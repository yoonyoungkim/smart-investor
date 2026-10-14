#!/usr/bin/env python3
"""Collect US stock data and save to database."""

import argparse
import logging
import sys
import time
from pathlib import Path

import pandas as pd

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from smart_investor.collectors.us.ticker import USTickerCollector
from smart_investor.collectors.us.price import USPriceCollector
from smart_investor.collectors.us.dividend import USDividendCollector
from smart_investor.collectors.us.financial import USFinancialCollector
from smart_investor.db.connection import DatabaseConnection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Default US dividend stocks to track
DEFAULT_SYMBOLS = [
    # Dividend Aristocrats (examples)
    "JNJ",    # Johnson & Johnson
    "PG",     # Procter & Gamble
    "KO",     # Coca-Cola
    "PEP",    # PepsiCo
    "MMM",    # 3M
    "ABT",    # Abbott Laboratories
    "ABBV",   # AbbVie
    "T",      # AT&T
    "VZ",     # Verizon
    "XOM",    # Exxon Mobil
    "CVX",    # Chevron
    "IBM",    # IBM
    "MCD",    # McDonald's
    "WMT",    # Walmart
    "HD",     # Home Depot
    "O",      # Realty Income (REIT)
    "AAPL",   # Apple
    "MSFT",   # Microsoft
]


def collect_tickers(symbols: list[str], delay: float = 0.0) -> pd.DataFrame | None:
    """Collect ticker information.

    Returns:
        DataFrame of collected tickers (persistence-ready), or None on failure.
    """
    logger.info(f"Collecting ticker info for {len(symbols)} symbols...")
    collector = USTickerCollector()
    result = collector.collect(symbols, delay=delay)

    if result.success:
        count = len(result.data) if result.data is not None else 0
        print(result.data.to_string())
        print(f"\n총 {count}개 티커 수집 완료")
        return result.data

    logger.error(f"❌ Failed: {result.error}")
    return None


def collect_prices(symbols: list[str], period: str = "1y", delay: float = 0.0) -> pd.DataFrame | None:
    """Collect price history.

    Returns:
        Combined DataFrame of collected prices (persistence-ready), or None.
    """
    logger.info(f"Collecting price history for {len(symbols)} symbols (period={period})...")
    collector = USPriceCollector()

    success_count = 0
    all_data = []
    for symbol in symbols:
        result = collector.collect(symbol, period=period)
        if result.success and result.data is not None:
            success_count += 1
            all_data.append(result.data)
        else:
            logger.warning(f"⚠️ {symbol}: {result.error if result.error else 'No data'}")
        if delay > 0:
            time.sleep(delay)

    logger.info(f"가격 수집 완료: {success_count}/{len(symbols)}")

    if not all_data:
        return None

    combined = pd.concat(all_data, ignore_index=True)
    print(f"\nSample data (last 5 rows):")
    print(combined.tail().to_string())
    print(f"\n총 {len(combined)}개 가격 기록 수집 완료")
    return combined


def collect_dividends(symbols: list[str], delay: float = 0.0) -> pd.DataFrame | None:
    """Collect dividend history.

    Returns:
        Combined DataFrame of collected dividends (persistence-ready), or None.
    """
    logger.info(f"Collecting dividend history for {len(symbols)} symbols...")
    collector = USDividendCollector()

    success_count = 0
    all_data = []
    for symbol in symbols:
        result = collector.collect(symbol)
        if result.success and result.data is not None and len(result.data) > 0:
            success_count += 1
            all_data.append(result.data)
        else:
            logger.warning(f"⚠️ {symbol}: No dividend data")
        if delay > 0:
            time.sleep(delay)

    logger.info(f"배당 수집 완료: {success_count}/{len(symbols)}")

    if not all_data:
        return None
    return pd.concat(all_data, ignore_index=True)


def collect_financials(
    symbols: list[str], delay: float = 0.0, frequency: str = "yearly"
) -> pd.DataFrame | None:
    """Collect financial statements.

    Args:
        symbols: Stock symbols to collect.
        delay: Seconds between requests.
        frequency: ``yearly`` or ``quarterly``. Quarterly statements refresh the
            balance-sheet accounts the debt, quick and book ratios read; income
            accounts stay on the annual figures because a single quarter is not
            comparable to a year.

    Returns:
        Combined DataFrame of collected financials (persistence-ready), or None.
    """
    logger.info(f"Collecting {frequency} financial data for {len(symbols)} symbols...")
    collector = USFinancialCollector()

    success_count = 0
    all_data = []
    for symbol in symbols:
        result = collector.collect(symbol, frequency=frequency)
        if result.success and result.data is not None:
            success_count += 1
            all_data.append(result.data)
        else:
            logger.warning(f"⚠️ {symbol}: {result.error}")
        if delay > 0:
            time.sleep(delay)

    logger.info(f"재무 수집 완료: {success_count}/{len(symbols)}")

    if not all_data:
        return None
    return pd.concat(all_data, ignore_index=True)


