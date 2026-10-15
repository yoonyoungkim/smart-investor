"""Tests for .githooks/cross_review.py: reviewer selection, parsing, blocking policy, and the real
git pre-commit flow with fake `agy` / `claude` executables on PATH."""
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("cross_review", ROOT / ".githooks" / "cross_review.py")
cr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cr)


class TestUnits:
    def test_claude_session_is_reviewed_by_agy(self):
        assert cr.pick_reviewer({"CLAUDE_CODE_CHILD_SESSION": "1"}) == "agy"

    def test_everything_else_is_reviewed_by_claude(self):
        assert cr.pick_reviewer({}) == "claude"
        assert cr.pick_reviewer({"CLAUDECODE": "1"}) == "claude"      # IDE-terminal marker is not a Claude commit

    def test_override(self):
        assert cr.pick_reviewer({"REVIEW_WITH": "claude", "CLAUDE_CODE_CHILD_SESSION": "1"}) == "claude"
        assert cr.pick_reviewer({"REVIEW_WITH": "AGY"}) == "agy"
        assert cr.pick_reviewer({"REVIEW_WITH": "bogus"}) == "claude"

    def test_parse_with_surrounding_text_and_unknown_severity(self):
        text = 'sure:\n' + json.dumps({"summary": "s", "findings": [
            {"severity": "CRITICAL", "file": "a.py", "line": 3, "issue": "i"},
            {"severity": "weird", "issue": "j"}]}) + '\nthanks'
        summary, findings = cr.parse_review(text)
        assert summary == "s" and [f["severity"] for f in findings] == ["critical", "minor"]

    def test_parse_rejects_garbage(self):
        with pytest.raises(Exception):
            cr.parse_review("nothing here")

    def test_findings_capped(self):
        text = json.dumps({"findings": [{"severity": "minor", "issue": "x"}] * 40})
        assert len(cr.parse_review(text)[1]) == 15

    def test_clean_env_drops_git_vars_and_github_tokens_but_keeps_home(self):
        env = cr.clean_env({"GIT_INDEX_FILE": "x", "GITHUB_TOKEN": "t", "GH_TOKEN": "t", "HOME": "/h", "PATH": "/p"})
        assert env == {"HOME": "/h", "PATH": "/p"}


FAKE = """#!/usr/bin/env python3
import json, os, sys
log = os.environ["CALL_LOG"]
with open(log, "a") as fh:
    fh.write(json.dumps({"tool": os.path.basename(sys.argv[0]), "args": sys.argv[1:], "cwd": os.getcwd(),
                         "has_request": os.path.exists("review_request.md"),
                         "stdin": sys.stdin.read() if not sys.stdin.isatty() and "agy" not in sys.argv[0] else ""}) + "\\n")
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "crash":
    sys.stderr.write("authentication required"); sys.exit(1)
resp = open(os.environ["FAKE_RESPONSE"]).read()
if "agy" in os.path.basename(sys.argv[0]):
    print(json.dumps({"status": "SUCCESS", "response": resp}))
else:
    print(json.dumps({"result": resp, "is_error": False}))
"""


@pytest.fixture
def repo(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("agy", "claude"):
        p = bin_dir / name
        p.write_text(FAKE)
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    r = tmp_path / "repo"
    r.mkdir()
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "CALL_LOG": str(tmp_path / "calls.jsonl"),
           "FAKE_RESPONSE": str(tmp_path / "resp.json"), "GIT_CONFIG_NOSYSTEM": "1"}

    def git(*args, extra=None, check=True):
        e = {**env, **(extra or {})}
        return subprocess.run(["git", *args], cwd=r, env=e, capture_output=True, text=True, check=check)
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t"); git("config", "user.name", "t")
    git("config", "core.hooksPath", str(ROOT / ".githooks"))
    (r / "a.py").write_text("print(1)\n")
    git("add", "a.py")

    def respond(findings, summary="ok"):
        (tmp_path / "resp.json").write_text(json.dumps({"summary": summary, "findings": findings}))

    def calls():
        p = tmp_path / "calls.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []
    return git, respond, calls, r


