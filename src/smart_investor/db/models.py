"""SQLAlchemy ORM models for database tables.

Each table carries a unique constraint on its natural key. Duplicate prevention
used to live only in :mod:`smart_investor.db.persistence`, which read a row
before writing it - a check two concurrent batches can both pass. The database
now rejects the duplicate outright, which also lets the persistence layer use a
single ``INSERT ... ON DUPLICATE KEY UPDATE`` instead of a read per row.

Single-column indexes that a unique constraint already covers as a leading
prefix are omitted rather than declared twice.
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import BIGINT, CHAR, DATE, DECIMAL, INT, VARCHAR, Index, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


class GlobalTicker(Base):
    """Stock ticker information."""

    __tablename__ = "global_ticker"

    id: Mapped[int] = mapped_column(INT, primary_key=True, autoincrement=True)
    Name: Mapped[str] = mapped_column(VARCHAR(255))
    Symbol: Mapped[str] = mapped_column(VARCHAR(20))
    Exchange: Mapped[str] = mapped_column(VARCHAR(50))
    Sector: Mapped[str] = mapped_column(VARCHAR(100))
    market_cap: Mapped[Optional[int]] = mapped_column("Market Cap", BIGINT, nullable=True)
    country: Mapped[str] = mapped_column(VARCHAR(100))
    # Currency the financial statements are filed in. Foreign issuers listed as
    # US ADRs file in their home currency while trading in USD, so dividing a
    # USD market cap by a KRW net income produced PERs near 0.01. Valuation
    # metrics are skipped when this does not match the trading currency.
    financial_currency: Mapped[Optional[str]] = mapped_column(VARCHAR(10), nullable=True)
    date: Mapped[date] = mapped_column(DATE)

    __table_args__ = (
        UniqueConstraint("Symbol", name="uq_ticker_symbol"),
        Index("idx_date", "date"),
        Index("idx_country", "country"),
    )


class GlobalPrice(Base):
    """Historical price data."""

    __tablename__ = "global_price"

    id: Mapped[int] = mapped_column(INT, primary_key=True, autoincrement=True)
    Date: Mapped[date] = mapped_column(DATE)
    High: Mapped[Decimal] = mapped_column(DECIMAL(20, 4))
    Low: Mapped[Decimal] = mapped_column(DECIMAL(20, 4))
    Open: Mapped[Decimal] = mapped_column(DECIMAL(20, 4))
    Close: Mapped[Decimal] = mapped_column(DECIMAL(20, 4))
    Volume: Mapped[int] = mapped_column(BIGINT)
    adj_close: Mapped[Decimal] = mapped_column("Adj Close", DECIMAL(20, 4))
    ticker: Mapped[str] = mapped_column(VARCHAR(20))

    __table_args__ = (
        UniqueConstraint("ticker", "Date", name="uq_price_ticker_date"),
        Index("idx_date", "Date"),
    )


class GlobalFinancialStatement(Base):
    """Financial statement data."""

    __tablename__ = "global_fs"

    id: Mapped[int] = mapped_column(INT, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(VARCHAR(20))
    date: Mapped[date] = mapped_column(DATE)
    account: Mapped[str] = mapped_column(VARCHAR(100))
    value: Mapped[Decimal] = mapped_column(DECIMAL(30, 2))
    freq: Mapped[str] = mapped_column(CHAR(1))

    __table_args__ = (
        UniqueConstraint(
            "ticker", "date", "account", "freq", name="uq_fs_ticker_date_account_freq"
        ),
        Index("idx_date", "date"),
        Index("idx_account", "account"),
        Index("idx_freq", "freq"),
    )


class GlobalDividend(Base):
    """Dividend payment information."""

    __tablename__ = "global_dividends"

    id: Mapped[int] = mapped_column(INT, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(VARCHAR(20))
    ex_dividend_date: Mapped[date] = mapped_column("Ex-Dividend Date", DATE)
    cash_amount: Mapped[Decimal] = mapped_column("Cash Amount", DECIMAL(10, 4))
    record_date: Mapped[Optional[date]] = mapped_column("Record Date", DATE, nullable=True)
    pay_date: Mapped[Optional[date]] = mapped_column("Pay Date", DATE, nullable=True)

    __table_args__ = (
        UniqueConstraint("ticker", "Ex-Dividend Date", name="uq_dividend_ticker_exdate"),
        Index("idx_pay_date", "Pay Date"),
    )


class GlobalValue(Base):
    """Calculated financial metrics and indicators."""

    __tablename__ = "global_value"

    id: Mapped[int] = mapped_column(INT, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(VARCHAR(20))
    date: Mapped[date] = mapped_column(DATE)
    indicator: Mapped[str] = mapped_column(VARCHAR(20))
    value: Mapped[Decimal] = mapped_column(DECIMAL(20, 4))

    __table_args__ = (
        UniqueConstraint("ticker", "date", "indicator", name="uq_value_ticker_date_ind"),
        Index("idx_date", "date"),
        Index("idx_indicator", "indicator"),
    )


class GlobalETF(Base):
    """ETF ticker information (kept separate from stocks in global_ticker)."""

    __tablename__ = "global_etf"

    id: Mapped[int] = mapped_column(INT, primary_key=True, autoincrement=True)
    Name: Mapped[str] = mapped_column(VARCHAR(255))
    Symbol: Mapped[str] = mapped_column(VARCHAR(20))
    Exchange: Mapped[str] = mapped_column(VARCHAR(50))
    category: Mapped[Optional[str]] = mapped_column(VARCHAR(100), nullable=True)
    nav: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(20, 4), nullable=True)
    market_cap: Mapped[Optional[int]] = mapped_column("Market Cap", BIGINT, nullable=True)
    country: Mapped[str] = mapped_column(VARCHAR(100))
    date: Mapped[date] = mapped_column(DATE)

    __table_args__ = (
        UniqueConstraint("Symbol", name="uq_etf_symbol"),
        Index("idx_country", "country"),
    )
