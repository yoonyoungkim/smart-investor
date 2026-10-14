"""US Ticker information collector using yfinance."""

import json
import time
import urllib.request
from datetime import date
from typing import Any

import pandas as pd
import yfinance as yf

from ..base import DataCollector, CollectionResult


class USTickerCollector(DataCollector[pd.DataFrame]):
    """Collects basic ticker information for US stocks."""

    # Major US exchanges and their Yahoo Finance codes
    SUPPORTED_EXCHANGES = [
        "NMS", "NYQ", "ASE", "PCX", "NCM", "NGM",
        "NASDAQGS", "NASDAQ", "NYSE", "AMEX"
    ]

    def __init__(self) -> None:
        """Initialize ticker collector."""
        super().__init__()

    def collect(self, symbols: list[str] | None = None, delay: float = 0.0) -> CollectionResult[pd.DataFrame]:
        """Collect ticker information.

        Args:
            symbols: List of stock symbols to collect. If None, collects from default sources.
            delay: Delay between API requests in seconds (default: 0)

        Returns:
            CollectionResult with DataFrame containing ticker information
        """
        if symbols is None:
            symbols = self._get_default_symbols()

        tickers_data = []

        for symbol in symbols:
            try:
                ticker_info = self._fetch_ticker_info(symbol)
                if ticker_info:
                    tickers_data.append(ticker_info)
            except Exception as e:
                self.logger.warning(f"Failed to fetch {symbol}: {e}")
                continue
            if delay > 0:
                time.sleep(delay)

        if not tickers_data:
            return CollectionResult.fail("No ticker data collected")

        df = pd.DataFrame(tickers_data)
        return CollectionResult.ok(df, count=len(df))

    def _fetch_ticker_info(self, symbol: str) -> dict[str, Any] | None:
        """Fetch information for a single ticker.

        Args:
            symbol: Stock symbol

        Returns:
            Dictionary with ticker information or None if failed
        """
        ticker = yf.Ticker(symbol)
        info = ticker.info

        # Filter for US stocks only
        country = info.get("country", "")
        if country != "United States":
            self.logger.debug(f"{symbol}: Not a US stock (country={country})")
            return None

        exchange = info.get("exchange", "")
        if not exchange or not any(ex in exchange.upper() for ex in self.SUPPORTED_EXCHANGES):
            self.logger.debug(f"{symbol}: Unsupported exchange ({exchange})")
            return None

        return {
            "Symbol": symbol,
            "Name": info.get("longName", symbol),
            "Exchange": exchange,
            "Sector": info.get("sector", "Unknown"),
            "Market Cap": info.get("marketCap", 0),
            "country": info.get("country", "United States"),
            "date": date.today(),
        }

    def _get_default_symbols(self) -> list[str]:
        """Get comprehensive list of US stock symbols from major indices.

        Returns:
            List of stock symbols from S&P 500, NASDAQ-100, and Dow Jones
        """
        try:
            return self._fetch_all_us_stocks()
        except Exception as e:
            self.logger.warning(f"Failed to fetch comprehensive ticker list: {e}")
            self.logger.info("Falling back to sample ticker list")
            return [
                "AAPL", "MSFT", "GOOGL", "AMZN", "META",
                "TSLA", "NVDA", "JPM", "JNJ", "V",
                "WMT", "PG", "UNH", "MA", "HD",
                "DIS", "BAC", "ADBE", "CMCSA", "NFLX",
            ]

    def _fetch_all_us_stocks(self) -> list[str]:
        """Fetch all US stock tickers from NASDAQ, NYSE, and AMEX.

        Returns:
            Combined list of unique stock symbols from major US exchanges
        """
        all_symbols = set()

        for exchange in ["NASDAQ", "NYSE", "AMEX"]:
            self.logger.info(f"Fetching {exchange} tickers...")
            symbols = self._fetch_exchange_tickers(exchange)
            all_symbols.update(symbols)
            self.logger.info(f"  Found {len(symbols)} {exchange} stocks")

        symbols_list = sorted(list(all_symbols))
        self.logger.info(f"Total unique stocks: {len(symbols_list)}")

        return symbols_list

    def _fetch_exchange_tickers(self, exchange: str) -> list[str]:
        """Fetch ticker symbols from US-Stock-Symbols GitHub repository.

        Args:
            exchange: Exchange name (NASDAQ, NYSE, or AMEX)

        Returns:
            List of stock symbols from the exchange
        """
        try:
            base_url = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main"
            exchange_files = {
                "NASDAQ": f"{base_url}/nasdaq/nasdaq_full_tickers.json",
                "NYSE": f"{base_url}/nyse/nyse_full_tickers.json",
                "AMEX": f"{base_url}/amex/amex_full_tickers.json",
            }

            url = exchange_files.get(exchange)
            if not url:
                self.logger.warning(f"Unknown exchange: {exchange}")
                return []

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            req = urllib.request.Request(url, headers=headers)

            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())

            if isinstance(data, list):
                symbols = [
                    item.get('symbol', item) if isinstance(item, dict) else item
                    for item in data
                ]
            else:
                self.logger.warning(f"Unexpected JSON format for {exchange}")
                return []

            symbols = [str(s).strip().upper() for s in symbols if s]
            return symbols

        except Exception as e:
            self.logger.warning(f"Failed to fetch {exchange} tickers: {e}")
            return []

    def collect_from_file(self, file_path: str) -> CollectionResult[pd.DataFrame]:
        """Collect ticker information from a file.

        Args:
            file_path: Path to file containing stock symbols (one per line)

        Returns:
            CollectionResult with DataFrame containing ticker information
        """
        try:
            with open(file_path, "r") as f:
                symbols = [line.strip() for line in f if line.strip()]
            return self.collect(symbols=symbols)
        except Exception as e:
            return CollectionResult.fail(f"Failed to read file: {e}")
