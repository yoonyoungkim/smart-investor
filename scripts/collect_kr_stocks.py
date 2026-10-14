#!/usr/bin/env python3
"""Collect Korean stock data and save to database."""

import argparse
import logging
import sys
import time
import warnings
import os
from pathlib import Path
from io import StringIO

# Suppress pykrx KRX login warning (prints directly to stdout)
_original_stdout = sys.stdout
sys.stdout = StringIO()
try:
    import pykrx
finally:
    sys.stdout = _original_stdout

warnings.filterwarnings("ignore")
logging.getLogger("pykrx").setLevel(logging.CRITICAL)

import FinanceDataReader as fdr

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from smart_investor.collectors.kr.ticker import KRTickerCollector
from smart_investor.collectors.kr.price import KRPriceCollector
from smart_investor.collectors.kr.dividend import KRDividendCollector
from smart_investor.collectors.kr.financial import KRFinancialCollector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Default Korean dividend stocks to track
DEFAULT_SYMBOLS = [
    # 고배당주
    "005930",  # 삼성전자
    "000660",  # SK하이닉스
    "035420",  # NAVER
    "005380",  # 현대차
    "051910",  # LG화학
    "006400",  # 삼성SDI
    "035720",  # 카카오
    "105560",  # KB금융
    "055550",  # 신한지주
    "086790",  # 하나금융지주
    "316140",  # 우리금융지주
    "017670",  # SK텔레콤
    "030200",  # KT
    "032830",  # 삼성생명
    "000810",  # 삼성화재
    "096770",  # SK이노베이션
    "034730",  # SK
    "003550",  # LG
    "066570",  # LG전자
    "012330",  # 현대모비스
]


def collect_tickers(
    symbols: list[str] = None, market: str = "ALL", use_fdr: bool = False
) -> "pd.DataFrame | None":
    """Collect ticker information.

    Returns:
        Persistence-ready DataFrame (Symbol, Name, Exchange, Sector,
        Market Cap, country, date), or None on failure.
    """
    import pandas as pd
    from datetime import date

    logger.info(f"Collecting ticker info (market={market})...")

    if use_fdr or symbols is None:
        # Use FinanceDataReader for all tickers (more reliable)
        all_data = []
        if market in ["ALL", "KOSPI"]:
            kospi = fdr.StockListing("KOSPI")
            kospi["Market"] = "KOSPI"
            all_data.append(kospi)
        if market in ["ALL", "KOSDAQ"]:
            kosdaq = fdr.StockListing("KOSDAQ")
            kosdaq["Market"] = "KOSDAQ"
            all_data.append(kosdaq)

        df = pd.concat(all_data, ignore_index=True)

        if symbols:
            df = df[df["Code"].isin(symbols)]

        print(df[["Code", "Name", "Market", "Marcap"]].head(20).to_string())
        print(f"\n총 {len(df)}개 티커 수집 완료")

        # Transform to persistence-ready schema
        ticker_df = pd.DataFrame({
            "Symbol": df["Code"],
            "Name": df["Name"],
            "Exchange": df["Market"],
            "Sector": df.get("Sector", "Unknown"),
            "Market Cap": df.get("Marcap"),
            "country": "South Korea",
            "date": date.today(),
        })
        return ticker_df

    collector = KRTickerCollector()
    all_data = []
    for symbol in symbols:
        result = collector.collect(symbol)
        if result.success and result.data is not None:
            print(result.data.to_string())
            all_data.append(result.data)
        else:
            logger.warning(f"⚠️ {symbol}: {result.error}")

    if not all_data:
        return None
    return pd.concat(all_data, ignore_index=True)


def collect_prices(symbols: list[str], days: int = 365, delay: float = 0.0) -> "pd.DataFrame | None":
    """Collect price history.

    Returns:
        Combined persistence-ready DataFrame of prices, or None.
    """
    import pandas as pd
    from datetime import datetime, timedelta

    logger.info(f"Collecting price history for {len(symbols)} symbols (days={days})...")
    collector = KRPriceCollector()

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    success_count = 0
    all_data = []
    for symbol in symbols:
        result = collector.collect(symbol, start_date=start_date, end_date=end_date)
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


def collect_dividends(
    symbols: list[str], delay: float = 0.0
) -> "tuple[pd.DataFrame | None, pd.DataFrame | None]":
    """Collect dividend history and the yields DART disclosed alongside it.

    Returns:
        Tuple of (dividend DataFrame, disclosed-yield DataFrame), either of
        which may be None. The yields come from the same requests and are used
        to detect per-share amounts left on a pre-split basis.
    """
    import pandas as pd

    logger.info(f"Collecting dividend history for {len(symbols)} symbols...")
    collector = KRDividendCollector(delay=delay)

    if not collector.client.configured:
        logger.error(
            "❌ DART_API_KEY is not set - Korean dividends come from DART. "
            "Get a free key at https://opendart.fss.or.kr/ and add "
            "DART_API_KEY=<key> to .env"
        )
        return None, None

    success_count = 0
    all_data = []
    all_yields = []
    for symbol in symbols:
        result = collector.collect(symbol)
        if result.success and result.data is not None and len(result.data) > 0:
            success_count += 1
            all_data.append(result.data)
            yields = result.metadata.get("disclosed_yields")
            if yields is not None and not yields.empty:
                all_yields.append(yields)
        else:
            logger.warning(f"⚠️ {symbol}: No dividend data")
        if delay > 0:
            time.sleep(delay)

    logger.info(f"배당 수집 완료: {success_count}/{len(symbols)}")

    dividends = pd.concat(all_data, ignore_index=True) if all_data else None
    disclosed = pd.concat(all_yields, ignore_index=True) if all_yields else None
    if disclosed is not None:
        logger.info(f"공시 배당수익률 수집: {len(disclosed)}건")
    return dividends, disclosed


