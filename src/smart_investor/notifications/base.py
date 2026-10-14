"""Base notification service."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from smart_investor.db.config import load_env
from smart_investor.models.stock import FilterResult


@dataclass
class NotificationResult:
    """Result of a notification operation."""

    success: bool
    channel: str
    message: str | None = None
    error: str | None = None
    sent_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, channel: str, message: str, **metadata: Any) -> "NotificationResult":
        """Create a successful result."""
        return cls(success=True, channel=channel, message=message, metadata=metadata)

    @classmethod
    def fail(cls, channel: str, error: str, **metadata: Any) -> "NotificationResult":
        """Create an error result.

        Named ``fail`` rather than ``error``: a classmethod sharing a dataclass
        field's name becomes that field's default, which left ``.error`` holding
        a bound method - and therefore truthy - on every successful result.
        """
        return cls(success=False, channel=channel, error=error, metadata=metadata)


class NotificationService(ABC):
    """Abstract base class for notification services."""

    def __init__(self) -> None:
        """Initialize notification service.

        Subclasses read their credentials from the environment in their own
        ``__init__``, and callers may build a notifier before touching the
        database, so ``.env`` has to be loaded here rather than relying on
        DatabaseConfig having run first.
        """
        load_env()
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    async def send(self, message: str, **kwargs: Any) -> NotificationResult:
        """Send a notification.

        Args:
            message: Message to send
            **kwargs: Additional parameters

        Returns:
            NotificationResult with status
        """
        ...

    async def send_stock_alert(
        self,
        stocks: list[FilterResult],
        alert_type: str = "new_qualified",
    ) -> NotificationResult:
        """Send stock qualification alert.

        Args:
            stocks: List of FilterResult for stocks
            alert_type: Type of alert ('new_qualified', 'disqualified', 'daily_report')

        Returns:
            NotificationResult with status
        """
        if not stocks:
            return NotificationResult.fail(
                channel=self.__class__.__name__,
                error="No stocks to notify about"
            )

        message = self._format_stock_alert(stocks, alert_type)
        return await self.send(message)

    def _format_stock_alert(
        self,
        stocks: list[FilterResult],
        alert_type: str,
    ) -> str:
        """Format stock alert message.

        Args:
            stocks: List of FilterResult
            alert_type: Type of alert

        Returns:
            Formatted message string
        """
        if alert_type == "new_qualified":
            title = "🎯 New Stocks Passing All Criteria"
        elif alert_type == "disqualified":
            title = "⚠️ Stocks No Longer Meeting Criteria"
        elif alert_type == "daily_report":
            title = "📊 Daily Stock Screening Report"
        else:
            title = "📢 Stock Alert"

        lines = [
            title,
            f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"Total: {len(stocks)} stocks",
            "",
            "─" * 40,
        ]

        for result in stocks[:20]:  # Limit to 20 stocks
            metrics = result.metrics
            if metrics:
                lines.append(
                    f"• {result.ticker} ({result.market.value})"
                )
                if metrics.dividend_yield:
                    lines.append(f"  Dividend Yield: {metrics.dividend_yield:.2f}%")
                if metrics.years_of_dividend:
                    lines.append(f"  Dividend Years: {metrics.years_of_dividend}")

                if not result.passed and result.failed_criteria:
                    lines.append(f"  ❌ Failed: {', '.join(result.failed_criteria[:2])}")
            else:
                lines.append(f"• {result.ticker}")

            lines.append("")

        if len(stocks) > 20:
            lines.append(f"... and {len(stocks) - 20} more stocks")

        return "\n".join(lines)

    async def send_daily_report(
        self,
        passed_stocks: list[FilterResult],
        total_analyzed: int,
    ) -> NotificationResult:
        """Send daily screening report.

        Args:
            passed_stocks: Stocks that passed all filters
            total_analyzed: Total number of stocks analyzed

        Returns:
            NotificationResult with status
        """
        pass_rate = (len(passed_stocks) / total_analyzed * 100) if total_analyzed > 0 else 0

        lines = [
            "📊 Daily Stock Screening Report",
            f"Date: {datetime.now().strftime('%Y-%m-%d')}",
            "",
            "─" * 40,
            f"Total Analyzed: {total_analyzed}",
            f"Passed All Filters: {len(passed_stocks)} ({pass_rate:.1f}%)",
            "",
        ]

        if passed_stocks:
            lines.append("Top Qualifying Stocks:")
            for result in passed_stocks[:10]:
                metrics = result.metrics
                if metrics and metrics.dividend_yield:
                    lines.append(
                        f"• {result.ticker}: {metrics.dividend_yield:.2f}% yield, "
                        f"{metrics.years_of_dividend}yr dividends"
                    )
                else:
                    lines.append(f"• {result.ticker}")

            if len(passed_stocks) > 10:
                lines.append(f"... and {len(passed_stocks) - 10} more")
        else:
            lines.append("No stocks passed all criteria today.")

        return await self.send("\n".join(lines))

    async def send_recommendation(
        self,
        stocks: list[FilterResult],
        total_analyzed: int,
        criteria: list[str] | None = None,
        market: str = "ALL",
        limit: int = 20,
    ) -> NotificationResult:
        """Send a recommendation report.

        Unlike :meth:`send_daily_report` this states which criteria produced the
        list. A recommendation is only meaningful alongside the thresholds it
        came from, since those are configurable per run.

        Args:
            stocks: Stocks passing every active criterion.
            total_analyzed: How many stocks were screened.
            criteria: Descriptions of the active criteria.
            market: Market label for the heading.
            limit: Maximum stocks listed before truncating.

        Returns:
            NotificationResult with status
        """
        pass_rate = (len(stocks) / total_analyzed * 100) if total_analyzed > 0 else 0.0

        lines = [
            f"🎯 종목 추천 ({market})",
            f"{datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
        ]

        if criteria:
            lines.append(f"적용 조건 ({len(criteria)}개)")
            lines.extend(f"  · {item}" for item in criteria)
            lines.append("")

        lines.append("─" * 40)
        lines.append(f"통과: {len(stocks)} / {total_analyzed:,} ({pass_rate:.1f}%)")
        lines.append("")

        if not stocks:
            lines.append("조건을 모두 통과한 종목이 없습니다.")
            return await self.send("\n".join(lines))

        # Highest yield first: among stocks that clear every criterion, yield is
        # what the criteria set is built around.
        ranked = sorted(
            stocks,
            key=lambda r: (r.metrics.dividend_yield if r.metrics else 0) or 0,
            reverse=True,
        )

        for result in ranked[:limit]:
            lines.append(self._format_recommendation_line(result))

        if len(ranked) > limit:
            lines.append(f"... 외 {len(ranked) - limit}종목")

        return await self.send("\n".join(lines))

    @staticmethod
    def _format_recommendation_line(result: FilterResult) -> str:
        """Format one recommended stock as a single line.

        Args:
            result: Filter result for a passing stock.

        Returns:
            Formatted line.
        """
        metrics = result.metrics
        if not metrics:
            return f"• {result.ticker}"

        parts = [f"• {result.ticker} ({result.market.value})"]

        if metrics.dividend_yield is not None:
            parts.append(f"배당 {metrics.dividend_yield:.2f}%")
        if metrics.years_of_dividend:
            parts.append(f"{metrics.years_of_dividend}년")
        if metrics.debt_ratio is not None:
            parts.append(f"부채 {metrics.debt_ratio:.1f}%")
        if metrics.quick_ratio is not None:
            parts.append(f"당좌 {metrics.quick_ratio:.1f}%")

        return "  ".join(parts)

    async def send_safe(self, message: str, **kwargs: Any) -> NotificationResult:
        """Safely send a notification with exception handling.

        Args:
            message: Message to send
            **kwargs: Additional parameters

        Returns:
            NotificationResult with status
        """
        try:
            return await self.send(message, **kwargs)
        except Exception as e:
            self.logger.error(f"Notification failed: {e}", exc_info=True)
            return NotificationResult.fail(
                channel=self.__class__.__name__,
                error=str(e)
            )
