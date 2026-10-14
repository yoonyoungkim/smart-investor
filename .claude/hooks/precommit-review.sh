#!/usr/bin/env bash
# PreToolUse hook (Bash): block `git commit` until the pending changes have been
# code-reviewed. Review is recorded by mark-reviewed.sh as a hash of the diff;
# any later change to the diff invalidates it.
# Bypass for one commit: start the command with SKIP_REVIEW=1 (e.g. SKIP_REVIEW=1 git commit ...).
# Not covered: `git -C other commit`, `cd other && git commit` (checks the project repo only).
set -u

if ! command -v python3 >/dev/null 2>&1; then
  echo "precommit-review: python3 not found - commit review hook is NOT enforced." >&2
  exit 1
fi

mode=$(python3 -c '
import json, os, re, shlex, sys
try:
    cmd = json.load(sys.stdin).get("tool_input", {}).get("command", "") or ""
except Exception as e:
    sys.stderr.write("precommit-review: cannot parse hook input: %s\n" % e); sys.exit(3)

GVAL = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env"}
SHORTVAL = set("mFCct")
LONGVAL = {"--message", "--file", "--reuse-message", "--reedit-message", "--template", "--author",
           "--date", "--cleanup", "--fixup", "--squash", "--trailer", "--pathspec-from-file"}
SEPS = {";", ";;", "&&", "||", "|", "|&", "&", "(", ")", "\n"}

def analyse(seg):
    i, bypass = 0, False
    while i < len(seg) and re.fullmatch(r"\w+=.*", seg[i], re.S):
        bypass = bypass or seg[i] == "SKIP_REVIEW=1"; i += 1
    if i >= len(seg) or os.path.basename(seg[i]) != "git": return None
    i += 1
    while i < len(seg) and seg[i].startswith("-"): i += 2 if seg[i] in GVAL else 1
    if i >= len(seg) or seg[i] != "commit": return None
    if bypass: return "skip"
    args, mode, j = seg[i + 1:], "staged", 0
    while j < len(args):
        a = args[j]; j += 1
        if a == "--":
            if j < len(args): mode = "all"
            break
        if a.startswith("--"):
            name = a.split("=")[0]
            if name in ("--all", "--only", "--include"): mode = "all"
            elif name in LONGVAL and "=" not in a: j += 1
        elif a.startswith("-") and len(a) > 1:
            for k, ch in enumerate(a[1:]):
                if ch in "aoi": mode = "all"
                if ch in SHORTVAL:
                    if k == len(a) - 2: j += 1
                    break
        else:
            mode = "all"          # pathspec: partial commit of working-tree content
    return mode

try:
    lex = shlex.shlex(cmd.replace("\\\n", " "), posix=True, punctuation_chars=";&|()\n")
    lex.whitespace = " \t\r"; lex.whitespace_split = True
    toks = list(lex)
except ValueError:
    print("staged" if re.search(r"\bgit\b.*\bcommit(?![\w-])", cmd, re.S) else ""); sys.exit(0)

segs, cur = [], []
for t in toks:
    if t in SEPS:
        segs.append(cur); cur = []
    else: cur.append(t)
segs.append(cur)
modes = [m for m in (analyse(s) for s in segs) if m and m != "skip"]
print("all" if "all" in modes else ("staged" if modes else ""))
'  <<<"$(cat)")
rc=$?
if [ $rc -ne 0 ]; then echo "precommit-review: hook failed (exit $rc) - commit review is NOT enforced." >&2; exit 1; fi
[ -z "$mode" ] && exit 0

cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0
. "$(dirname "$0")/review-lib.sh"

hash=$(review_hash "$mode")
[ -z "$hash" ] && exit 0      # nothing to review; let git report "nothing to commit"
marker="$(git rev-parse --git-dir)/claude-review-ok"
if [ -f "$marker" ] && [ "$(cat "$marker")" = "$hash" ]; then exit 0; fi

arg=""; [ "$mode" = "all" ] && arg=" all"
cat >&2 <<MSG
Commit blocked: these changes have not been code-reviewed yet.
1. Run the code-review skill (superpowers:requesting-code-review) on the pending diff
   ($( [ "$mode" = "all" ] && echo 'git diff HEAD' || echo 'git diff --cached' )) and fix every issue it reports.
2. Once the review is clean, run: .claude/hooks/mark-reviewed.sh${arg}
3. Retry the commit. (Editing the changes afterwards requires a new review.)
MSG
exit 2
