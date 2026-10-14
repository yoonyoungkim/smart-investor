"""Tests for duplicate handling in the persistence layer.

These need a reachable MySQL database because the upsert uses MySQL's
``INSERT ... ON DUPLICATE KEY UPDATE`` against the natural-key constraints. The
whole module skips when no database is configured, so the unit suite still runs
on a bare checkout.

Rows are written under reserved test tickers and removed afterwards, so the
tests can run against a working database without disturbing collected data.
"""

from datetime import date

import pandas as pd
import pytest
from sqlalchemy import text

from smart_investor.db.config import DatabaseConfig
from smart_investor.db.connection import DatabaseConnection
from smart_investor.db.persistence import DataPersistence

# Reserved prefix; no real ticker starts with an underscore.
TEST_PREFIX = "__PYTEST"
PRICE_TICKER = f"{TEST_PREFIX}_P__"
FS_TICKER = f"{TEST_PREFIX}_F__"
DIV_TICKER = f"{TEST_PREFIX}_D__"
SYMBOL = f"{TEST_PREFIX}_S__"

CLEANUP = (
    ("global_price", "ticker", (PRICE_TICKER,)),
    ("global_fs", "ticker", (FS_TICKER,)),
    ("global_dividends", "ticker", (DIV_TICKER,)),
    ("global_ticker", "Symbol", (SYMBOL,)),
    ("global_etf", "Symbol", (SYMBOL,)),
)


@pytest.fixture(scope="module")
def connection():
    """Open a database connection, skipping the module when unavailable."""
    try:
        config = DatabaseConfig.from_env()
    except ValueError as exc:
        pytest.skip(f"database not configured: {exc}")

    try:
        with DatabaseConnection(config) as db:
            if not db.test_connection():
                pytest.skip("database not reachable")
            yield db
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"database not reachable: {exc}")


@pytest.fixture
def persistence(connection):
    """Provide a persistence layer and remove test rows afterwards."""
    session = connection.get_session()
    _cleanup(session)
    try:
        yield DataPersistence(session)
    finally:
        _cleanup(session)
        session.close()


def _cleanup(session):
    """Delete every row written under the reserved test identifiers."""
    for table, column, values in CLEANUP:
        session.execute(
            text(f"DELETE FROM {table} WHERE `{column}` IN :values"),
            {"values": values},
        )
    session.commit()


def _price_frame(close: float, days: int = 3) -> pd.DataFrame:
    """Build a price frame for the reserved price ticker."""
    return pd.DataFrame([
        {
            "ticker": PRICE_TICKER,
            "Date": date(2026, 1, day),
            "Open": close, "High": close + 1, "Low": close - 1,
            "Close": close, "Volume": 1000, "AdjClose": close,
        }
        for day in range(1, days + 1)
    ])


def _count(session, table: str, column: str, value: str) -> int:
    """Count rows for one identifier."""
    return session.execute(
        text(f"SELECT COUNT(*) FROM {table} WHERE `{column}` = :v"), {"v": value}
    ).scalar()


class TestPriceUpsert:
    """Re-saving prices updates rather than duplicates."""

    def test_insert(self, persistence):
        assert persistence.save_prices(_price_frame(10.0)) == 3
        assert _count(persistence.session, "global_price", "ticker", PRICE_TICKER) == 3

    def test_repeat_save_does_not_duplicate(self, persistence):
        persistence.save_prices(_price_frame(10.0))
        persistence.save_prices(_price_frame(10.0))
        persistence.save_prices(_price_frame(10.0))

        assert _count(persistence.session, "global_price", "ticker", PRICE_TICKER) == 3

    def test_repeat_save_updates_values(self, persistence):
        persistence.save_prices(_price_frame(10.0))
        persistence.save_prices(_price_frame(99.0))

        closes = persistence.session.execute(
            text("SELECT DISTINCT Close FROM global_price WHERE ticker = :t"),
            {"t": PRICE_TICKER},
        ).scalars().all()
        assert [float(c) for c in closes] == [99.0]

    def test_duplicates_within_one_batch_collapse(self, persistence):
        doubled = pd.concat([_price_frame(10.0), _price_frame(20.0)], ignore_index=True)

        assert persistence.save_prices(doubled) == 3
        assert _count(persistence.session, "global_price", "ticker", PRICE_TICKER) == 3

    def test_rows_without_prices_are_skipped(self, persistence):
        df = _price_frame(10.0)
        df.loc[0, ["Open", "High", "Low", "Close"]] = float("nan")

        assert persistence.save_prices(df) == 2

    def test_empty_frame(self, persistence):
        assert persistence.save_prices(pd.DataFrame(columns=_price_frame(1.0).columns)) == 0


class TestFinancialUpsert:
    """Financials key on ticker, date, account and frequency."""

    def _frame(self, value: float) -> pd.DataFrame:
        return pd.DataFrame([
            {"ticker": FS_TICKER, "date": date(2025, 12, 31),
             "account": "Total Revenue", "value": value, "freq": "y"},
            {"ticker": FS_TICKER, "date": date(2025, 12, 31),
             "account": "Operating Income", "value": value / 10, "freq": "y"},
        ])

    def test_repeat_save_does_not_duplicate(self, persistence):
        persistence.save_financials(self._frame(1000.0))
        persistence.save_financials(self._frame(1000.0))

        assert _count(persistence.session, "global_fs", "ticker", FS_TICKER) == 2

    def test_repeat_save_updates_value(self, persistence):
        persistence.save_financials(self._frame(1000.0))
        persistence.save_financials(self._frame(2000.0))

        value = persistence.session.execute(
            text("SELECT value FROM global_fs WHERE ticker = :t AND account = 'Total Revenue'"),
            {"t": FS_TICKER},
        ).scalar()
        assert float(value) == 2000.0

    def test_same_account_different_frequency_coexists(self, persistence):
        yearly = self._frame(1000.0)
        quarterly = self._frame(250.0)
        quarterly["freq"] = "q"

        persistence.save_financials(yearly)
        persistence.save_financials(quarterly)

        assert _count(persistence.session, "global_fs", "ticker", FS_TICKER) == 4

    def test_null_values_skipped(self, persistence):
        df = self._frame(1000.0)
        df.loc[0, "value"] = float("nan")

        assert persistence.save_financials(df) == 1


