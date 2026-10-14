"""Tests for the notification layer, including the Slack recommendation alert."""

import pytest

from smart_investor.models.stock import FilterResult, FinancialMetrics, Market
from smart_investor.notifications.base import NotificationResult, NotificationService
from smart_investor.notifications.slack import SlackNotifier


class Capturing(NotificationService):
    """Notification service that records the message instead of sending it."""

    def __init__(self):
        super().__init__()
        self.messages: list[str] = []

    async def send(self, message: str, **kwargs) -> NotificationResult:
        self.messages.append(message)
        return NotificationResult.ok("capture", "captured")


def _stock(ticker: str, yield_pct=None, years=0, debt=None, quick=None, market=Market.KR):
    """Build a passing FilterResult for the given metrics."""
    return FilterResult(
        ticker=ticker,
        passed=True,
        market=market,
        metrics=FinancialMetrics(
            ticker=ticker,
            market=market,
            dividend_yield=yield_pct,
            debt_ratio=debt,
            quick_ratio=quick,
            years_of_dividend=years,
        ),
    )


@pytest.fixture
def notifier():
    """Provide a capturing notification service."""
    return Capturing()


@pytest.fixture
def clean_env(monkeypatch):
    """Stop the base class reloading .env over the test's environment.

    NotificationService.__init__ calls load_env() so notifiers work before any
    database call; without this a developer's real .env would defeat monkeypatch.
    """
    monkeypatch.setattr("smart_investor.notifications.base.load_env", lambda: None)
    for name in ("SLACK_TOKEN", "SLACK_CHANNEL"):
        monkeypatch.delenv(name, raising=False)


class TestRecommendationMessage:
    """The recommendation report states what produced the list."""

    async def test_includes_header_and_market(self, notifier):
        await notifier.send_recommendation([_stock("005930", 4.5)], 100, market="KR")

        message = notifier.messages[0]
        assert "종목 추천 (KR)" in message

    async def test_includes_pass_rate(self, notifier):
        await notifier.send_recommendation([_stock("A", 4.0)], 200)

        assert "통과: 1 / 200 (0.5%)" in notifier.messages[0]

    async def test_lists_active_criteria(self, notifier):
        criteria = ["dividend_yield: 배당수익률 >= 4.0%", "debt_ratio: 부채비율 <= 200.0%"]
        await notifier.send_recommendation([_stock("A", 4.0)], 10, criteria=criteria)

        message = notifier.messages[0]
        assert "적용 조건 (2개)" in message
        for item in criteria:
            assert item in message

    def test_criteria_are_not_optional_context(self):
        """A threshold-configurable screen is meaningless without its criteria."""
        assert "criteria" in NotificationService.send_recommendation.__doc__

    async def test_omits_criteria_block_when_absent(self, notifier):
        await notifier.send_recommendation([_stock("A", 4.0)], 10)

        assert "적용 조건" not in notifier.messages[0]

    async def test_metrics_rendered(self, notifier):
        await notifier.send_recommendation(
            [_stock("020710", 9.26, years=5, debt=22.49, quick=103.36)], 100
        )

        message = notifier.messages[0]
        assert "020710" in message
        assert "배당 9.26%" in message
        assert "5년" in message
        assert "부채 22.5%" in message
        assert "당좌 103.4%" in message

    async def test_missing_metrics_are_skipped_not_zeroed(self, notifier):
        """Banks report no quick ratio; the line should omit it, not print 0."""
        await notifier.send_recommendation([_stock("105560", 3.1, years=5, quick=None)], 100)

        assert "당좌" not in notifier.messages[0]

    async def test_sorted_by_yield_descending(self, notifier):
        await notifier.send_recommendation(
            [_stock("LOW", 2.0), _stock("HIGH", 9.0), _stock("MID", 5.0)], 100
        )

        message = notifier.messages[0]
        assert message.index("HIGH") < message.index("MID") < message.index("LOW")

    async def test_truncates_long_lists(self, notifier):
        stocks = [_stock(f"T{i:03d}", float(i)) for i in range(30)]
        await notifier.send_recommendation(stocks, 100, limit=5)

        message = notifier.messages[0]
        assert "... 외 25종목" in message

    async def test_empty_result_says_so(self, notifier):
        await notifier.send_recommendation([], 2763)

        message = notifier.messages[0]
        assert "통과: 0 / 2,763" in message
        assert "조건을 모두 통과한 종목이 없습니다." in message

    async def test_zero_analyzed_does_not_divide_by_zero(self, notifier):
        await notifier.send_recommendation([], 0)

        assert "0.0%" in notifier.messages[0]

    async def test_stock_without_metrics(self, notifier):
        await notifier.send_recommendation(
            [FilterResult(ticker="BARE", passed=True, market=Market.US)], 10
        )

        assert "BARE" in notifier.messages[0]


