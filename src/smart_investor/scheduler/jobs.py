"""Scheduled job definitions for stock scanning."""

import asyncio
import logging
from datetime import datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from smart_investor.analysis.calculator import MetricsCalculator
from smart_investor.db.config import DatabaseConfig
from smart_investor.db.connection import DatabaseConnection
from smart_investor.filters.config import FilterConfig
from smart_investor.filters.engine import StockFilterEngine
from smart_investor.models.stock import FinancialMetrics, Market, FilterResult
from smart_investor.notifications.base import NotificationService

logger = logging.getLogger(__name__)


class StockScannerJob:
    """Job for scanning stocks and sending notifications."""

    def __init__(
        self,
        db_config: DatabaseConfig,
        notifiers: list[NotificationService] | None = None,
        markets: list[Market] | None = None,
        filter_config: FilterConfig | None = None,
    ) -> None:
        """Initialize scanner job.

        Args:
            db_config: Database configuration
            notifiers: List of notification services
            markets: Markets to scan (default: both US and KR)
            filter_config: Criteria selection and thresholds for the scan
                (default: every registered criterion at its default threshold)
        """
        self.db_config = db_config
        self.notifiers = notifiers or []
        self.markets = markets or [Market.US, Market.KR]
        self.filter_engine = StockFilterEngine(config=filter_config)
        self._previous_passed: set[str] = set()

    async def run_daily_scan(self) -> dict[str, Any]:
        """Run daily stock screening scan.

        Returns:
            Dictionary with scan results
        """
        logger.info("Starting daily stock scan...")
        start_time = datetime.now()

        results = {
            "timestamp": start_time,
            "markets": [m.value for m in self.markets],
            "total_analyzed": 0,
            "passed_stocks": [],
            "new_qualifiers": [],
            "disqualified": [],
            "errors": [],
        }

        try:
            with DatabaseConnection(self.db_config) as db:
                session = db.get_session()
                calculator = MetricsCalculator(session)

                # Get all tickers to scan
                all_tickers = self._get_tickers_to_scan(session)
                results["total_analyzed"] = len(all_tickers)

                logger.info(f"Scanning {len(all_tickers)} stocks...")

                # Calculate metrics and filter
                all_metrics = []
                for ticker_info in all_tickers:
                    try:
                        ticker = ticker_info["symbol"]
                        market = ticker_info.get("market", Market.US)

                        # Calculate metrics
                        metrics_dict = calculator.calculate_all_metrics(ticker)

                        # Convert to FinancialMetrics
                        metrics = FinancialMetrics(
                            ticker=ticker,
                            market=market,
                            dividend_yield=self._to_float(metrics_dict.get("dividend_yield")),
                            debt_ratio=self._to_float(metrics_dict.get("debt_ratio")),
                            quick_ratio=self._to_float(metrics_dict.get("quick_ratio")),
                            interest_coverage_ratio=self._to_float(
                                metrics_dict.get("interest_coverage_ratio")
                            ),
                            has_interest_expense=metrics_dict.get("has_interest_expense"),
                            dividend_increasing=metrics_dict.get("dividend_increasing", False),
                            revenue_increasing=metrics_dict.get("revenue_increasing", False),
                            operating_income_increasing=metrics_dict.get(
                                "operating_income_increasing", False
                            ),
                            years_of_dividend=metrics_dict.get("years_of_dividend", 0),
                        )
                        all_metrics.append(metrics)

                    except Exception as e:
                        logger.warning(f"Failed to process {ticker}: {e}")
                        results["errors"].append({"ticker": ticker, "error": str(e)})

                # Run filtering
                passed, failed = self.filter_engine.filter_stocks(all_metrics)
                results["passed_stocks"] = passed

                # Detect changes
                current_passed = {r.ticker for r in passed}
                new_qualifiers = current_passed - self._previous_passed
                disqualified = self._previous_passed - current_passed

                results["new_qualifiers"] = [r for r in passed if r.ticker in new_qualifiers]
                results["disqualified"] = list(disqualified)

                # Update tracking
                self._previous_passed = current_passed

                session.close()

        except Exception as e:
            logger.error(f"Daily scan failed: {e}", exc_info=True)
            results["errors"].append({"error": str(e)})

        # Send notifications
        await self._send_notifications(results)

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"Daily scan completed in {elapsed:.1f}s. Passed: {len(results['passed_stocks'])}")

        return results

    async def run_weekly_report(self) -> dict[str, Any]:
        """Run weekly summary report.

        Returns:
            Dictionary with report data
        """
        logger.info("Generating weekly report...")

        # For now, just run a daily scan and send as weekly report
        results = await self.run_daily_scan()

        # Send weekly report through all notifiers
        for notifier in self.notifiers:
            try:
                await notifier.send_daily_report(
                    passed_stocks=results["passed_stocks"],
                    total_analyzed=results["total_analyzed"],
                )
            except Exception as e:
                logger.error(f"Failed to send weekly report via {notifier}: {e}")

        return results

    def _get_tickers_to_scan(self, session: Session) -> list[dict]:
        """Get list of tickers to scan from database.

        Args:
            session: Database session

        Returns:
            List of ticker info dictionaries
        """
        from smart_investor.db.models import GlobalTicker

        tickers = []

        # Query tickers from database
        query = session.query(GlobalTicker)

        for record in query.all():
            market = Market.KR if record.country == "South Korea" else Market.US
            if market in self.markets:
                tickers.append({
                    "symbol": record.Symbol,
                    "market": market,
                    "name": record.Name,
                })

        return tickers

    async def _send_notifications(self, results: dict[str, Any]) -> None:
        """Send notifications based on scan results.

        Args:
            results: Scan results dictionary
        """
        if not self.notifiers:
            return

        # Notify about new qualifiers
        if results["new_qualifiers"]:
            for notifier in self.notifiers:
                try:
                    await notifier.send_stock_alert(
                        stocks=results["new_qualifiers"],
                        alert_type="new_qualified",
                    )
                except Exception as e:
                    logger.error(f"Failed to send alert via {notifier}: {e}")

        # Notify about disqualified stocks
        if results["disqualified"]:
            for notifier in self.notifiers:
                try:
                    # Create simple FilterResult for disqualified tickers
                    disqualified_results = [
                        FilterResult(ticker=t, passed=False, failed_criteria=["No longer meets criteria"])
                        for t in results["disqualified"]
                    ]
                    await notifier.send_stock_alert(
                        stocks=disqualified_results,
                        alert_type="disqualified",
                    )
                except Exception as e:
                    logger.error(f"Failed to send alert via {notifier}: {e}")

    @staticmethod
    def _to_float(value: Any) -> float | None:
        """Convert value to float or None."""
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


