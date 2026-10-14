"""Data persistence layer for collectors.

Writes go through ``INSERT ... ON DUPLICATE KEY UPDATE`` against the natural-key
unique constraints in :mod:`smart_investor.db.models`, so re-running a
collection updates existing rows instead of duplicating them - and concurrent
batches cannot race past an application-level existence check.
"""

import logging
import math
from datetime import date

import pandas as pd
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from smart_investor.db.models import (
    GlobalDividend,
    GlobalETF,
    GlobalFinancialStatement,
    GlobalPrice,
    GlobalTicker,
    GlobalValue,
)

logger = logging.getLogger(__name__)


class DataPersistence:
    """Handles saving collected data to database."""

    def __init__(self, session: Session) -> None:
        """Initialize persistence layer.

        Args:
            session: SQLAlchemy session
        """
        self.session = session

    @staticmethod
    def _clean_value(val):
        """Convert NaN/inf values to None for MySQL compatibility.

        Also handles negative zeros and very small/large numbers.

        Args:
            val: Value to clean

        Returns:
            None if val is NaN/inf, otherwise cleaned value
        """
        if val is None:
            return None

        if isinstance(val, float):
            # Handle NaN and infinity
            if math.isnan(val) or math.isinf(val):
                return None

            # Convert negative zero to positive zero
            if val == 0.0:
                return 0.0

            # Handle very small numbers (near zero)
            if abs(val) < 1e-10:
                return 0.0

        return val

    @staticmethod
    def _clean_string(val):
        """Clean string values.

        Args:
            val: Value to clean

        Returns:
            Cleaned string or None
        """
        if val is None:
            return None

        if isinstance(val, str):
            # Strip whitespace
            val = val.strip()

            # Convert empty strings to None
            if not val or val.lower() in ("n/a", "na", "null", "none", "-"):
                return None

        return val

    def _bulk_upsert(
        self,
        model,
        rows: list[dict],
        key_columns: tuple[str, ...],
        update_columns: tuple[str, ...],
        chunk_size: int = 1000,
    ) -> int:
        """Insert rows, updating any that collide with the natural key.

        Uses MySQL's ``INSERT ... ON DUPLICATE KEY UPDATE`` against the unique
        constraints declared in :mod:`smart_investor.db.models`. The previous
        read-then-write approach cost a round trip per row and could not stop
        two concurrent batches from both inserting the same key.

        Args:
            model: ORM model whose table receives the rows.
            rows: Column-keyed dicts. Keys must match the table's column keys.
            key_columns: Natural key, used to collapse duplicates inside a batch.
            update_columns: Columns overwritten when a row already exists.
            chunk_size: Rows per statement, to keep packets a sane size.

        Returns:
            Number of distinct rows written.
        """
        if not rows:
            return 0

        # Collapse repeats inside this batch so a single statement never carries
        # the same key twice; the last occurrence wins, matching the old
        # row-by-row behaviour.
        deduped = {tuple(row.get(k) for k in key_columns): row for row in rows}
        values = list(deduped.values())

        table = model.__table__

        for start in range(0, len(values), chunk_size):
            chunk = values[start:start + chunk_size]
            stmt = mysql_insert(table).values(chunk)
            stmt = stmt.on_duplicate_key_update(
                {column: stmt.inserted[column] for column in update_columns}
            )
            self.session.execute(stmt)

        self.session.commit()
        return len(values)

    @staticmethod
    def _to_date(val):
        """Normalise a pandas/py datetime to a plain date.

        Args:
            val: Timestamp, datetime, date, or None.

        Returns:
            A ``date``, or None when the input is missing or not a date.
        """
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return None

        if hasattr(val, "tz_localize") and getattr(val, "tzinfo", None) is not None:
            val = val.tz_localize(None)

        if hasattr(val, "date") and not isinstance(val, date):
            return val.date()

        return val

    def save_tickers(self, df: pd.DataFrame) -> int:
        """Save ticker data to database, updating rows that already exist.

        Duplicates are prevented by the ``uq_ticker_symbol`` constraint.

        Args:
            df: DataFrame with ticker information

        Returns:
            Number of records inserted/updated
        """
        rows = []

        for record in df.to_dict("records"):
            rows.append({
                "Symbol": record["Symbol"],
                "Name": self._clean_string(record.get("Name")) or record["Symbol"],
                "Exchange": self._clean_string(record.get("Exchange")) or "Unknown",
                "Sector": self._clean_string(record.get("Sector")) or "Unknown",
                "Market Cap": self._clean_value(record.get("Market Cap")),
                "country": self._clean_string(record.get("country")) or "United States",
                "date": self._to_date(record["date"]),
            })

        return self._bulk_upsert(
            GlobalTicker,
            rows,
            key_columns=("Symbol",),
            update_columns=("Name", "Exchange", "Sector", "Market Cap", "country", "date"),
        )

    def save_etfs(self, df: pd.DataFrame) -> int:
        """Save ETF ticker data to global_etf, updating rows that already exist.

        Duplicates are prevented by the ``uq_etf_symbol`` constraint.

        Args:
            df: DataFrame with ETF information. Recognized columns:
                Symbol, Name, Exchange, category, nav, Market Cap, country, date.

        Returns:
            Number of records inserted/updated
        """
        rows = []

        for record in df.to_dict("records"):
            market_cap = self._clean_value(record.get("Market Cap"))
            if market_cap is not None:
                market_cap = int(market_cap)

            rows.append({
                "Symbol": record["Symbol"],
                "Name": self._clean_string(record.get("Name")) or record["Symbol"],
                "Exchange": self._clean_string(record.get("Exchange")) or "Unknown",
                "category": self._clean_string(record.get("category")),
                "nav": self._clean_value(record.get("nav")),
                "Market Cap": market_cap,
                "country": self._clean_string(record.get("country")) or "Unknown",
                "date": self._to_date(record["date"]),
            })

        return self._bulk_upsert(
            GlobalETF,
            rows,
            key_columns=("Symbol",),
            update_columns=(
                "Name", "Exchange", "category", "nav", "Market Cap", "country", "date",
            ),
        )

    def save_prices(self, df: pd.DataFrame) -> int:
        """Save price data to database, updating rows that already exist.

        Duplicates are prevented by the ``uq_price_ticker_date`` constraint.

        Args:
            df: DataFrame with price data

        Returns:
            Number of records inserted/updated
        """
        rows = []

        for record in df.to_dict("records"):
            # Adjusted close arrives under different names depending on source.
            adj_close = record.get("AdjClose") or record.get("Adj Close") or record.get("Close")

            high = self._clean_value(record["High"])
            low = self._clean_value(record["Low"])
            open_price = self._clean_value(record["Open"])
            close = self._clean_value(record["Close"])

            # Skip records with no valid price data
            if all(val is None for val in [high, low, open_price, close]):
                continue

            rows.append({
                "ticker": record["ticker"],
                "Date": self._to_date(record["Date"]),
                "High": high,
                "Low": low,
                "Open": open_price,
                "Close": close,
                "Volume": self._clean_value(record["Volume"]) or 0,
                "Adj Close": self._clean_value(adj_close),
            })

        return self._bulk_upsert(
            GlobalPrice,
            rows,
            key_columns=("ticker", "Date"),
            update_columns=("High", "Low", "Open", "Close", "Volume", "Adj Close"),
        )

    def save_financials(self, df: pd.DataFrame) -> int:
        """Save financial statement data, updating rows that already exist.

        Duplicates are prevented by the ``uq_fs_ticker_date_account_freq``
        constraint.

        Args:
            df: DataFrame with financial data

        Returns:
            Number of records inserted/updated
        """
        rows = []

        for record in df.to_dict("records"):
            value = self._clean_value(record.get("value"))
            if value is None:
                continue

            rows.append({
                "ticker": record["ticker"],
                "date": self._to_date(record["date"]),
                "account": record["account"],
                "value": value,
                "freq": record["freq"],
            })

        return self._bulk_upsert(
            GlobalFinancialStatement,
            rows,
            key_columns=("ticker", "date", "account", "freq"),
            update_columns=("value",),
        )

    def save_dividends(self, df: pd.DataFrame) -> int:
        """Save dividend data to database, updating rows that already exist.

        Duplicates are prevented by the ``uq_dividend_ticker_exdate`` constraint.

        Args:
            df: DataFrame with dividend data

        Returns:
            Number of records inserted/updated
        """
        rows = []

        for record in df.to_dict("records"):
            cash_amount = self._clean_value(
                record.get("Cash Amount", record.get("cash_amount"))
            )

            if cash_amount is None:
                continue

            # DECIMAL(10, 4) tops out at 999999.9999; a value outside that range
            # is bad data rather than a dividend.
            if cash_amount < 0 or cash_amount > 999999.9999:
                logger.warning(
                    f"Skipping invalid dividend for {record['ticker']}: "
                    f"cash_amount={cash_amount} (out of range)"
                )
                continue

            ex_div_date = self._to_date(
                record.get("Ex-Dividend Date", record.get("ex_dividend_date"))
            )
            if ex_div_date is None:
                continue

            rows.append({
                "ticker": record["ticker"],
                "Ex-Dividend Date": ex_div_date,
                "Cash Amount": cash_amount,
                "Pay Date": self._to_date(record.get("Pay Date", record.get("pay_date"))),
                "Record Date": self._to_date(
                    record.get("Record Date", record.get("record_date"))
                ),
            })

        return self._bulk_upsert(
            GlobalDividend,
            rows,
            key_columns=("ticker", "Ex-Dividend Date"),
            update_columns=("Cash Amount", "Pay Date", "Record Date"),
        )

    def save_values(self, df: pd.DataFrame) -> int:
        """Save calculated or disclosed indicators to global_value.

        Duplicates are prevented by the ``uq_value_ticker_date_ind`` constraint.

        Args:
            df: DataFrame with ticker, date, indicator and value columns.

        Returns:
            Number of records inserted/updated
        """
        rows = []

        for record in df.to_dict("records"):
            value = self._clean_value(record.get("value"))
            if value is None:
                continue

            rows.append({
                "ticker": record["ticker"],
                "date": self._to_date(record["date"]),
                "indicator": record["indicator"],
                "value": value,
            })

        return self._bulk_upsert(
            GlobalValue,
            rows,
            key_columns=("ticker", "date", "indicator"),
            update_columns=("value",),
        )

    def ticker_exists(self, symbol: str) -> bool:
        """Check if ticker exists in database.

        Args:
            symbol: Stock symbol

        Returns:
            True if ticker exists
        """
        return (
            self.session.query(GlobalTicker)
            .filter(GlobalTicker.Symbol == symbol)
            .first()
            is not None
        )

    def get_latest_price_date(self, symbol: str) -> pd.Timestamp | None:
        """Get the latest price date for a symbol.

        Args:
            symbol: Stock symbol

        Returns:
            Latest price date or None if no prices exist
        """
        result = (
            self.session.query(GlobalPrice.Date)
            .filter(GlobalPrice.ticker == symbol)
            .order_by(GlobalPrice.Date.desc())
            .first()
        )

        if result:
            return pd.Timestamp(result[0])
        return None

    def get_latest_financial_date(self, symbol: str, frequency: str = "y") -> pd.Timestamp | None:
        """Get the latest financial statement date for a symbol.

        Args:
            symbol: Stock symbol
            frequency: 'y' for yearly or 'q' for quarterly

        Returns:
            Latest financial statement date or None if no data exists
        """
        result = (
            self.session.query(GlobalFinancialStatement.date)
            .filter(GlobalFinancialStatement.ticker == symbol)
            .filter(GlobalFinancialStatement.freq == frequency)
            .order_by(GlobalFinancialStatement.date.desc())
            .first()
        )

        if result:
            return pd.Timestamp(result[0])
        return None

    def get_latest_dividend_date(self, symbol: str) -> pd.Timestamp | None:
        """Get the latest dividend ex-dividend date for a symbol.

        Args:
            symbol: Stock symbol

        Returns:
            Latest ex-dividend date or None if no dividends exist
        """
        result = (
            self.session.query(GlobalDividend.ex_dividend_date)
            .filter(GlobalDividend.ticker == symbol)
            .order_by(GlobalDividend.ex_dividend_date.desc())
            .first()
        )

        if result:
            return pd.Timestamp(result[0])
        return None
