#!/usr/bin/env python3
"""Calculate financial metrics from collected data and store them (step 3).

Reads the raw data collected into ``global_price``, ``global_fs`` and
``global_dividends``, computes the indicators the recommendation criteria need,
and writes them to ``global_value``.

Usage:
    python scripts/calculate_metrics.py [--market US|KR|ALL] [--limit N]

Examples:
    python scripts/calculate_metrics.py
    python scripts/calculate_metrics.py --market KR
    python scripts/calculate_metrics.py --market US --limit 500
    python scripts/calculate_metrics.py --only-with-data
"""

import argparse
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import distinct

from smart_investor.analysis.calculator import MetricsCalculator
from smart_investor.db.config import DatabaseConfig
from smart_investor.db.connection import DatabaseConnection
from smart_investor.db.models import (
    GlobalDividend,
    GlobalFinancialStatement,
    GlobalTicker,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

COUNTRY_BY_MARKET = {
    "US": "United States",
    "KR": "South Korea",
}


def main() -> int:
    """Calculate and store metrics."""
    parser = argparse.ArgumentParser(
        description="Calculate financial metrics into global_value"
    )
    parser.add_argument(
        "symbols",
        nargs="*",
        default=None,
        help="Specific symbols to process (default: all tickers in the market)",
    )
    parser.add_argument(
        "--market",
        choices=["US", "KR", "ALL"],
        default="ALL",
        help="Market to process (default: ALL)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of tickers to process (0 = no limit)",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Skip first N tickers (for batch processing)",
    )
    parser.add_argument(
        "--only-with-data",
        action="store_true",
        help="Process only tickers that already have financial or dividend rows",
    )
    args = parser.parse_args()

    try:
        config = DatabaseConfig.from_env()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return 1

    with DatabaseConnection(config) as db:
        session = db.get_session()
        calculator = MetricsCalculator(session)

        symbols = _resolve_symbols(session, args)
        if not symbols:
            logger.warning("No tickers matched - nothing to calculate")
            return 0

        logger.info(f"Calculating metrics for {len(symbols)} tickers...")

        stored = 0
        empty = 0
        errors = 0

        for index, symbol in enumerate(symbols, start=1):
            try:
                metrics = calculator.calculate_all_metrics(symbol)
                calculator.save_metrics(symbol, metrics)

                if _has_any_indicator(metrics):
                    stored += 1
                else:
                    empty += 1

            except Exception as e:
                errors += 1
                session.rollback()
                logger.warning(f"{symbol}: metric calculation failed: {e}")

            if index % 200 == 0:
                logger.info(f"  {index}/{len(symbols)} processed")

        session.close()

    logger.info("=" * 60)
    logger.info(f"Tickers processed:      {len(symbols)}")
    logger.info(f"Indicators stored:      {stored}")
    logger.info(f"No indicator computed:  {empty}")
    logger.info(f"Errors:                 {errors}")
    logger.info("=" * 60)

    if empty and not stored:
        logger.warning(
            "No indicators could be computed. Collect prices, dividends and "
            "financials first (scripts/collect_us_stocks.py, collect_kr_stocks.py)."
        )

    return 0


def _resolve_symbols(session, args) -> list[str]:
    """Determine which tickers to process.

    Args:
        session: SQLAlchemy session.
        args: Parsed CLI arguments.

    Returns:
        List of ticker symbols.
    """
    if args.symbols:
        return list(args.symbols)

    query = session.query(GlobalTicker.Symbol)

    country = COUNTRY_BY_MARKET.get(args.market)
    if country:
        query = query.filter(GlobalTicker.country == country)

    if args.only_with_data:
        with_financials = session.query(distinct(GlobalFinancialStatement.ticker))
        with_dividends = session.query(distinct(GlobalDividend.ticker))
        known = {row[0] for row in with_financials} | {row[0] for row in with_dividends}
        symbols = [row[0] for row in query if row[0] in known]
    else:
        symbols = [row[0] for row in query]

    if args.offset:
        symbols = symbols[args.offset:]
    if args.limit:
        symbols = symbols[: args.limit]

    return symbols


def _has_any_indicator(metrics: dict) -> bool:
    """Whether any numeric indicator was produced for a ticker.

    Args:
        metrics: Result of ``calculate_all_metrics``.

    Returns:
        True when at least one indicator is not None.
    """
    return any(
        metrics.get(key) is not None
        for key in ("dividend_yield", "debt_ratio", "quick_ratio", "interest_coverage_ratio")
    )


if __name__ == "__main__":
    sys.exit(main())
