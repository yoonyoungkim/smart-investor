#!/usr/bin/env python3
"""Start the stock scanner scheduler.

Usage:
    python scripts/start_scheduler.py [--daily-hour HOUR] [--weekly-day DAY]

Examples:
    python scripts/start_scheduler.py
    python scripts/start_scheduler.py --daily-hour 17
    python scripts/start_scheduler.py --weekly-day sat
"""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from smart_investor.db.config import DatabaseConfig
from smart_investor.filters.config import FilterConfig
from smart_investor.scheduler.jobs import StockScannerJob, ScannerScheduler
from smart_investor.notifications.slack import SlackNotifier
from smart_investor.notifications.telegram import TelegramNotifier
from smart_investor.notifications.email import EmailNotifier

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main() -> int:
    """Start the scheduler."""
    parser = argparse.ArgumentParser(description="Start stock scanner scheduler")
    parser.add_argument(
        "--daily-hour",
        type=int,
        default=18,
        help="Hour for daily scan (24-hour format, default: 18)"
    )
    parser.add_argument(
        "--weekly-day",
        default="sun",
        help="Day for weekly report (default: sun)"
    )
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Run a scan immediately and exit"
    )
    parser.add_argument(
        "--filter-config",
        help="JSON file selecting which criteria the scan applies "
             "(default: all registered criteria)"
    )
    args = parser.parse_args()

    # Load the criteria selection before touching the database so a bad config
    # fails immediately rather than after a full scan.
    filter_config = None
    if args.filter_config:
        try:
            filter_config = FilterConfig.load(args.filter_config)
            filter_config.build()
        except (ValueError, TypeError, KeyError, FileNotFoundError) as e:
            logger.error(f"Filter configuration error: {e}")
            return 1

    # Load configuration
    try:
        db_config = DatabaseConfig.from_env()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return 1

    # Initialize notifiers (only those with configuration)
    notifiers = []

    try:
        slack = SlackNotifier()
        if slack.token:
            notifiers.append(slack)
            logger.info("Slack notifier enabled")
    except Exception as e:
        logger.debug(f"Slack notifier not configured: {e}")

    try:
        telegram = TelegramNotifier()
        if telegram.token:
            notifiers.append(telegram)
            logger.info("Telegram notifier enabled")
    except Exception as e:
        logger.debug(f"Telegram notifier not configured: {e}")

    try:
        email = EmailNotifier()
        if email.username:
            notifiers.append(email)
            logger.info("Email notifier enabled")
    except Exception as e:
        logger.debug(f"Email notifier not configured: {e}")

    if not notifiers:
        logger.warning("No notifiers configured - running without notifications")

    # Initialize scanner job
    scanner_job = StockScannerJob(
        db_config=db_config,
        notifiers=notifiers,
        filter_config=filter_config,
    )

    # Run immediately if requested
    if args.run_now:
        logger.info("Running scan immediately...")
        result = asyncio.run(scanner_job.run_daily_scan())
        logger.info(f"Scan complete: {len(result['passed_stocks'])} stocks passed")
        return 0

    # Initialize scheduler
    scheduler = ScannerScheduler(scanner_job)

    # Add jobs
    scheduler.add_daily_scan(hour=args.daily_hour, minute=0)
    scheduler.add_weekly_report(day_of_week=args.weekly_day, hour=10)

    # Print job schedule
    logger.info("Scheduled jobs:")
    for job in scheduler.get_jobs():
        logger.info(f"  {job['name']}: next run at {job['next_run']}")

    # Setup signal handlers for graceful shutdown
    def signal_handler(sig, frame):
        logger.info("Received shutdown signal, stopping scheduler...")
        scheduler.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start scheduler with event loop
    logger.info("Starting scheduler...")

    async def run_scheduler():
        scheduler.start()
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            scheduler.stop()

    try:
        asyncio.run(run_scheduler())
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")
        scheduler.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
