#!/usr/bin/env bash
# Shared helpers for the pre-commit review hook.
# review_hash MODE  -> prints a hash of the pending diff, nothing if the diff is empty.
#   MODE=staged : what `git commit` would record (index vs HEAD)
#   MODE=all    : tracked changes vs HEAD (`git commit -a`, `-o`, pathspec commits)
review_hash() {
  local d base
  if [ "$1" = all ]; then
    if git rev-parse -q --verify HEAD >/dev/null 2>&1; then base=HEAD
    else base=4b825dc642cb6eb9a060e54bf8d69288fbee4904; fi   # empty tree: first commit
    d=$(git diff "$base" --no-color --no-textconv --no-ext-diff)
  else
    d=$(git diff --cached --no-color --no-textconv --no-ext-diff)
  fi
  [ -n "$d" ] && printf '%s' "$d" | git hash-object --stdin
  return 0
}