def get_all_us_symbols() -> list[str]:
    """Fetch all US stock symbols from NASDAQ, NYSE, AMEX."""
    collector = USTickerCollector()
    return collector._fetch_all_us_stocks()


def get_symbols_from_db() -> list[str]:
    """Load all US stock symbols from the global_ticker table.

    Requires global_ticker to be populated first, e.g. via
    ``python scripts/collect_all_tickers.py --market US``.

    Returns:
        List of US ticker symbols stored in the database.
    """
    from smart_investor.db.config import DatabaseConfig
    from smart_investor.db.connection import DatabaseConnection
    from smart_investor.db.models import GlobalTicker

    config = DatabaseConfig.from_env()
    with DatabaseConnection(config) as db:
        session = db.get_session()
        try:
            rows = (
                session.query(GlobalTicker.Symbol)
                .filter(GlobalTicker.country == "United States")
                .order_by(GlobalTicker.Symbol)
                .all()
            )
            return [row[0] for row in rows]
        finally:
            session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect US stock data")
    parser.add_argument(
        "symbols",
        nargs="*",
        default=None,
        help="Stock symbols to collect (default: dividend aristocrats)"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Collect ALL US stocks (~7000 symbols)"
    )
    parser.add_argument(
        "--from-db",
        action="store_true",
        help="Load the full ticker list from the global_ticker table "
             "(run collect_all_tickers.py first). With --type all, price/"
             "dividend/financial are collected and ticker step is skipped."
    )
    parser.add_argument(
        "--type",
        choices=["all", "ticker", "price", "dividend", "financial"],
        default="all",
        help="Type of data to collect"
    )
    parser.add_argument(
        "--period",
        default="1y",
        help="Price history period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, max)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of symbols to collect (0 = no limit)"
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Skip first N symbols (for batch processing)"
    )
    parser.add_argument(
        "--freq",
        choices=["yearly", "quarterly", "both"],
        default="yearly",
        help="Financial statement frequency (default: yearly). Quarterly data "
             "refreshes balance-sheet accounts only",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save to database"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Delay between API requests in seconds (default: 0)"
    )

    args = parser.parse_args()

    # Determine symbols to collect
    if args.from_db:
        logger.info("Loading US tickers from database (global_ticker)...")
        symbols = get_symbols_from_db()
        logger.info(f"Loaded {len(symbols)} US tickers from DB")
        if not symbols:
            logger.error(
                "No US tickers in database. Run first: "
                "python scripts/collect_all_tickers.py --market US"
            )
            return 1
    elif args.all:
        logger.info("Fetching all US stock symbols...")
        symbols = get_all_us_symbols()
        logger.info(f"Found {len(symbols)} symbols")
    elif args.symbols:
        symbols = args.symbols
    else:
        symbols = DEFAULT_SYMBOLS

    # Apply offset and limit
    if args.offset > 0:
        symbols = symbols[args.offset:]
    if args.limit > 0:
        symbols = symbols[:args.limit]

    print(f"\n{'='*60}")
    print(f"US Stock Data Collector")
    print(f"{'='*60}")
    print(f"Symbols: {', '.join(symbols[:5])}{'...' if len(symbols) > 5 else ''}")
    print(f"Type: {args.type}")
    print(f"{'='*60}\n")

    collected: dict[str, pd.DataFrame | None] = {}

    # When sourcing tickers from the DB, skip re-collecting ticker info under
    # --type all (they already exist in global_ticker, and the per-symbol
    # yfinance lookup would be prohibitively slow for the full universe).
    skip_ticker = args.from_db and args.type == "all"

    if args.type in ["all", "ticker"] and not skip_ticker:
        collected["tickers"] = collect_tickers(symbols, delay=args.delay)
        print()

    if args.type in ["all", "price"]:
        collected["prices"] = collect_prices(symbols, args.period, delay=args.delay)
        print()

    if args.type in ["all", "dividend"]:
        collected["dividends"] = collect_dividends(symbols, delay=args.delay)
        print()

    if args.type in ["all", "financial"]:
        frequencies = (
            ["yearly", "quarterly"] if args.freq == "both" else [args.freq]
        )
        frames = [
            collect_financials(symbols, delay=args.delay, frequency=freq)
            for freq in frequencies
        ]
        frames = [f for f in frames if f is not None and not f.empty]
        collected["financials"] = pd.concat(frames, ignore_index=True) if frames else None
        print()

    if args.save:
        logger.info("💾 Saving to database...")
        from smart_investor.db.saver import save_collected_data

        try:
            counts = save_collected_data(collected)
            total = sum(counts.values())
            logger.info(f"✅ Database save complete: {total} records ({counts})")
        except Exception as e:
            logger.error(f"❌ Database save failed: {e}", exc_info=True)
            return 1

    print(f"\n{'='*60}")
    print("Collection complete!")
    print(f"{'='*60}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
