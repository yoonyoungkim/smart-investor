"""Tests for .github/scripts/risk_review.py (PR risk scoring and merge decision)."""
import importlib.util
import json
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "risk_review.py"
_spec = importlib.util.spec_from_file_location("risk_review", _PATH)
rr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rr)


def f(name, add=0, dele=0, status="modified", patch="x"):
    return {"filename": name, "additions": add, "deletions": dele, "status": status, "patch": patch}


def llm(sec=0, brk=0, blockers=()):
    return {"security": (sec, []), "breaking": (brk, []), "blockers": list(blockers), "summary": "", "findings": []}


class TestScope:
    def test_small_pr_scores_zero(self):
        assert rr.score_scope([f(f"a{i}.py", 20) for i in range(5)])[0] == 0

    def test_many_files_hits_max(self):
        assert rr.score_scope([f(f"a{i}.py", 1) for i in range(30)])[0] == rr.MAX["scope"]

    def test_single_huge_file_hits_max(self):
        assert rr.score_scope([f("a.py", 2000)])[0] == rr.MAX["scope"]

    def test_monotonic(self):
        sizes = [10, 100, 400, 1000, 2000]
        scores = [rr.score_scope([f("a.py", s)])[0] for s in sizes]
        assert scores == sorted(scores)


class TestTests:
    def test_source_without_tests_is_full(self):
        assert rr.score_tests([f("src/a.py", 50)])[0] == rr.MAX["tests"]

    def test_docs_only_is_zero(self):
        assert rr.score_tests([f("README.md", 50)])[0] == 0

    def test_well_tested_change_is_zero(self):
        assert rr.score_tests([f("src/a.py", 40), f("tests/test_a.py", 30)])[0] == 0

    def test_thin_tests_partial(self):
        pts = rr.score_tests([f("src/a.py", 100), f("tests/test_a.py", 10)])[0]
        assert 0 < pts < rr.MAX["tests"]

    def test_removed_tests_penalised(self):
        base = rr.score_tests([f("src/a.py", 40), f("tests/test_a.py", 30)])[0]
        worse = rr.score_tests([f("src/a.py", 40), f("tests/test_a.py", 30), f("tests/test_b.py", 0, 80, "removed")])[0]
        assert worse == base + 5


class TestMigration:
    def test_nothing(self):
        assert rr.score_migration([f("src/a.py", 5)])[0] == 0

    def test_model_without_migration_is_full(self):
        assert rr.score_migration([f("src/smart_investor/db/models.py", 5)])[0] == rr.MAX["migration"]

    def test_migration_script(self):
        assert rr.score_migration([f("scripts/migrate_add_x.py", 5)])[0] == 10

    def test_env_var_added_in_code(self):
        patch = '+x = os.getenv("NEW_KEY")'
        assert rr.score_migration([f("src/a.py", 1, patch=patch)])[0] == 5

    def test_dependency_file(self):
        assert rr.score_migration([f("requirements.txt", 1)])[0] == 5


class TestHardStopsAndFloors:
    def test_workflow_change_is_hard_stop(self):
        assert rr.hard_stops([f(".github/workflows/x.yml", 1)], False)

    def test_claude_dir_is_hard_stop(self):
        assert rr.hard_stops([f(".claude/hooks/x.sh", 1)], False)

    def test_githooks_is_hard_stop_and_security_floor(self):
        assert rr.hard_stops([f(".githooks/pre-commit", 1)], False)
        assert rr.security_floor([f(".githooks/cross_review.py", 1)])[0] == 10

    def test_truncated_is_hard_stop(self):
        assert rr.hard_stops([f("a.py", 1)], True)

    def test_plain_change_has_none(self):
        assert rr.hard_stops([f("src/a.py", 1)], False) == []

    def test_security_floor_on_sensitive_path(self):
        assert rr.security_floor([f("src/auth/login.py", 1)])[0] == 10

    def test_manipulated_llm_cannot_lower_below_floor_or_auto_merge(self):
        files = [f(".github/workflows/x.yml", 1), f("tests/test_a.py", 1)]
        axes, total, stops = rr.assess(files, False, llm(sec=0, brk=0))
        assert axes["security"][0] >= 10
        assert rr.decide(total, stops, [], 30, 61) == "human"


