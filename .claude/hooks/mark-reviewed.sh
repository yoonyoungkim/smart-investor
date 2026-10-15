#!/usr/bin/env bash
# Record that the current diff has been code-reviewed (see precommit-review.sh).
# Usage: mark-reviewed.sh        # staged changes (git commit)
#        mark-reviewed.sh all    # tracked changes vs HEAD (git commit -a)
set -eu
cd "${CLAUDE_PROJECT_DIR:-.}"
. "$(dirname "$0")/review-lib.sh"
h=$(review_hash "${1:-staged}")
[ -n "$h" ] || { echo "Nothing to mark: diff is empty." >&2; exit 1; }
printf '%s' "$h" > "$(git rev-parse --git-dir)/claude-review-ok"
echo "Marked current diff as reviewed."
