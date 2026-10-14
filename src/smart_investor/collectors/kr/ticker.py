"""Korean ticker information collector using FinanceDataReader.

pykrx's listing endpoints (``get_market_ticker_list``, ``get_market_cap_by_ticker``)
now require KRX account credentials and return empty results without them, so
listings are read from FinanceDataReader instead. FDR returns the whole market in
a single request, which also avoids the per-ticker round trips the previous
implementation made.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

try:
    import FinanceDataReader as fdr
except ImportError:  # pragma: no cover - exercised only without the dependency
    fdr = None

from ..base import CollectionResult, DataCollector

# FDR listing column names vary slightly by market; these are the candidates
# checked in order when reading a field.
_NAME_COLUMNS = ("Name", "종목명")
_SYMBOL_COLUMNS = ("Symbol", "Code", "종목코드")
_SECTOR_COLUMNS = ("Sector", "Industry", "업종")
_MARKET_CAP_COLUMNS = ("Marcap", "MarketCap", "시가총액")


class KRTickerCollector(DataCollector[pd.DataFrame]):
    """Collects basic ticker information for Korean stocks (KOSPI/KOSDAQ)."""

    MARKETS = ["KOSPI", "KOSDAQ"]

    def __init__(self) -> None:
        """Initialize Korean ticker collector."""
        super().__init__()
        if fdr is None:
            self.logger.warning(
                "FinanceDataReader is not installed - Korean ticker collection "
                "is unavailable"
            )

    def collect(
        self,
        symbols: list[str] | None = None,
        market: str | None = None,
    ) -> CollectionResult[pd.DataFrame]:
        """Collect ticker information for Korean stocks.

        Args:
            symbols: Stock codes to collect. When None, collects the whole market.
            market: ``KOSPI``, ``KOSDAQ``, or None for both.

        Returns:
            CollectionResult with a DataFrame of ticker information.
        """
        if fdr is None:
            return CollectionResult.fail("FinanceDataReader is not installed")

        try:
            markets = [market] if market else self.MARKETS
            frames = []

            for mkt in markets:
                self.logger.info(f"Fetching {mkt} tickers...")
                listing = self._fetch_market_listing(mkt)
                if listing is not None and not listing.empty:
                    frames.append(listing)
                    self.logger.info(f"  Found {len(listing)} {mkt} stocks")

            if not frames:
                return CollectionResult.fail("No ticker data collected")

            df = pd.concat(frames, ignore_index=True)

            if symbols is not None:
                wanted = {s.zfill(6) for s in symbols}
                df = df[df["Symbol"].isin(wanted)]
                missing = wanted - set(df["Symbol"])
                for code in sorted(missing):
                    self.logger.warning(f"Ticker {code} not found in KOSPI/KOSDAQ listings")

            if df.empty:
                return CollectionResult.fail("No ticker data collected")

            df = df.drop_duplicates(subset=["Symbol"]).reset_index(drop=True)
            return CollectionResult.ok(df, count=len(df))

        except Exception as e:
            return CollectionResult.fail(f"Failed to collect Korean tickers: {e}")

    def _fetch_market_listing(self, market: str) -> pd.DataFrame | None:
        """Fetch one market's listing and normalise it to the storage schema.

        Args:
            market: ``KOSPI`` or ``KOSDAQ``.

        Returns:
            Normalised DataFrame, or None when the listing could not be read.
        """
        try:
            listing = fdr.StockListing(market)
        except Exception as e:
            self.logger.warning(f"Failed to fetch {market} listing: {e}")
            return None

        if listing is None or listing.empty:
            return None

        symbols = self._column(listing, _SYMBOL_COLUMNS)
        if symbols is None:
            self.logger.warning(f"{market} listing has no recognisable symbol column")
            return None

        today = date.today()
        names = self._column(listing, _NAME_COLUMNS)
        sectors = self._column(listing, _SECTOR_COLUMNS)
        market_caps = self._column(listing, _MARKET_CAP_COLUMNS)

        df = pd.DataFrame({
            "Symbol": symbols.astype(str).str.zfill(6),
            "Name": names if names is not None else "",
            "Exchange": market,
            "Sector": sectors if sectors is not None else "Unknown",
            "Market Cap": market_caps if market_caps is not None else None,
            "country": "South Korea",
            "date": today,
        })

        df["Name"] = df["Name"].fillna("").astype(str)
        df["Sector"] = df["Sector"].fillna("Unknown").astype(str)
        return df

    @staticmethod
    def _column(df: pd.DataFrame, candidates: tuple[str, ...]) -> pd.Series | None:
        """Return the first column present among ``candidates``.

        Args:
            df: Source DataFrame.
            candidates: Column names to try, in priority order.

        Returns:
            The matching Series, or None when no candidate is present.
        """
        for name in candidates:
            if name in df.columns:
                return df[name]
        return None

    def collect_batch(self, symbols: list[str]) -> CollectionResult[pd.DataFrame]:
        """Collect ticker information for specific stock codes.

        Args:
            symbols: List of 6-digit stock codes.

        Returns:
            CollectionResult with a DataFrame of ticker information.
        """
        return self.collect(symbols=symbols)

    def get_market(self, symbol: str) -> str:
        """Determine which market a ticker belongs to.

        Args:
            symbol: 6-digit stock code.

        Returns:
            ``KOSPI``, ``KOSDAQ``, or ``Unknown``.
        """
        result = self.collect(symbols=[symbol])
        if not result.success or result.data is None or result.data.empty:
            return "Unknown"
        return str(result.data.iloc[0]["Exchange"])

    def _get_ticker_market(self, symbol: str) -> str:
        """Backward-compatible alias for :meth:`get_market`.

        Args:
            symbol: 6-digit stock code.

        Returns:
            ``KOSPI``, ``KOSDAQ``, or ``Unknown``.
        """
        return self.get_market(symbol)

    def get_all_symbols(self, market: str | None = None) -> list[str]:
        """List every stock code in the requested market.

        Args:
            market: ``KOSPI``, ``KOSDAQ``, or None for both.

        Returns:
            List of 6-digit stock codes.
        """
        result = self.collect(market=market)
        if not result.success or result.data is None:
            return []
        return result.data["Symbol"].tolist()

    def _fetch_market_tickers(self, market: str) -> list[dict[str, Any]]:
        """Backward-compatible record-list form of :meth:`_fetch_market_listing`.

        Args:
            market: ``KOSPI`` or ``KOSDAQ``.

        Returns:
            List of ticker dictionaries.
        """
        listing = self._fetch_market_listing(market)
        if listing is None:
            return []
        return listing.to_dict("records")