class ScannerScheduler:
    """Scheduler for stock scanning jobs."""

    def __init__(
        self,
        scanner_job: StockScannerJob,
        timezone: str = "Asia/Seoul",
    ) -> None:
        """Initialize scheduler.

        Args:
            scanner_job: Scanner job to schedule
            timezone: Timezone for job scheduling
        """
        self.scanner_job = scanner_job
        self.timezone = timezone
        self.scheduler = AsyncIOScheduler(timezone=timezone)
        self._is_running = False

    def add_daily_scan(
        self,
        hour: int = 18,
        minute: int = 0,
        day_of_week: str = "mon-fri",
    ) -> None:
        """Add daily scan job.

        Args:
            hour: Hour to run (24-hour format)
            minute: Minute to run
            day_of_week: Days to run (e.g., 'mon-fri', '0-4', '*')
        """
        self.scheduler.add_job(
            self.scanner_job.run_daily_scan,
            trigger=CronTrigger(
                hour=hour,
                minute=minute,
                day_of_week=day_of_week,
            ),
            id="daily_scan",
            name="Daily Stock Scan",
            replace_existing=True,
        )
        logger.info(f"Added daily scan job at {hour:02d}:{minute:02d} ({day_of_week})")

    def add_weekly_report(
        self,
        day_of_week: str = "sun",
        hour: int = 10,
        minute: int = 0,
    ) -> None:
        """Add weekly report job.

        Args:
            day_of_week: Day to run (e.g., 'sun', '6', 'sat,sun')
            hour: Hour to run
            minute: Minute to run
        """
        self.scheduler.add_job(
            self.scanner_job.run_weekly_report,
            trigger=CronTrigger(
                day_of_week=day_of_week,
                hour=hour,
                minute=minute,
            ),
            id="weekly_report",
            name="Weekly Report",
            replace_existing=True,
        )
        logger.info(f"Added weekly report job on {day_of_week} at {hour:02d}:{minute:02d}")

    def start(self) -> None:
        """Start the scheduler."""
        if not self._is_running:
            self.scheduler.start()
            self._is_running = True
            logger.info("Scheduler started")

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._is_running:
            self.scheduler.shutdown()
            self._is_running = False
            logger.info("Scheduler stopped")

    async def run_now(self, job_type: str = "daily") -> dict[str, Any]:
        """Run a job immediately.

        Args:
            job_type: Type of job to run ('daily' or 'weekly')

        Returns:
            Job results
        """
        if job_type == "daily":
            return await self.scanner_job.run_daily_scan()
        elif job_type == "weekly":
            return await self.scanner_job.run_weekly_report()
        else:
            raise ValueError(f"Unknown job type: {job_type}")

    def get_jobs(self) -> list[dict[str, Any]]:
        """Get list of scheduled jobs.

        Returns:
            List of job information dictionaries
        """
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name if hasattr(job, 'name') else job.id,
                "next_run": getattr(job, 'next_run_time', None),
                "trigger": str(job.trigger),
            })
        return jobs
