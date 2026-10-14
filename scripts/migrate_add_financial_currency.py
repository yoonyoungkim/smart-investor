#!/usr/bin/env python3
"""Add the financial_currency column to global_ticker.

Foreign issuers listed in the US as ADRs file their statements in their home
currency while trading in USD. Dividing a USD market cap by a KRW net income
produced PER values near 0.01, which then sorted to the top of the value
screen. Recording the filing currency lets those tickers be excluded from
valuation ratios instead.

Idempotent: re-running is a no-op once the column exists.

Usage:
    python scripts/migrate_add_financial_currency.py [--dry-run]
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import text

from smart_investor.db.config import DatabaseConfig
from smart_investor.db.connection import DatabaseConnection

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    """Add the column when it is missing."""
    parser = argparse.ArgumentParser(description="Add global_ticker.financial_currency")
    parser.add_argument("--dry-run", action="store_true", help="Report only")
    args = parser.parse_args()

    try:
        config = DatabaseConfig.from_env()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return 1

    with DatabaseConnection(config) as db:
        session = db.get_session()

        exists = session.execute(text(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'global_ticker' "
            "AND COLUMN_NAME = 'financial_currency'"
        )).scalar()

        if exists:
            logger.info("global_ticker.financial_currency already present")
            return 0

        if args.dry_run:
            logger.info("Would add global_ticker.financial_currency VARCHAR(10) NULL")
            return 0

        session.execute(text(
            "ALTER TABLE global_ticker ADD COLUMN financial_currency VARCHAR(10) NULL"
        ))
        session.commit()
        logger.info("Added global_ticker.financial_currency")

    return 0


if __name__ == "__main__":
    sys.exit(main())
