"""Stock filtering engine."""

import logging
from typing import Sequence

from ..models.stock import FilterResult, FinancialMetrics
from .config import FilterConfig
from .criteria import FilterCriterion

logger = logging.getLogger(__name__)


class StockFilterEngine:
    """Engine to filter stocks based on investment criteria.

    Args:
        config: Selection of criteria and threshold overrides. Defaults to every
            registered criterion at its default threshold.
        filters: Explicit ``(label, criterion)`` pairs, bypassing the registry.
            Takes precedence over ``config`` when both are given.
    """

    def __init__(
        self,
        config: FilterConfig | None = None,
        filters: Sequence[tuple[str, FilterCriterion]] | None = None,
    ) -> None:
        """Initialize filter engine with the selected criteria."""
        if filters is not None:
            self.filters = list(filters)
        else:
            self.config = config or FilterConfig()
            self.filters = self.config.build()

    def filter_stock(self, metrics: FinancialMetrics) -> FilterResult:
        """Apply all filters to a stock.

        Args:
            metrics: Financial metrics for the stock

        Returns:
            FilterResult with pass/fail status and reasons
        """
        failed_criteria = []

        for criterion_name, filter_obj in self.filters:
            passed, reason = filter_obj.check(metrics)
            if not passed:
                failed_criteria.append(f"{criterion_name}: {reason}")

        return FilterResult(
            ticker=metrics.ticker,
            passed=len(failed_criteria) == 0,
            failed_criteria=failed_criteria,
            metrics=metrics,
            market=metrics.market,
        )

    def filter_stocks(
        self, stocks_metrics: Sequence[FinancialMetrics]
    ) -> tuple[list[FilterResult], list[FilterResult]]:
        """Filter multiple stocks with detailed logging.

        Args:
            stocks_metrics: Sequence of financial metrics for stocks

        Returns:
            Tuple of (passed_stocks, failed_stocks)
        """
        total_stocks = len(stocks_metrics)
        logger.info(f"Starting filter process for {total_stocks} stocks")
        logger.info(
            f"Active filters ({len(self.filters)}): "
            f"{', '.join(name for name, _ in self.filters) or 'none'}"
        )

        # Apply all filters
        results = [self.filter_stock(metrics) for metrics in stocks_metrics]

        passed = [r for r in results if r.passed]
        failed = [r for r in results if not r.passed]

        if not total_stocks:
            logger.info("No stocks to analyze")
            return passed, failed

        # Log summary statistics
        logger.info("=" * 80)
        logger.info("FILTER RESULTS SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Total stocks analyzed: {total_stocks}")
        logger.info(f"Passed all filters: {len(passed)} ({len(passed)/total_stocks*100:.1f}%)")
        logger.info(f"Failed filters: {len(failed)} ({len(failed)/total_stocks*100:.1f}%)")

        # Get filter-by-filter statistics
        if self.filters:
            logger.info("")
            logger.info("FILTER BREAKDOWN (Why stocks failed):")
            logger.info("-" * 80)

            filter_stats = self.get_filter_summary(results)

            ranked = sorted(filter_stats.items(), key=lambda x: x[1], reverse=True)
            for criterion_name, fail_count in ranked:
                if fail_count > 0:
                    fail_pct = fail_count / total_stocks * 100
                    logger.info(
                        f"  {criterion_name:30s}: {fail_count:4d} failed ({fail_pct:5.1f}%)"
                    )

        logger.info("=" * 80)

        return passed, failed

    def get_filter_summary(
        self, results: Sequence[FilterResult]
    ) -> dict[str, int]:
        """Get summary of why stocks failed filtering.

        Args:
            results: Sequence of filter results

        Returns:
            Dictionary mapping criterion name to count of failures
        """
        summary: dict[str, int] = {name: 0 for name, _ in self.filters}

        for result in results:
            if not result.passed:
                for failed in result.failed_criteria:
                    criterion_name = failed.split(":")[0]
                    if criterion_name in summary:
                        summary[criterion_name] += 1

        return summary
