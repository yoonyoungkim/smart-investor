#!/usr/bin/env python3
"""Create all database tables from the ORM models.

Run once against a fresh database before collecting data:

    python scripts/init_db.py

Uses the DB settings from ``.env``. Existing tables are left untouched
(``create_all`` only creates what is missing).
"""

import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from smart_investor.db.config import DatabaseConfig
from smart_investor.db.connection import DatabaseConnection
from smart_investor.db.models import Base

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    config = DatabaseConfig.from_env()
    logger.info(f"Connecting to database: {config}")

    with DatabaseConnection(config) as db:
        if not db.test_connection():
            logger.error("❌ Database connection failed. Check .env and that MySQL is running.")
            return 1

        Base.metadata.create_all(db.engine)

    tables = ", ".join(sorted(Base.metadata.tables.keys()))
    logger.info(f"✅ Tables ready: {tables}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
