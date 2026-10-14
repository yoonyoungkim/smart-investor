"""US Dividend data collector using yfinance."""

from datetime import datetime
from typing import Any

import pandas as pd
import yfinance as yf

from ..base import DataCollector, CollectionResult


class USDividendCollector(DataCollector[pd.DataFrame]):
    """Collects dividend payment data for US stocks."""

    def __init__(self) -> None:
        """Initialize dividend collector."""
        super().__init__()

    def collect(
        self,
        symbol: str,
        start_date: datetime | str | None = None,
        end_date: datetime | str | None = None,
    ) -> CollectionResult[pd.DataFrame]:
        """Collect dividend data for a symbol.

        Args:
            symbol: Stock symbol
            start_date: Start date for dividend data
            end_date: End date for dividend data

        Returns:
            CollectionResult with DataFrame containing dividend data
        """
        try:
            ticker = yf.Ticker(symbol)
            dividends = ticker.dividends

            if dividends.empty:
                return CollectionResult.fail(f"No dividend data found for {symbol}")

            df = pd.DataFrame(dividends).reset_index()
            df.columns = ["Date", "Cash Amount"]

            if start_date:
                df = df[df["Date"] >= pd.to_datetime(start_date)]
            if end_date:
                df = df[df["Date"] <= pd.to_datetime(end_date)]

            if df.empty:
                return CollectionResult.fail(
                    f"No dividend data in specified date range for {symbol}"
                )

            df["ticker"] = symbol
            df["Ex-Dividend Date"] = df["Date"]
            df["Pay Date"] = df["Date"]
            df = df[["ticker", "Ex-Dividend Date", "Cash Amount", "Pay Date"]]

            return CollectionResult.ok(
                df,
                symbol=symbol,
                rows=len(df),
                total_dividends=df["Cash Amount"].sum(),
                start=df["Ex-Dividend Date"].min(),
                end=df["Ex-Dividend Date"].max(),
            )

        except Exception as e:
            return CollectionResult.fail(f"Failed to collect dividends for {symbol}: {e}")

    def collect_batch(
        self,
        symbols: list[str],
        start_date: datetime | str | None = None,
        end_date: datetime | str | None = None,
    ) -> dict[str, CollectionResult[pd.DataFrame]]:
        """Collect dividend data for multiple symbols.

        Args:
            symbols: List of stock symbols
            start_date: Start date for dividend data
            end_date: End date for dividend data

        Returns:
            Dictionary mapping symbols to their CollectionResults
        """
        results = {}

        for symbol in symbols:
            self.logger.info(f"Collecting dividends for {symbol}")
            result = self.collect_safe(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
            )
            results[symbol] = result

        return results

    def get_dividend_summary(self, symbol: str, years: int = 5) -> dict[str, Any]:
        """Get dividend summary statistics.

        Args:
            symbol: Stock symbol
            years: Number of years to analyze

        Returns:
            Dictionary with dividend statistics
        """
        start_date = datetime.now().replace(year=datetime.now().year - years)
        result = self.collect(symbol=symbol, start_date=start_date)

        if not result.success or result.data is None:
            return {
                "symbol": symbol,
                "has_dividends": False,
                "error": result.error,
            }

        df = result.data
        yearly_dividends = df.groupby(df["Ex-Dividend Date"].dt.year)["Cash Amount"].sum()

        return {
            "symbol": symbol,
            "has_dividends": True,
            "years_of_data": len(yearly_dividends),
            "total_payments": len(df),
            "avg_annual_dividend": yearly_dividends.mean(),
            "latest_dividend": df.iloc[-1]["Cash Amount"],
            "total_dividend": df["Cash Amount"].sum(),
            "yearly_dividends": yearly_dividends.to_dict(),
        }
