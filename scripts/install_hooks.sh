#!/usr/bin/env bash
# Point git at the repo's hooks (pre-commit cross-model review). Run once per clone.
set -eu
cd "$(git rev-parse --show-toplevel)"
chmod +x .githooks/pre-commit .githooks/cross_review.py
git config core.hooksPath .githooks
echo "core.hooksPath -> .githooks (cross-review pre-commit enabled)"
