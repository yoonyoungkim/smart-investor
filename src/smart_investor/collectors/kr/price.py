"""Korean Stock price data collector using pykrx."""

from datetime import datetime, timedelta, date

import pandas as pd
from pykrx import stock as krx
from sqlalchemy.orm import Session

from ..base import DataCollector, CollectionResult


class KRPriceCollector(DataCollector[pd.DataFrame]):
    """Collects historical price data for Korean stocks."""

    def __init__(self, default_years: int = 5) -> None:
        """Initialize Korean price collector.

        Args:
            default_years: Default number of years of historical data to collect
        """
        super().__init__()
        self.default_years = default_years

    def collect(
        self,
        symbol: str,
        start_date: datetime | str | None = None,
        end_date: datetime | str | None = None,
    ) -> CollectionResult[pd.DataFrame]:
        """Collect historical price data for a Korean stock.

        Args:
            symbol: Stock code (6-digit)
            start_date: Start date for historical data
            end_date: End date for historical data

        Returns:
            CollectionResult with DataFrame containing price data
        """
        try:
            # Set default date range
            if end_date is None:
                end_dt = date.today()
            elif isinstance(end_date, str):
                end_dt = pd.to_datetime(end_date).date()
            else:
                end_dt = end_date.date() if hasattr(end_date, 'date') else end_date

            if start_date is None:
                start_dt = end_dt - timedelta(days=365 * self.default_years)
            elif isinstance(start_date, str):
                start_dt = pd.to_datetime(start_date).date()
            else:
                start_dt = start_date.date() if hasattr(start_date, 'date') else start_date

            # Format dates for pykrx
            start_str = start_dt.strftime("%Y%m%d")
            end_str = end_dt.strftime("%Y%m%d")

            # Get OHLCV data from pykrx
            df = krx.get_market_ohlcv_by_date(start_str, end_str, symbol)

            if df.empty:
                return CollectionResult.fail(f"No price data found for {symbol}")

            # Transform to our standard format
            df = self._transform_price_data(df, symbol)

            return CollectionResult.ok(
                df,
                symbol=symbol,
                rows=len(df),
                start=df["Date"].min(),
                end=df["Date"].max(),
            )

        except Exception as e:
            return CollectionResult.fail(f"Failed to collect prices for {symbol}: {e}")

    def _transform_price_data(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """Transform pykrx OHLCV data to our standard format.

        Args:
            df: DataFrame from pykrx
            symbol: Stock code

        Returns:
            Transformed DataFrame
        """
        # pykrx returns DataFrame with Korean column names
        # 시가(Open), 고가(High), 저가(Low), 종가(Close), 거래량(Volume)
        df = df.reset_index()
        df = df.rename(columns={
            "날짜": "Date",
            "시가": "Open",
            "고가": "High",
            "저가": "Low",
            "종가": "Close",
            "거래량": "Volume",
        })

        # Add ticker and adjusted close (same as close for Korean stocks)
        df["ticker"] = symbol
        df["AdjClose"] = df["Close"]  # No adjustment needed for Korean stocks in KRX

        # Ensure Date is datetime
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"])

        # Select and reorder columns
        columns = ["Date", "Open", "High", "Low", "Close", "Volume", "AdjClose", "ticker"]
        available_cols = [c for c in columns if c in df.columns]
        df = df[available_cols]

        return df

    def collect_batch(
        self,
        symbols: list[str],
        start_date: datetime | str | None = None,
        end_date: datetime | str | None = None,
        session: Session | None = None,
        incremental: bool = True,
    ) -> dict[str, CollectionResult[pd.DataFrame]]:
        """Collect price data for multiple Korean stocks.

        Args:
            symbols: List of stock codes
            start_date: Start date for historical data
            end_date: End date for historical data
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
            symbol: Stock code
            last_date: Last date in existing data

        Returns:
            CollectionResult with DataFrame containing new price data
        """
        if isinstance(last_date, str):
            last_date = pd.to_datetime(last_date)

        start_date = last_date + timedelta(days=1)
        return self.collect(symbol=symbol, start_date=start_date)
