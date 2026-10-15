"""Package metadata stays consistent between pyproject.toml and the package."""
import re
from pathlib import Path

import smart_investor

ROOT = Path(__file__).resolve().parents[1]


def test_version_matches_pyproject():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    assert match, "version not found in pyproject.toml"
    assert match.group(1) == smart_investor.__version__
