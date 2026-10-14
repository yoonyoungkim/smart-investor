"""Tests for the recommendation CLI's defaults.

Notifying and writing the report are on by default so a scheduled run needs no
flags; these pin the opt-outs and the unconfigured-machine behaviour.
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "recommend_stocks", Path(__file__).parent.parent / "scripts" / "recommend_stocks.py"
)
recommend = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(recommend)


@pytest.fixture
def no_env(monkeypatch):
    """Stop .env from supplying a token the test did not set."""
    monkeypatch.setattr("smart_investor.db.config.load_env", lambda: None)
    monkeypatch.delenv("SLACK_TOKEN", raising=False)


def args(**overrides):
    """Build a minimal argument namespace."""
    base = {"no_notify": False, "notify": None}
    base.update(overrides)
    return SimpleNamespace(**base)


class TestDefaultChannels:
    """Slack is the default target when it is actually configured."""

    def test_slack_by_default_when_token_present(self, no_env, monkeypatch):
        monkeypatch.setenv("SLACK_TOKEN", "xoxb-test")

        assert recommend._requested_channels(args()) == ["slack"]

    def test_nothing_without_a_token(self, no_env):
        """Defaulting to a channel that cannot deliver would fail every run."""
        assert recommend._requested_channels(args()) == []

    def test_no_notify_wins_over_token(self, no_env, monkeypatch):
        monkeypatch.setenv("SLACK_TOKEN", "xoxb-test")

        assert recommend._requested_channels(args(no_notify=True)) == []

    def test_explicit_notify_overrides_default(self, no_env):
        assert recommend._requested_channels(args(notify="telegram")) == ["telegram"]

    def test_explicit_notify_works_without_a_slack_token(self, no_env):
        """--notify is a deliberate request, so it is honoured either way."""
        assert recommend._requested_channels(args(notify="slack")) == ["slack"]

    def test_comma_separated_channels(self, no_env):
        assert recommend._requested_channels(
            args(notify="slack, telegram")
        ) == ["slack", "telegram"]

    def test_blank_entries_ignored(self, no_env):
        assert recommend._requested_channels(args(notify="slack,,")) == ["slack"]

    def test_no_notify_wins_over_explicit_notify(self, no_env):
        assert recommend._requested_channels(args(no_notify=True, notify="slack")) == []


class TestParserDefaults:
    """Report and notification are on unless explicitly turned off."""

    def parse(self, argv):
        """Parse arguments through the real parser."""
        return recommend.build_parser().parse_args(argv)

    def test_excel_on_by_default(self):
        assert self.parse(["--market", "KR"]).excel == "auto"

    def test_no_excel_turns_it_off(self):
        parsed = self.parse(["--market", "KR", "--no-excel"])
        assert parsed.no_excel is True

    def test_excel_accepts_a_path(self):
        assert self.parse(["--excel", "/tmp/r.xlsx"]).excel == "/tmp/r.xlsx"

    def test_bare_excel_flag_means_auto(self):
        assert self.parse(["--excel"]).excel == "auto"

    def test_notify_unset_by_default(self):
        """Left to _requested_channels, which checks for a usable token."""
        assert self.parse(["--market", "KR"]).notify is None

    def test_no_notify_flag(self):
        assert self.parse(["--no-notify"]).no_notify is True

    def test_strategy_defaults_to_none(self):
        """None means the dividend set, preserving the pre-strategy behaviour."""
        assert self.parse([]).strategy is None

    def test_strategy_accepts_both(self):
        assert self.parse(["--strategy", "both"]).strategy == "both"