class TestDecision:
    @pytest.mark.parametrize("total,expected", [(0, "auto_merge"), (30, "auto_merge"), (31, "human"),
                                                (60, "human"), (61, "block"), (100, "block")])
    def test_thresholds(self, total, expected):
        assert rr.decide(total, [], [], 30, 61) == expected

    def test_blocker_forces_block_even_when_score_low(self):
        assert rr.decide(5, [], ["hardcoded secret"], 30, 61) == "block"

    def test_hard_stop_prevents_auto_merge(self):
        assert rr.decide(5, ["x"], [], 30, 61) == "human"

    def test_llm_unavailable_fails_closed_to_human(self):
        axes, total, stops = rr.assess([f("src/a.py", 1), f("tests/test_a.py", 1)], False, None)
        assert "LLM review unavailable" in stops
        assert rr.decide(total, stops, [], 30, 61) == "human"

    def test_totals_never_exceed_100(self):
        files = [f(f"src/auth/a{i}.py", 200) for i in range(40)] + [f("src/smart_investor/db/models.py", 5)]
        _, total, _ = rr.assess(files, False, llm(sec=30, brk=20))
        assert total <= 100


class TestLLMParsing:
    def test_parses_json_with_surrounding_text_and_clamps(self):
        text = 'Here you go:\n' + json.dumps({"security": {"score": 99, "reasons": ["a"]},
                                               "breaking": {"score": -4}, "blockers": [], "summary": "ok"}) + "\nbye"
        out = rr.parse_llm(text)
        assert out["security"][0] == 30 and out["breaking"][0] == 0

    def test_rejects_garbage(self):
        with pytest.raises(Exception):
            rr.parse_llm("no json here")

    def test_rejects_missing_scores(self):
        with pytest.raises(Exception):
            rr.parse_llm('{"security": {}, "breaking": {}}')

    def test_findings_capped(self):
        text = json.dumps({"security": {"score": 1}, "breaking": {"score": 1},
                           "findings": [{"file": "a", "comment": "c"}] * 30})
        assert len(rr.parse_llm(text)["findings"]) == 10


class TestDiffAndRender:
    def test_diff_truncation_flagged(self):
        files = [f("a.py", 1, patch="p" * 100), f("b.py", 1, patch="p" * 100)]
        _, truncated = rr.build_diff(files, 150)
        assert truncated

    def test_missing_patch_counts_as_truncated(self):
        _, truncated = rr.build_diff([f("big.py", 5000, patch=None)], 10_000)
        assert truncated

    def test_render_has_marker_total_and_axes(self):
        axes, total, stops = rr.assess([f("src/a.py", 1), f("tests/test_a.py", 1)], False, llm())
        body = rr.render(axes, total, "auto_merge", stops, llm(), "", 30, 61)
        assert rr.MARK in body and f"{total} / 100" in body and "Security" in body and "Migration" in body


def review(verdict="pass", edits=(), issues=(), summary="s"):
    return {"verdict": verdict, "summary": summary, "edits": list(edits), "issues": list(issues), "note": ""}


PASS_REVIEW = review()