IMPORTANT = [{"severity": "important", "file": "a.py", "line": 1, "issue": "bug", "fix": "fix it"}]
MINOR = [{"severity": "minor", "file": "a.py", "line": 1, "issue": "nit"}]
FROM_CLAUDE = {"CLAUDE_CODE_CHILD_SESSION": "1"}


class TestGitFlow:
    def test_claude_commit_is_reviewed_by_agy_and_blocked_on_important(self, repo):
        git, respond, calls, r = repo
        respond(IMPORTANT)
        res = git("commit", "-m", "x", extra=FROM_CLAUDE, check=False)
        assert res.returncode != 0 and "commit blocked" in res.stderr and "reviewed by agy" in res.stderr
        assert [c["tool"] for c in calls()] == ["agy"]
        c = calls()[0]
        assert c["has_request"] and Path(c["cwd"]) != r            # empty temp workspace, not the repo
        assert "--output-format" in c["args"] and "json" in c["args"]

    def test_non_claude_commit_is_reviewed_by_claude(self, repo):
        git, respond, calls, _ = repo
        respond([{"severity": "critical", "file": "a.py", "issue": "rce"}])
        res = git("commit", "-m", "x", check=False)
        assert res.returncode != 0 and "reviewed by claude" in res.stderr
        c = calls()[0]
        assert c["tool"] == "claude" and "--tools" in c["args"] and "<diff>" in c["stdin"] and "print(1)" in c["stdin"]

    def test_minor_only_passes_and_prints(self, repo):
        git, respond, calls, _ = repo
        respond(MINOR)
        res = git("commit", "-m", "x", extra=FROM_CLAUDE)
        assert "[minor]" in res.stderr
        assert git("log", "--oneline").stdout.strip()

    def test_clean_review_commits(self, repo):
        git, respond, _, _ = repo
        respond([])
        assert git("commit", "-m", "x").returncode == 0

    def test_skip_review_bypasses_everything(self, repo):
        git, respond, calls, _ = repo
        respond(IMPORTANT)
        assert git("commit", "-m", "x", extra={"SKIP_REVIEW": "1"}).returncode == 0
        assert calls() == []

    def test_missing_reviewer_cli_allows_commit_with_warning(self, repo, tmp_path):
        git, respond, calls, _ = repo
        respond(IMPORTANT)
        (tmp_path / "bin" / "agy").unlink()
        res = git("commit", "-m", "x", extra=FROM_CLAUDE)
        assert "not found" in res.stderr and calls() == []

    def test_reviewer_crash_allows_commit_with_login_hint(self, repo):
        git, respond, _, _ = repo
        respond(IMPORTANT)
        res = git("commit", "-m", "x", extra={**FROM_CLAUDE, "FAKE_MODE": "crash"})
        assert "review failed" in res.stderr and "log in" in res.stderr

    def test_garbage_response_allows_commit(self, repo, tmp_path):
        git, respond, _, _ = repo
        (tmp_path / "resp.json").write_text("I refuse")
        res = git("commit", "-m", "x")
        assert "review failed" in res.stderr

    def test_commit_dash_a_reviews_unstaged_tracked_changes(self, repo):
        git, respond, calls, r = repo
        respond([])
        git("commit", "-q", "-m", "base", extra={"SKIP_REVIEW": "1"})
        (r / "a.py").write_text("print(2)\n")
        git("commit", "-a", "-m", "y")
        assert "print(2)" in calls()[0]["stdin"]

    def test_empty_staged_diff_skips_review(self, repo):
        git, respond, calls, _ = repo
        respond(IMPORTANT)
        git("commit", "-q", "-m", "base", extra={"SKIP_REVIEW": "1"})
        git("commit", "--allow-empty", "-m", "empty")
        assert calls() == []