def collect_financials(symbols: list[str], delay: float = 0.0) -> "pd.DataFrame | None":
    """Collect financial statements.

    Returns:
        Combined persistence-ready DataFrame of financials, or None.
    """
    import pandas as pd

    logger.info(f"Collecting financial data for {len(symbols)} symbols...")
    collector = KRFinancialCollector(delay=delay)

    if not collector.client.configured:
        logger.error(
            "❌ DART_API_KEY is not set - Korean financial statements come from "
            "DART. Get a free key at https://opendart.fss.or.kr/ and add "
            "DART_API_KEY=<key> to .env"
        )
        return None

    success_count = 0
    all_data = []

    for symbol in symbols:
        result = collector.collect(symbol)
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


def get_all_kr_symbols(market: str = "ALL") -> list[str]:
    """Fetch all Korean stock symbols from KOSPI/KOSDAQ."""
    symbols = []

    if market in ["ALL", "KOSPI"]:
        logger.info("Fetching KOSPI tickers...")
        kospi = fdr.StockListing("KOSPI")
        kospi_symbols = kospi["Code"].tolist()
        symbols.extend(kospi_symbols)
        logger.info(f"  Found {len(kospi_symbols)} KOSPI stocks")

    if market in ["ALL", "KOSDAQ"]:
        logger.info("Fetching KOSDAQ tickers...")
        kosdaq = fdr.StockListing("KOSDAQ")
        kosdaq_symbols = kosdaq["Code"].tolist()
        symbols.extend(kosdaq_symbols)
        logger.info(f"  Found {len(kosdaq_symbols)} KOSDAQ stocks")

    logger.info(f"Total: {len(symbols)} stocks")
    return symbols


def get_symbols_from_db() -> list[str]:
    """Load all Korean stock symbols from the global_ticker table.

    Requires global_ticker to be populated first, e.g. via
    ``python scripts/collect_all_tickers.py --market KR``.

    Returns:
        List of Korean ticker symbols stored in the database.
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
                .filter(GlobalTicker.country == "South Korea")
                .order_by(GlobalTicker.Symbol)
                .all()
            )
            return [row[0] for row in rows]
        finally:
            session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect Korean stock data")
    parser.add_argument(
        "symbols",
        nargs="*",
        default=None,
        help="Stock symbols to collect (default: major Korean stocks)"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Collect ALL Korean stocks (~2800 symbols)"
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
        "--market",
        choices=["ALL", "KOSPI", "KOSDAQ"],
        default="ALL",
        help="Market to collect (KOSPI, KOSDAQ, or ALL)"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=365,
        help="Days of price history to collect"
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
        logger.info("Loading Korean tickers from database (global_ticker)...")
        symbols = get_symbols_from_db()
        logger.info(f"Loaded {len(symbols)} Korean tickers from DB")
        if not symbols:
            logger.error(
                "No Korean tickers in database. Run first: "
                "python scripts/collect_all_tickers.py --market KR"
            )
            return 1
    elif args.all:
        symbols = get_all_kr_symbols(args.market)
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
    print(f"Korean Stock Data Collector")
    print(f"{'='*60}")
    print(f"Symbols: {', '.join(symbols[:5])}{'...' if len(symbols) > 5 else ''}")
    print(f"Type: {args.type}")
    print(f"{'='*60}\n")

    import pandas as pd
    collected: dict[str, pd.DataFrame | None] = {}

    # When sourcing tickers from the DB, skip re-collecting ticker info under
    # --type all (they already exist in global_ticker, and the per-symbol
    # pykrx lookup would be prohibitively slow for the full universe).
    skip_ticker = args.from_db and args.type == "all"

    if args.type in ["all", "ticker"] and not skip_ticker:
        collected["tickers"] = collect_tickers(symbols, market=args.market, use_fdr=args.all)
        print()

    if args.type in ["all", "price"]:
        collected["prices"] = collect_prices(symbols, args.days, delay=args.delay)
        print()

    if args.type in ["all", "dividend"]:
        collected["dividends"], collected["values"] = collect_dividends(
            symbols, delay=args.delay
        )
        print()

    if args.type in ["all", "financial"]:
        collected["financials"] = collect_financials(symbols, delay=args.delay)
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