class FakeGH:
    """In-memory stand-in for GH: records comments, labels and merges."""
    pr = {}
    files_ = []
    ci = (True, "success")
    log = None

    def __init__(self, repo, token):
        type(self).log = {"comments": [], "labels": [], "merged": [], "deleted": [], "flags": [], "reviews": [],
                          "pushed": [], "token": token}

    def call(self, method, path, body=None, ok_404=False):
        if method == "GET":
            return type(self).pr
        if method == "DELETE":
            type(self).log["deleted"].append(path)
        return {}

    def files(self, n):
        return type(self).files_, False

    def upsert_comment(self, n, body):
        type(self).log["comments"].append(body)

    def set_label(self, n, label):
        type(self).log["labels"].append(label)

    def wait_for_ci(self, sha, name, timeout):
        return type(self).ci

    def merge(self, n, sha, title):
        type(self).log["merged"].append((n, sha))

    commits = []
    texts = {}
    push_error = None
    approve_error = None

    def set_flag(self, n, label, on):
        type(self).log["flags"].append((label, on))

    def pr_commits(self, n):
        return [{"commit": {"message": m}} for m in type(self).commits]

    def get_text(self, path, ref):
        return type(self).texts[path]

    def review(self, n, sha, event, body, comments=None):
        if event == "APPROVE" and type(self).approve_error:
            raise RuntimeError(type(self).approve_error)
        type(self).log["reviews"].append((event, comments))

    def push_changes(self, branch, base_sha, changes, message):
        if type(self).push_error:
            raise RuntimeError(type(self).push_error)
        type(self).log["pushed"].append((branch, base_sha, changes, message))


@pytest.fixture
def run_main(monkeypatch):
    def _run(files, *, llm_result=None, llm_raises=False, ci=(True, "success"), fork=False, review_result=None,
             review_raises=False, push_token=None, commits=(), texts=None, push_error=None, approve_error=None):
        monkeypatch.setenv("REPO", "o/r"); monkeypatch.setenv("GITHUB_TOKEN", "t"); monkeypatch.setenv("PR_NUMBER", "7")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        FakeGH.pr = {"title": "t", "body": "", "head": {"sha": "abc", "ref": "feat/x",
                                                         "repo": {"full_name": "fork/r" if fork else "o/r"}}}
        FakeGH.files_, FakeGH.ci = files, ci
        FakeGH.commits, FakeGH.texts = list(commits), texts or {}
        FakeGH.push_error, FakeGH.approve_error = push_error, approve_error
        monkeypatch.setattr(rr, "GH", FakeGH)
        monkeypatch.delenv("BOT_PUSH_TOKEN", raising=False)
        if push_token:
            monkeypatch.setenv("BOT_PUSH_TOKEN", push_token)

        def fake_llm(*a, **k):
            if k.get("system") == rr.REVIEW_SYSTEM:
                if review_raises:
                    raise RuntimeError("review boom sk-secret")
                return review_result or PASS_REVIEW
            if llm_raises:
                raise RuntimeError("boom")
            return llm_result or {"security": (0, []), "breaking": (0, []), "blockers": [], "summary": "", "findings": []}
        monkeypatch.setattr(rr, "call_llm", fake_llm)
        rc = rr.main()
        return rc, FakeGH.log
    return _run


SAFE = [f("src/a.py", 20), f("tests/test_a.py", 20)]


class TestMainFlow:
    def test_low_risk_with_green_ci_merges_and_deletes_branch(self, run_main):
        rc, log = run_main(SAFE)
        assert rc == 0 and log["merged"] == [(7, "abc")] and log["labels"] == ["risk:low"]
        assert log["reviews"] == [("APPROVE", None)] and log["flags"][-1] == (rr.REVIEW_LABEL, False)
        assert any("heads/feat/x" in p for p in log["deleted"])

    def test_red_ci_does_not_merge(self, run_main):
        rc, log = run_main(SAFE, ci=(False, "failure"))
        assert rc == 0 and log["merged"] == [] and "not merged" in log["comments"][-1]

    def test_high_risk_blocks_with_nonzero_exit(self, run_main):
        big = [f(f"src/auth/a{i}.py", 200) for i in range(30)]
        rc, log = run_main(big, llm_result={"security": (30, []), "breaking": (20, []), "blockers": [], "summary": "", "findings": []})
        assert rc == 1 and log["merged"] == [] and log["labels"] == ["risk:high"]

    def test_llm_blocker_blocks_even_small_pr(self, run_main):
        rc, log = run_main(SAFE, llm_result={"security": (5, []), "breaking": (0, []), "blockers": ["hardcoded secret"],
                                              "summary": "", "findings": []})
        assert rc == 1 and log["merged"] == []

    def test_llm_failure_goes_to_human_not_merge(self, run_main):
        rc, log = run_main(SAFE, llm_raises=True)
        assert rc == 0 and log["merged"] == [] and log["labels"] == ["risk:medium"]

    def test_workflow_change_never_auto_merges(self, run_main):
        rc, log = run_main(SAFE + [f(".github/workflows/x.yml", 1)])
        assert log["merged"] == [] and log["labels"] == ["risk:medium"]

    def test_fork_pr_is_skipped(self, run_main):
        rc, log = run_main(SAFE, fork=True)
        assert rc == 0 and log["merged"] == [] and "Skipped" in log["comments"][0]