class TestSlackNotifier:
    """Slack delivery, with the web client stubbed out."""

    def test_token_from_argument(self):
        assert SlackNotifier(token="xoxb-test").token == "xoxb-test"

    def test_token_from_environment(self, clean_env, monkeypatch):
        monkeypatch.setenv("SLACK_TOKEN", "xoxb-env")
        assert SlackNotifier().token == "xoxb-env"

    def test_channel_override(self):
        assert SlackNotifier(token="t", channel="#investing").default_channel == "#investing"

    def test_default_channel(self, clean_env):
        assert SlackNotifier(token="t").default_channel == "#smart-investor"

    async def test_missing_token_reports_clearly(self, clean_env):
        result = await SlackNotifier().send("hello")

        assert result.success is False
        assert "token" in result.error.lower()

    async def test_successful_send(self, monkeypatch):
        sent = {}

        class StubClient:
            async def chat_postMessage(self, **payload):  # noqa: N802 - Slack SDK name
                sent.update(payload)
                return {"ts": "1700000000.1", "channel": "C123"}

        notifier = SlackNotifier(token="xoxb-test", channel="#invest")
        monkeypatch.setattr(type(notifier), "client", property(lambda self: StubClient()))

        result = await notifier.send("배당 9.26%")

        assert result.success is True
        assert sent["channel"] == "#invest"
        assert sent["text"] == "배당 9.26%"
        assert sent["blocks"]

    async def test_channel_argument_overrides_default(self, monkeypatch):
        sent = {}

        class StubClient:
            async def chat_postMessage(self, **payload):  # noqa: N802 - Slack SDK name
                sent.update(payload)
                return {"ts": "1", "channel": "C1"}

        notifier = SlackNotifier(token="xoxb-test", channel="#default")
        monkeypatch.setattr(type(notifier), "client", property(lambda self: StubClient()))

        await notifier.send("hi", channel="#override")

        assert sent["channel"] == "#override"

    async def test_api_failure_is_reported_not_raised(self, monkeypatch):
        class FailingClient:
            async def chat_postMessage(self, **payload):  # noqa: N802 - Slack SDK name
                raise RuntimeError("channel_not_found")

        notifier = SlackNotifier(token="xoxb-test")
        monkeypatch.setattr(type(notifier), "client", property(lambda self: FailingClient()))

        result = await notifier.send("hi")

        assert result.success is False
        assert "channel_not_found" in result.error

    async def test_recommendation_reaches_slack(self, monkeypatch):
        sent = {}

        class StubClient:
            async def chat_postMessage(self, **payload):  # noqa: N802 - Slack SDK name
                sent.update(payload)
                return {"ts": "1", "channel": "C1"}

        notifier = SlackNotifier(token="xoxb-test")
        monkeypatch.setattr(type(notifier), "client", property(lambda self: StubClient()))

        result = await notifier.send_recommendation(
            [_stock("020710", 9.26, years=5)],
            total_analyzed=2763,
            criteria=["dividend_yield: 배당수익률 >= 4.0%"],
            market="KR",
        )

        assert result.success is True
        assert "020710" in sent["text"]
        assert "종목 추천 (KR)" in sent["text"]