class TestDividendUpsert:
    """Dividends key on ticker and ex-dividend date."""

    def _frame(self, amount: float) -> pd.DataFrame:
        return pd.DataFrame([
            {"ticker": DIV_TICKER, "Ex-Dividend Date": date(2025, 12, 31),
             "Cash Amount": amount, "Pay Date": None},
        ])

    def test_repeat_save_does_not_duplicate(self, persistence):
        persistence.save_dividends(self._frame(1444.0))
        persistence.save_dividends(self._frame(1444.0))

        assert _count(persistence.session, "global_dividends", "ticker", DIV_TICKER) == 1

    def test_repeat_save_updates_amount(self, persistence):
        persistence.save_dividends(self._frame(1444.0))
        persistence.save_dividends(self._frame(1668.0))

        amount = persistence.session.execute(
            text("SELECT `Cash Amount` FROM global_dividends WHERE ticker = :t"),
            {"t": DIV_TICKER},
        ).scalar()
        assert float(amount) == 1668.0

    def test_out_of_range_amount_skipped(self, persistence):
        """DECIMAL(10,4) cannot hold this, and it is not a real dividend."""
        assert persistence.save_dividends(self._frame(10_000_000.0)) == 0

    def test_negative_amount_skipped(self, persistence):
        assert persistence.save_dividends(self._frame(-5.0)) == 0

    def test_accepts_snake_case_columns(self, persistence):
        """Collectors emit display names; older callers used snake_case."""
        df = pd.DataFrame([{
            "ticker": DIV_TICKER, "ex_dividend_date": date(2025, 12, 31),
            "cash_amount": 100.0, "pay_date": None,
        }])
        assert persistence.save_dividends(df) == 1


class TestTickerUpsert:
    """Tickers and ETFs key on Symbol."""

    def _frame(self, name: str) -> pd.DataFrame:
        return pd.DataFrame([{
            "Symbol": SYMBOL, "Name": name, "Exchange": "TEST",
            "Sector": "Test", "Market Cap": 1000, "country": "South Korea",
            "date": date(2026, 1, 1),
        }])

    def test_repeat_save_does_not_duplicate(self, persistence):
        persistence.save_tickers(self._frame("First"))
        persistence.save_tickers(self._frame("Second"))

        assert _count(persistence.session, "global_ticker", "Symbol", SYMBOL) == 1

    def test_repeat_save_updates_name(self, persistence):
        persistence.save_tickers(self._frame("First"))
        persistence.save_tickers(self._frame("Second"))

        name = persistence.session.execute(
            text("SELECT Name FROM global_ticker WHERE Symbol = :s"), {"s": SYMBOL}
        ).scalar()
        assert name == "Second"

    def test_etf_repeat_save_does_not_duplicate(self, persistence):
        df = self._frame("ETF").drop(columns=["Sector"])
        df["category"] = "Equity"
        df["nav"] = 1000.0

        persistence.save_etfs(df)
        persistence.save_etfs(df)

        assert _count(persistence.session, "global_etf", "Symbol", SYMBOL) == 1


class TestNaturalKeyConstraints:
    """The database, not the application, enforces the natural keys."""

    EXPECTED = {
        "global_ticker": "uq_ticker_symbol",
        "global_etf": "uq_etf_symbol",
        "global_price": "uq_price_ticker_date",
        "global_fs": "uq_fs_ticker_date_account_freq",
        "global_dividends": "uq_dividend_ticker_exdate",
        "global_value": "uq_value_ticker_date_ind",
    }

    def test_constraints_exist(self, persistence):
        """Fails until scripts/migrate_add_unique_constraints.py has been run."""
        present = set(persistence.session.execute(text(
            "SELECT CONCAT(TABLE_NAME, ':', INDEX_NAME) "
            "FROM INFORMATION_SCHEMA.STATISTICS "
            "WHERE TABLE_SCHEMA = DATABASE() AND NON_UNIQUE = 0"
        )).scalars().all())

        missing = [
            f"{table}:{name}"
            for table, name in self.EXPECTED.items()
            if f"{table}:{name}" not in present
        ]
        assert not missing, f"missing unique constraints: {missing}"

    def test_no_duplicates_in_live_data(self, persistence):
        """Guards against duplicates that predate the constraints."""
        keys = {
            "global_ticker": "`Symbol`",
            "global_etf": "`Symbol`",
            "global_price": "ticker, `Date`",
            "global_fs": "ticker, `date`, account, freq",
            "global_dividends": "ticker, `Ex-Dividend Date`",
            "global_value": "ticker, `date`, indicator",
        }
        for table, key in keys.items():
            extra = persistence.session.execute(text(
                f"SELECT COALESCE(SUM(c - 1), 0) FROM "
                f"(SELECT COUNT(*) c FROM {table} GROUP BY {key} HAVING c > 1) d"
            )).scalar()
            assert int(extra or 0) == 0, f"{table} has {extra} duplicate row(s)"