GOOD = {"security": {"score": 4, "reasons": ["r"]}, "breaking": {"score": 2}, "blockers": [], "summary": "ok"}


class _Proc:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


class TestClaudeCli:
    def _run(self, monkeypatch, proc):
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"], seen["kw"] = cmd, kw
            return proc
        monkeypatch.setattr(rr.subprocess, "run", fake_run)
        monkeypatch.setenv("GITHUB_TOKEN", "ghs_secret")
        out = rr.call_claude_cli("t", "b", "diff", "oauth-token", "claude-sonnet-5-5")
        return out, seen

    def test_parses_result_text(self, monkeypatch):
        out, _ = self._run(monkeypatch, _Proc(json.dumps({"result": "```json\n" + json.dumps(GOOD) + "\n```", "is_error": False})))
        assert out["security"][0] == 4 and out["breaking"][0] == 2

    def test_parses_structured_output(self, monkeypatch):
        out, _ = self._run(monkeypatch, _Proc(json.dumps({"structured_output": GOOD, "result": ""})))
        assert out["security"][0] == 4

    def test_tools_disabled_and_no_bare_and_github_token_not_forwarded(self, monkeypatch):
        _, seen = self._run(monkeypatch, _Proc(json.dumps({"result": json.dumps(GOOD)})))
        cmd = seen["cmd"]
        assert cmd[cmd.index("--tools") + 1] == ""
        assert "--bare" not in cmd and "--no-session-persistence" in cmd
        assert seen["kw"]["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth-token"
        assert "GITHUB_TOKEN" not in seen["kw"]["env"] and "ANTHROPIC_API_KEY" not in seen["kw"]["env"]
        assert seen["kw"]["input"].startswith("PR title: t")          # diff goes via stdin, not argv

    def test_nonzero_exit_raises(self, monkeypatch):
        with pytest.raises(RuntimeError):
            self._run(monkeypatch, _Proc("", 1, "auth failed"))

    def test_is_error_raises(self, monkeypatch):
        with pytest.raises(RuntimeError):
            self._run(monkeypatch, _Proc(json.dumps({"is_error": True, "result": "Login expired"})))


class TestCredentialSelection:

    def test_api_key_preferred_then_oauth_then_none(self, monkeypatch):
        calls = []
        def pick(name):
            return lambda *a, **k: calls.append(name) or (review() if k.get("system") == rr.REVIEW_SYSTEM else llm())
        monkeypatch.setattr(rr, "call_llm", pick("api"))
        monkeypatch.setattr(rr, "call_claude_cli", pick("cli"))
        monkeypatch.setattr(rr, "GH", FakeGH)
        monkeypatch.setenv("REPO", "o/r"); monkeypatch.setenv("GITHUB_TOKEN", "t"); monkeypatch.setenv("PR_NUMBER", "7")
        FakeGH.pr = {"title": "t", "body": "", "head": {"sha": "abc", "ref": "x", "repo": {"full_name": "o/r"}}}
        FakeGH.files_, FakeGH.ci = SAFE, (True, "success")

        def go(key, oauth):
            for n, v in (("ANTHROPIC_API_KEY", key), ("CLAUDE_CODE_OAUTH_TOKEN", oauth)):
                monkeypatch.delenv(n, raising=False)
                if v:
                    monkeypatch.setenv(n, v)
            calls.clear()
            rc = rr.main()
            return list(calls), FakeGH.log

        assert set(go("k", "o")[0]) == {"api"}
        assert set(go(None, "o")[0]) == {"cli"}
        c, log = go(None, None)                      # no credential: fail closed, no merge
        assert c == [] and log["merged"] == []


class TestParseReview:
    def test_valid(self):
        r = rr.parse_review(json.dumps({"verdict": "minor", "summary": "x",
                                         "edits": [{"file": "a.md", "find": "teh", "replace": "the"}], "issues": []}))
        assert r["verdict"] == "minor" and r["edits"][0]["replace"] == "the"

    def test_bad_verdict_rejected(self):
        with pytest.raises(ValueError):
            rr.parse_review(json.dumps({"verdict": "lgtm"}))

    def test_pass_with_issues_is_downgraded(self):
        r = rr.parse_review(json.dumps({"verdict": "pass", "issues": [{"file": "a.py", "line": 1, "comment": "bug"}]}))
        assert r["verdict"] == "needs_dev"

    def test_minor_with_issues_or_without_edits_is_downgraded(self):
        assert rr.parse_review(json.dumps({"verdict": "minor"}))["verdict"] == "needs_dev"
        both = {"verdict": "minor", "edits": [{"file": "a.md", "find": "a", "replace": "b"}],
                "issues": [{"file": "a.py", "comment": "bug"}]}
        assert rr.parse_review(json.dumps(both))["verdict"] == "needs_dev"


class TestPlanEdits:
    def plan(self, edits, text, path="src/a.py", status="modified"):
        files = [f(path, status=status)]
        return rr.plan_edits(review("minor", [dict(file=path, reason="r", **e) for e in edits]), files, lambda p: text)

    def test_comment_typo_is_allowed(self):
        ok, why, ch = self.plan([{"find": "# teh value", "replace": "# the value"}], "x = 1  # teh value\n")
        assert ok and ch["src/a.py"] == "x = 1  # the value\n"

    def test_docstring_change_is_allowed(self):
        src = 'def f():\n    """Retrun x."""\n    return 1\n'
        assert self.plan([{"find": "Retrun", "replace": "Return"}], src)[0]

    def test_code_change_is_refused(self):
        ok, why, _ = self.plan([{"find": "return 1", "replace": "return 2"}], "def f():\n    return 1\n")
        assert not ok and "behaviour" in why

    def test_string_literal_change_is_refused(self):
        assert not self.plan([{"find": "'teh'", "replace": "'the'"}], "x = 'teh'\n")[0]

    def test_ambiguous_or_missing_find_is_refused(self):
        assert not self.plan([{"find": "a", "replace": "b"}], "# a\n# a\n")[0]
        assert not self.plan([{"find": "zzz", "replace": "b"}], "# a\n")[0]

    def test_file_outside_pr_or_sensitive_or_wrong_type_refused(self):
        r = review("minor", [dict(file="other.md", find="a", replace="b", reason="")])
        assert not rr.plan_edits(r, [f("a.md")], lambda p: "a")[0]
        assert not self.plan([{"find": "a", "replace": "b"}], "# a", path=".github/scripts/x.py")[0]
        assert not self.plan([{"find": "a", "replace": "b"}], "a", path="src/auth.py")[0]
        assert not self.plan([{"find": "a", "replace": "b"}], "a", path="src/run.sh")[0]

    def test_markdown_allowed_and_size_capped(self):
        assert self.plan([{"find": "teh", "replace": "the"}], "teh doc", path="README.md")[0]
        big = "\n".join(f"l{i}" for i in range(40))
        assert not self.plan([{"find": big, "replace": big.replace("l", "L")}], big, path="README.md")[0]


class TestInlineComments:
    PATCH = "@@ -1,2 +10,3 @@\n ctx\n+new1\n+new2\n"

    def test_added_lines(self):
        assert rr.added_lines(self.PATCH) == {11, 12}

    def test_only_lines_in_diff_become_inline(self):
        files = [f("a.py", patch=self.PATCH)]
        issues = [{"file": "a.py", "line": 11, "severity": "high", "comment": "c"},
                  {"file": "a.py", "line": 99, "severity": "low", "comment": "c"},
                  {"file": "b.py", "line": 11, "severity": "low", "comment": "c"}]
        out = rr.inline_comments(files, issues)
        assert [c["line"] for c in out] == [11] and out[0]["side"] == "RIGHT"


class TestReviewFlow:
    FIX = review("minor", [{"file": "src/a.py", "find": "# teh", "replace": "# the", "reason": "typo"}])
    TEXTS = {"src/a.py": "x = 1  # teh\n"}

    def test_pass_and_low_risk_approves_and_merges(self, run_main):
        rc, log = run_main(SAFE)
        assert log["merged"] == [(7, "abc")] and log["reviews"][0][0] == "APPROVE"

    def test_needs_dev_blocks_merge_flags_and_comments_inline(self, run_main):
        patch = "@@ -1,1 +1,2 @@\n ctx\n+bad\n"
        files = [f("src/a.py", 20, patch=patch), f("tests/test_a.py", 20)]
        rv = review("needs_dev", issues=[{"file": "src/a.py", "line": 2, "severity": "high", "comment": "bug"}])
        rc, log = run_main(files, review_result=rv)
        assert rc == 0 and log["merged"] == [] and (rr.REVIEW_LABEL, True) in log["flags"]
        assert log["reviews"] == [("COMMENT", [{"path": "src/a.py", "line": 2, "side": "RIGHT", "body": "**[high]** bug"}])]
        assert "developer check needed" in log["comments"][-1]

    def test_high_risk_with_passing_review_flags_and_does_not_merge(self, run_main):
        rc, log = run_main(SAFE + [f(".github/workflows/x.yml", 1)])
        assert log["merged"] == [] and (rr.REVIEW_LABEL, True) in log["flags"] and log["reviews"] == []

    def test_review_unavailable_goes_to_dev_and_reports_error_without_secret(self, run_main):
        rc, log = run_main(SAFE, review_raises=True)
        assert log["merged"] == [] and "LLM errors" in log["comments"][-1] and "review boom" in log["comments"][-1]

    def test_minor_fix_is_pushed_and_run_ends_without_merge(self, run_main):
        rc, log = run_main(SAFE, review_result=self.FIX, push_token="pat", texts=self.TEXTS)
        assert rc == 0 and log["merged"] == [] and len(log["pushed"]) == 1
        branch, base, changes, msg = log["pushed"][0]
        assert branch == "feat/x" and base == "abc" and changes == {"src/a.py": "x = 1  # the\n"} and rr.FIX_MARK in msg
        assert log["token"] == "pat"                       # push uses the PAT, not GITHUB_TOKEN

    def test_minor_without_push_token_goes_to_dev(self, run_main):
        rc, log = run_main(SAFE, review_result=self.FIX, texts=self.TEXTS)
        assert log["pushed"] == [] and log["merged"] == [] and "BOT_PUSH_TOKEN" in log["comments"][-1]

    def test_fix_round_limit(self, run_main):
        rc, log = run_main(SAFE, review_result=self.FIX, push_token="pat", texts=self.TEXTS,
                           commits=[f"fix {rr.FIX_MARK}"] * rr.MAX_FIX_ROUNDS)
        assert log["pushed"] == [] and log["merged"] == [] and "limit" in log["comments"][-1]

    def test_behaviour_changing_edit_is_not_pushed(self, run_main):
        bad = review("minor", [{"file": "src/a.py", "find": "x = 1", "replace": "x = 2", "reason": "r"}])
        rc, log = run_main(SAFE, review_result=bad, push_token="pat", texts=self.TEXTS)
        assert log["pushed"] == [] and log["merged"] == []

    def test_push_failure_goes_to_dev(self, run_main):
        rc, log = run_main(SAFE, review_result=self.FIX, push_token="pat", texts=self.TEXTS, push_error="not ff pat")
        assert log["merged"] == [] and "push failed" in log["comments"][-1] and "pat" not in log["comments"][-1].replace("push", "")

    def test_approve_failure_still_merges_with_note(self, run_main):
        rc, log = run_main(SAFE, approve_error="403 cannot approve")
        assert log["merged"] == [(7, "abc")] and "approve skipped" in log["comments"][-1]
