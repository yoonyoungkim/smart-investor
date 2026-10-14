#!/usr/bin/env python3
"""Add natural-key unique constraints to existing tables.

``init_db.py`` only creates missing tables (``create_all``), so a database built
before the constraints existed keeps relying on application-level duplicate
checks. That check reads a row before writing it, which two concurrent batches
can both pass - the database has to enforce the key itself.

The script is idempotent: constraints already present are skipped, so it is safe
to re-run. It refuses to add a constraint while duplicates exist, since MySQL
would fail the ALTER anyway; use ``--dedupe`` to collapse duplicate groups first
(keeping the lowest ``id`` of each group).

Usage:
    python scripts/migrate_add_unique_constraints.py --dry-run
    python scripts/migrate_add_unique_constraints.py
    python scripts/migrate_add_unique_constraints.py --dedupe
"""

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_investor.db.config import DatabaseConfig
from smart_investor.db.connection import DatabaseConnection

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Migration:
    """One table's natural key and the indexes it makes redundant.

    Attributes:
        table: Table name.
        constraint: Name of the unique constraint to create.
        columns: Natural key columns, in index order.
        redundant_indexes: Existing indexes fully covered by the new unique
            index as a leading prefix, which are dropped to avoid duplicate
            index maintenance on every write.
    """

    table: str
    constraint: str
    columns: tuple[str, ...]
    redundant_indexes: tuple[str, ...] = ()

    @property
    def quoted_columns(self) -> str:
        """Backtick-quoted column list for use in SQL."""
        return ", ".join(f"`{c}`" for c in self.columns)


MIGRATIONS = (
    Migration("global_ticker", "uq_ticker_symbol", ("Symbol",), ("idx_symbol",)),
    Migration("global_etf", "uq_etf_symbol", ("Symbol",), ("idx_symbol",)),
    Migration("global_price", "uq_price_ticker_date", ("ticker", "Date"), ("idx_ticker",)),
    Migration(
        "global_fs",
        "uq_fs_ticker_date_account_freq",
        ("ticker", "date", "account", "freq"),
        ("idx_ticker",),
    ),
    Migration(
        "global_dividends",
        "uq_dividend_ticker_exdate",
        ("ticker", "Ex-Dividend Date"),
        ("idx_ticker",),
    ),
    Migration(
        "global_value",
        "uq_value_ticker_date_ind",
        ("ticker", "date", "indicator"),
        ("idx_ticker",),
    ),
)


def main() -> int:
    """Run the migration."""
    parser = argparse.ArgumentParser(description="Add natural-key unique constraints")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without altering anything",
    )
    parser.add_argument(
        "--dedupe",
        action="store_true",
        help="Delete duplicate rows (keeping the lowest id) before adding constraints",
    )
    args = parser.parse_args()

    try:
        config = DatabaseConfig.from_env()
    except ValueError as e:
        logger.error(f"❌ Configuration error: {e}")
        return 1

    with DatabaseConnection(config) as db:
        session = db.get_session()
        try:
            return _migrate(session, dry_run=args.dry_run, dedupe=args.dedupe)
        finally:
            session.close()


def _migrate(session: Session, dry_run: bool, dedupe: bool) -> int:
    """Apply every migration.

    Args:
        session: SQLAlchemy session.
        dry_run: Report only, change nothing.
        dedupe: Collapse duplicate groups before adding constraints.

    Returns:
        Process exit code.
    """
    blocked = 0

    for migration in MIGRATIONS:
        if not _table_exists(session, migration.table):
            logger.info(f"⏭  {migration.table}: table missing, skipped")
            continue

        if _index_exists(session, migration.table, migration.constraint):
            logger.info(f"✅ {migration.table}: {migration.constraint} already present")
            _drop_redundant(session, migration, dry_run)
            continue

        duplicates = _count_duplicates(session, migration)
        if duplicates:
            if not dedupe:
                logger.error(
                    f"❌ {migration.table}: {duplicates:,} duplicate row(s) on "
                    f"({', '.join(migration.columns)}) - re-run with --dedupe"
                )
                blocked += 1
                continue

            if dry_run:
                logger.info(f"🔍 {migration.table}: would delete {duplicates:,} duplicate row(s)")
            else:
                removed = _delete_duplicates(session, migration)
                logger.info(f"🧹 {migration.table}: deleted {removed:,} duplicate row(s)")

        if dry_run:
            logger.info(
                f"🔍 {migration.table}: would add {migration.constraint} "
                f"({', '.join(migration.columns)})"
            )
        else:
            session.execute(text(
                f"ALTER TABLE {migration.table} "
                f"ADD CONSTRAINT {migration.constraint} UNIQUE ({migration.quoted_columns})"
            ))
            session.commit()
            logger.info(f"✅ {migration.table}: added {migration.constraint}")

        _drop_redundant(session, migration, dry_run)

    if blocked:
        logger.error(f"\n{blocked} table(s) blocked by duplicates. Re-run with --dedupe.")
        return 1

    logger.info("\n✅ Migration complete" if not dry_run else "\n🔍 Dry run complete")
    return 0


def _drop_redundant(session: Session, migration: Migration, dry_run: bool) -> None:
    """Drop indexes the new unique index already covers.

    Args:
        session: SQLAlchemy session.
        migration: Migration being applied.
        dry_run: Report only, change nothing.
    """
    for index_name in migration.redundant_indexes:
        if not _index_exists(session, migration.table, index_name):
            continue

        if dry_run:
            logger.info(f"🔍 {migration.table}: would drop redundant index {index_name}")
            continue

        session.execute(text(f"ALTER TABLE {migration.table} DROP INDEX {index_name}"))
        session.commit()
        logger.info(f"🧹 {migration.table}: dropped redundant index {index_name}")


def _table_exists(session: Session, table: str) -> bool:
    """Whether a table exists in the current schema.

    Args:
        session: SQLAlchemy session.
        table: Table name.

    Returns:
        True when the table exists.
    """
    return bool(session.execute(text(
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
    ), {"t": table}).scalar())


def _index_exists(session: Session, table: str, index: str) -> bool:
    """Whether an index exists on a table.

    Args:
        session: SQLAlchemy session.
        table: Table name.
        index: Index or constraint name.

    Returns:
        True when the index exists.
    """
    return bool(session.execute(text(
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND INDEX_NAME = :i"
    ), {"t": table, "i": index}).scalar())


def _count_duplicates(session: Session, migration: Migration) -> int:
    """Count rows that would violate the natural key.

    Args:
        session: SQLAlchemy session.
        migration: Migration being applied.

    Returns:
        Number of surplus rows (group size minus one, summed).
    """
    return int(session.execute(text(
        f"SELECT COALESCE(SUM(c - 1), 0) FROM ("
        f"  SELECT COUNT(*) c FROM {migration.table} "
        f"  GROUP BY {migration.quoted_columns} HAVING c > 1"
        f") d"
    )).scalar() or 0)


def _delete_duplicates(session: Session, migration: Migration) -> int:
    """Delete duplicate rows, keeping the lowest id in each group.

    Args:
        session: SQLAlchemy session.
        migration: Migration being applied.

    Returns:
        Number of rows deleted.
    """
    join_condition = " AND ".join(f"a.`{c}` = b.`{c}`" for c in migration.columns)
    result = session.execute(text(
        f"DELETE a FROM {migration.table} a "
        f"JOIN {migration.table} b ON {join_condition} AND a.id > b.id"
    ))
    session.commit()
    return result.rowcount


if __name__ == "__main__":
    sys.exit(main())
