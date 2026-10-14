"""US Stock price data collector using yfinance."""

import time
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf
from sqlalchemy.orm import Session

from ..base import DataCollector, CollectionResult


class USPriceCollector(DataCollector[pd.DataFrame]):
    """Collects historical price data for US stocks."""

    def __init__(self, default_period: str = "5y") -> None:
        """Initialize price collector.

        Args:
            default_period: Default period for historical data (e.g., '1y', '5y', 'max')
        """
        super().__init__()
        self.default_period = default_period

    def collect(
        self,
        symbol: str,
        start_date: datetime | str | None = None,
        end_date: datetime | str | None = None,
        period: str | None = None,
    ) -> CollectionResult[pd.DataFrame]:
        """Collect historical price data for a symbol.

        Args:
            symbol: Stock symbol
            start_date: Start date for historical data
            end_date: End date for historical data
            period: Period string (e.g., '1y', '5y') - used if start_date is None

        Returns:
            CollectionResult with DataFrame containing price data
        """
        try:
            ticker = yf.Ticker(symbol)

            if start_date is None and period is None:
                period = self.default_period

            if period:
                df = ticker.history(period=period)
            else:
                df = ticker.history(start=start_date, end=end_date)

            if df.empty:
                return CollectionResult.fail(f"No price data found for {symbol}")

            df = df.reset_index()
            df["ticker"] = symbol
            df.columns = df.columns.str.replace(" ", "")

            return CollectionResult.ok(
                df,
                symbol=symbol,
                rows=len(df),
                start=df["Date"].min(),
                end=df["Date"].max(),
            )

        except Exception as e:
            return CollectionResult.fail(f"Failed to collect prices for {symbol}: {e}")

    def collect_batch(
        self,
        symbols: list[str],
        start_date: datetime | str | None = None,
        end_date: datetime | str | None = None,
        period: str | None = None,
        session: Session | None = None,
        incremental: bool = True,
    ) -> dict[str, CollectionResult[pd.DataFrame]]:
        """Collect price data for multiple symbols.

        Args:
            symbols: List of stock symbols
            start_date: Start date for historical data
            end_date: End date for historical data
            period: Period string (e.g., '1y', '5y')
            session: Database session for incremental collection
            incremental: If True and session provided, collect only new data

        Returns:
            Dictionary mapping symbols to their CollectionResults
        """
        results = {}

        for symbol in symbols:
            effective_start_date = start_date

            if incremental and session is not None and start_date is None:
                from smart_investor.db.persistence import DataPersistence
                persistence = DataPersistence(session)
                last_date = persistence.get_latest_price_date(symbol)

                if last_date:
                    effective_start_date = last_date + timedelta(days=1)
                    self.logger.info(
                        f"Collecting prices for {symbol} from {effective_start_date.date()} (incremental)"
                    )
                else:
                    self.logger.info(f"Collecting prices for {symbol} (initial collection)")
            else:
                self.logger.info(f"Collecting prices for {symbol}")

            result = self.collect_safe(
                symbol=symbol,
                start_date=effective_start_date,
                end_date=end_date,
                period=period,
            )
            results[symbol] = result

        return results

    def collect_incremental(
        self,
        symbol: str,
        last_date: datetime | str,
    ) -> CollectionResult[pd.DataFrame]:
        """Collect price data incrementally from last known date.

        Args:
            symbol: Stock symbol
            last_date: Last date in existing data

        Returns:
            CollectionResult with DataFrame containing new price data
        """
        if isinstance(last_date, str):
            last_date = pd.to_datetime(last_date)

        start_date = last_date + timedelta(days=1)
        return self.collect(symbol=symbol, start_date=start_date)
