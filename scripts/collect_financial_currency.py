#!/usr/bin/env python3
"""Record the currency each company files its statements in.

US-listed foreign issuers (ADRs) trade in USD but file in their home currency.
Dividing a USD market cap by a KRW or CNY net income produced PER values near
0.01, which sorted to the top of the value screen. Storing the filing currency
lets :class:`~smart_investor.analysis.calculator.MetricsCalculator` skip
valuation ratios for those tickers rather than publish nonsense.

Korean tickers file in KRW and trade in KRW, so they are consistent by
construction and default to KRW without a lookup.

Usage:
    python scripts/collect_financial_currency.py [--market US|KR|ALL] [--limit N]
"""

import argparse
import logging
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import text  # noqa: E402

from smart_investor.db.config import DatabaseConfig  # noqa: E402
from smart_investor.db.connection import DatabaseConnection  # noqa: E402
from smart_investor.reporting import fetch_filing_currency  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

COUNTRY_BY_MARKET = {"US": "United States", "KR": "South Korea"}


def main() -> int:
    """Collect and store filing currencies."""
    parser = argparse.ArgumentParser(description="Store global_ticker.financial_currency")
    parser.add_argument("--market", choices=["US", "KR", "ALL"], default="US")
    parser.add_argument("--limit", type=int, default=0, help="0 = no limit")
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument(
        "--refresh", action="store_true", help="Re-fetch tickers that already have a value"
    )
    args = parser.parse_args()

    try:
        config = DatabaseConfig.from_env()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return 1

    with DatabaseConnection(config) as db:
        session = db.get_session()

        sql = (
            "SELECT Symbol, country FROM global_ticker WHERE Symbol IN "
            "(SELECT DISTINCT ticker FROM global_fs)"
        )
        params = {}
        country = COUNTRY_BY_MARKET.get(args.market)
        if country:
            sql += " AND country = :c"
            params["c"] = country
        if not args.refresh:
            sql += " AND financial_currency IS NULL"
        if args.limit:
            sql += f" LIMIT {int(args.limit)}"

        rows = session.execute(text(sql), params).all()
        logger.info(f"Looking up {len(rows)} tickers...")

        stored = 0
        for index, (symbol, ticker_country) in enumerate(rows, start=1):
            currency = fetch_filing_currency(symbol, ticker_country)
            if currency:
                session.execute(
                    text(
                        "UPDATE global_ticker SET financial_currency = :c WHERE Symbol = :s"
                    ),
                    {"c": currency, "s": symbol},
                )
                stored += 1

            if index % 100 == 0:
                session.commit()
                logger.info(f"  {index}/{len(rows)} processed")
            if args.delay:
                time.sleep(args.delay)

        session.commit()
        session.close()

    logger.info(f"Stored {stored}/{len(rows)} filing currencies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