class TestSlackFileUpload:
    """Uploading the Excel report."""

    async def test_channel_name_is_rejected_with_guidance(self, tmp_path):
        """files.completeUploadExternal takes an ID, unlike chat.postMessage."""
        report = tmp_path / "r.xlsx"
        report.write_bytes(b"x")

        result = await SlackNotifier(token="xoxb-test").send_file(
            str(report), channel="#stock"
        )

        assert result.success is False
        assert "channel ID" in result.error

    async def test_missing_file_reports_clearly(self):
        result = await SlackNotifier(token="xoxb-test").send_file(
            "/nonexistent/report.xlsx", channel="C123456789"
        )

        assert result.success is False
        assert "File not found" in result.error

    async def test_missing_token_reports_clearly(self, clean_env, tmp_path):
        report = tmp_path / "r.xlsx"
        report.write_bytes(b"x")

        result = await SlackNotifier().send_file(str(report), channel="C123456789")

        assert result.success is False
        assert "token" in result.error.lower()

    async def test_successful_upload(self, monkeypatch, tmp_path):
        report = tmp_path / "recommendations_KR.xlsx"
        report.write_bytes(b"xlsx-bytes")
        sent = {}

        class StubClient:
            async def files_upload_v2(self, **payload):  # noqa: N802 - Slack SDK name
                sent.update(payload)
                return {"file": {"id": "F123"}}

        notifier = SlackNotifier(token="xoxb-test")
        monkeypatch.setattr(type(notifier), "client", property(lambda self: StubClient()))

        result = await notifier.send_file(
            str(report), comment="상세", channel="C077W41NXHP", title="report"
        )

        assert result.success is True
        assert sent["channel"] == "C077W41NXHP"
        assert sent["filename"] == "recommendations_KR.xlsx"
        assert sent["initial_comment"] == "상세"

    async def test_upload_failure_is_reported_not_raised(self, monkeypatch, tmp_path):
        report = tmp_path / "r.xlsx"
        report.write_bytes(b"x")

        class FailingClient:
            async def files_upload_v2(self, **payload):  # noqa: N802 - Slack SDK name
                raise RuntimeError("invalid_arguments")

        notifier = SlackNotifier(token="xoxb-test")
        monkeypatch.setattr(type(notifier), "client", property(lambda self: FailingClient()))

        result = await notifier.send_file(str(report), channel="C123456789")

        assert result.success is False
        assert "invalid_arguments" in result.error

    async def test_send_returns_channel_id_for_the_upload(self, monkeypatch):
        """The upload's channel ID comes from the message that precedes it."""
        class StubClient:
            async def chat_postMessage(self, **payload):  # noqa: N802 - Slack SDK name
                return {"ts": "1", "channel": "C077W41NXHP"}

        notifier = SlackNotifier(token="xoxb-test")
        monkeypatch.setattr(type(notifier), "client", property(lambda self: StubClient()))

        result = await notifier.send("hi")

        assert result.metadata["channel_id"] == "C077W41NXHP"


class TestSlackBlocks:
    """Plain text is converted into Slack block kit sections."""

    def test_dividers_become_divider_blocks(self):
        blocks = SlackNotifier(token="t")._text_to_blocks("title\n" + "─" * 10 + "\nbody")

        assert {"type": "divider"} in blocks

    def test_text_becomes_sections(self):
        blocks = SlackNotifier(token="t")._text_to_blocks("line one\nline two")

        assert len(blocks) == 1
        assert blocks[0]["type"] == "section"
        assert "line one\nline two" == blocks[0]["text"]["text"]

    def test_empty_text_yields_no_blocks(self):
        assert SlackNotifier(token="t")._text_to_blocks("") == []


class TestSendSafe:
    """send_safe converts exceptions into results."""

    async def test_exception_becomes_error_result(self):
        class Exploding(NotificationService):
            async def send(self, message: str, **kwargs) -> NotificationResult:
                raise RuntimeError("boom")

        result = await Exploding().send_safe("hi")

        assert result.success is False
        assert "boom" in result.error
