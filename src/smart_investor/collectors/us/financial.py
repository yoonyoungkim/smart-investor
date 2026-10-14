"""US Financial statement data collector using yfinance."""

from typing import Literal

import pandas as pd
import yfinance as yf

from ..base import DataCollector, CollectionResult


FrequencyType = Literal["yearly", "quarterly"]


class USFinancialCollector(DataCollector[pd.DataFrame]):
    """Collects financial statement data for US stocks."""

    def __init__(self) -> None:
        """Initialize financial collector."""
        super().__init__()

    def collect(
        self,
        symbol: str,
        frequency: FrequencyType = "yearly",
        after_date: pd.Timestamp | None = None,
    ) -> CollectionResult[pd.DataFrame]:
        """Collect financial statements for a symbol.

        Args:
            symbol: Stock symbol
            frequency: 'yearly' or 'quarterly'
            after_date: Only collect data after this date (for incremental collection)

        Returns:
            CollectionResult with DataFrame containing financial data
        """
        try:
            ticker = yf.Ticker(symbol)

            # Collect different financial statements
            income_stmt = self._get_income_statement(ticker, frequency)
            balance_sheet = self._get_balance_sheet(ticker, frequency)
            cashflow = self._get_cashflow(ticker, frequency)

            # Combine all statements
            all_data = []

            for stmt_name, stmt_df in [
                ("income", income_stmt),
                ("balance", balance_sheet),
                ("cashflow", cashflow),
            ]:
                if stmt_df is not None and not stmt_df.empty:
                    data = self._transform_statement(stmt_df, symbol, frequency, after_date)
                    all_data.append(data)

            if not all_data:
                return CollectionResult.fail(f"No financial data found for {symbol}")

            df = pd.concat(all_data, ignore_index=True)

            return CollectionResult.ok(
                df,
                symbol=symbol,
                frequency=frequency,
                rows=len(df),
                accounts=df["account"].nunique(),
            )

        except Exception as e:
            return CollectionResult.fail(f"Failed to collect financials for {symbol}: {e}")

    def _get_income_statement(
        self,
        ticker: yf.Ticker,
        frequency: FrequencyType,
    ) -> pd.DataFrame | None:
        """Get income statement."""
        try:
            if frequency == "yearly":
                return ticker.financials
            else:
                return ticker.quarterly_financials
        except Exception as e:
            self.logger.warning(f"Failed to get income statement: {e}")
            return None

    def _get_balance_sheet(
        self,
        ticker: yf.Ticker,
        frequency: FrequencyType,
    ) -> pd.DataFrame | None:
        """Get balance sheet."""
        try:
            if frequency == "yearly":
                return ticker.balance_sheet
            else:
                return ticker.quarterly_balance_sheet
        except Exception as e:
            self.logger.warning(f"Failed to get balance sheet: {e}")
            return None

    def _get_cashflow(
        self,
        ticker: yf.Ticker,
        frequency: FrequencyType,
    ) -> pd.DataFrame | None:
        """Get cash flow statement."""
        try:
            if frequency == "yearly":
                return ticker.cashflow
            else:
                return ticker.quarterly_cashflow
        except Exception as e:
            self.logger.warning(f"Failed to get cash flow: {e}")
            return None

    def _transform_statement(
        self,
        df: pd.DataFrame,
        symbol: str,
        frequency: FrequencyType,
        after_date: pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        """Transform statement DataFrame to long format.

        Args:
            df: Statement DataFrame (accounts as rows, dates as columns)
            symbol: Stock symbol
            frequency: Frequency type
            after_date: Only include data after this date

        Returns:
            Transformed DataFrame in long format
        """
        df = df.reset_index()
        df.columns.name = None
        df = df.rename(columns={df.columns[0]: "account"})

        id_vars = ["account"]
        value_vars = [col for col in df.columns if col != "account"]

        if after_date is not None:
            value_vars = [col for col in value_vars if pd.Timestamp(col) > after_date]
            if not value_vars:
                return pd.DataFrame(columns=["ticker", "date", "account", "value", "freq"])

        df_long = df.melt(
            id_vars=id_vars,
            value_vars=value_vars,
            var_name="date",
            value_name="value",
        )

        df_long["ticker"] = symbol
        df_long["freq"] = "y" if frequency == "yearly" else "q"
        df_long = df_long[["ticker", "date", "account", "value", "freq"]]
        df_long = df_long.dropna(subset=["value"])

        return df_long

    def collect_batch(
        self,
        symbols: list[str],
        frequency: FrequencyType = "yearly",
    ) -> dict[str, CollectionResult[pd.DataFrame]]:
        """Collect financial data for multiple symbols.

        Args:
            symbols: List of stock symbols
            frequency: 'yearly' or 'quarterly'

        Returns:
            Dictionary mapping symbols to their CollectionResults
        """
        results = {}

        for symbol in symbols:
            self.logger.info(f"Collecting financials for {symbol}")
            result = self.collect_safe(symbol=symbol, frequency=frequency)
            results[symbol] = result

        return results
