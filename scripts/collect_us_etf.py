#!/usr/bin/env python3
"""Collect US ETF data."""

import argparse
import logging
import sys
import time
from pathlib import Path

import FinanceDataReader as fdr
import pandas as pd
import yfinance as yf

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from smart_investor.collectors.us.price import USPriceCollector
from smart_investor.collectors.us.dividend import USDividendCollector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Popular US ETFs
DEFAULT_ETFS = [
    "SPY",    # S&P 500
    "QQQ",    # NASDAQ 100
    "IWM",    # Russell 2000
    "DIA",    # Dow Jones
    "VTI",    # Total Stock Market
    "VOO",    # Vanguard S&P 500
    "VEA",    # Developed Markets
    "VWO",    # Emerging Markets
    "BND",    # Total Bond
    "GLD",    # Gold
    "SLV",    # Silver
    "USO",    # Oil
    "XLF",    # Financials
    "XLK",    # Technology
    "XLE",    # Energy
    "XLV",    # Healthcare
    "ARKK",   # ARK Innovation
    "SOXL",   # Semiconductor 3x
    "TQQQ",   # NASDAQ 3x
]


def get_all_us_etfs() -> list[str]:
    """Fetch all US ETF symbols."""
    logger.info("Fetching all US ETF symbols...")
    etf_df = fdr.StockListing('ETF/US')
    symbols = etf_df['Symbol'].tolist()
    logger.info(f"Found {len(symbols)} US ETFs")
    return symbols


def collect_etf_list(symbols: list[str]) -> None:
    """Collect ETF listing information."""
    logger.info(f"Collecting ETF list for {len(symbols)} symbols...")

    etf_df = fdr.StockListing('ETF/US')
    filtered = etf_df[etf_df['Symbol'].isin(symbols)]

    print(filtered[['Symbol', 'Name']].to_string())
    print(f"\n총 {len(filtered)}개 ETF")


def collect_etf_info(symbols: list[str], delay: float = 0.0) -> pd.DataFrame | None:
    """Collect detailed ETF information using yfinance.

    Returns:
        Persistence-ready ticker DataFrame (saved to global_ticker), or None.
    """
    from datetime import date

    logger.info(f"Collecting ETF info for {len(symbols)} symbols...")

    success_count = 0
    rows = []
    for symbol in symbols:
        try:
            etf = yf.Ticker(symbol)
            info = etf.info

            print(f"\n{'='*50}")
            print(f"📊 {symbol}: {info.get('shortName', 'N/A')}")
            print(f"{'='*50}")
            print(f"Category: {info.get('category', 'N/A')}")
            print(f"Total Assets: ${info.get('totalAssets', 0):,.0f}")
            print(f"NAV: ${info.get('navPrice', 0):.2f}")
            print(f"Expense Ratio: {info.get('annualReportExpenseRatio', 0)*100:.2f}%")
            print(f"Yield: {info.get('yield', 0)*100:.2f}%")
            print(f"52W High: ${info.get('fiftyTwoWeekHigh', 0):.2f}")
            print(f"52W Low: ${info.get('fiftyTwoWeekLow', 0):.2f}")

            rows.append({
                "Symbol": symbol,
                "Name": info.get("shortName") or info.get("longName") or symbol,
                "Exchange": info.get("exchange", "ETF"),
                "Sector": info.get("category", "ETF"),
                "Market Cap": info.get("totalAssets", 0),
                "country": "United States",
                "date": date.today(),
            })
            success_count += 1
        except Exception as e:
            logger.warning(f"⚠️ {symbol}: {e}")
        if delay > 0:
            time.sleep(delay)

    logger.info(f"ETF 정보 수집 완료: {success_count}/{len(symbols)}")

    if not rows:
        return None
    return pd.DataFrame(rows)


def collect_etf_price(symbols: list[str], period: str = "1y", delay: float = 0.0) -> pd.DataFrame | None:
    """Collect ETF price history.

    Returns:
        Combined persistence-ready price DataFrame, or None.
    """
    logger.info(f"Collecting price history for {len(symbols)} ETFs (period={period})...")
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


def collect_etf_dividend(symbols: list[str], delay: float = 0.0) -> pd.DataFrame | None:
    """Collect ETF dividend history.

    Returns:
        Combined persistence-ready dividend DataFrame, or None.
    """
    logger.info(f"Collecting dividend history for {len(symbols)} ETFs...")
    collector = USDividendCollector()

    success_count = 0
    all_data = []
    for symbol in symbols:
        result = collector.collect(symbol)
        if result.success and result.data is not None and len(result.data) > 0:
            print(f"\n{'='*50}")
            print(f"💰 {symbol} Dividend History (Last 10)")
            print(f"{'='*50}")
            print(result.data.tail(10).to_string())
            all_data.append(result.data)
            success_count += 1
        else:
            logger.warning(f"⚠️ {symbol}: No dividend data")
        if delay > 0:
            time.sleep(delay)

    logger.info(f"배당 수집 완료: {success_count}/{len(symbols)}")

    if not all_data:
        return None
    return pd.concat(all_data, ignore_index=True)


def collect_etf_holdings(symbols: list[str], delay: float = 0.0) -> None:
    """Collect ETF top holdings."""
    logger.info(f"Collecting holdings for {len(symbols)} ETFs...")

    success_count = 0
    for symbol in symbols:
        try:
            etf = yf.Ticker(symbol)

            # Get holdings if available
            try:
                holdings = etf.get_holdings()
                if holdings is not None and not holdings.empty:
                    print(f"\n{'='*50}")
                    print(f"📊 {symbol} Top Holdings")
                    print(f"{'='*50}")
                    print(holdings.head(10).to_string())
                    success_count += 1
                else:
                    logger.warning(f"⚠️ {symbol}: No holdings data")
            except:
                logger.warning(f"⚠️ {symbol}: Holdings not available")
        except Exception as e:
            logger.warning(f"⚠️ {symbol}: {e}")
        if delay > 0:
            time.sleep(delay)

    logger.info(f"보유종목 수집 완료: {success_count}/{len(symbols)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect US ETF data")
    parser.add_argument(
        "symbols",
        nargs="*",
        default=None,
        help="ETF symbols to collect (default: popular ETFs)"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Collect ALL US ETFs (~5400 symbols)"
    )
    parser.add_argument(
        "--type",
        choices=["all", "list", "info", "price", "dividend", "holdings"],
        default="info",
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
        help="Limit number of ETFs to collect (0 = no limit)"
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Skip first N ETFs (for batch processing)"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Delay between API requests in seconds (default: 0)"
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save to database (info→global_ticker, price→global_price, dividend→global_dividends)"
    )

    args = parser.parse_args()

    # Determine symbols to collect
    if args.all:
        symbols = get_all_us_etfs()
    elif args.symbols:
        symbols = args.symbols
    else:
        symbols = DEFAULT_ETFS

    # Apply offset and limit
    if args.offset > 0:
        symbols = symbols[args.offset:]
    if args.limit > 0:
        symbols = symbols[:args.limit]

    print(f"\n{'='*60}")
    print(f"US ETF Data Collector")
    print(f"{'='*60}")
    print(f"ETFs: {', '.join(symbols[:5])}{'...' if len(symbols) > 5 else ''}")
    print(f"Total: {len(symbols)} ETFs")
    print(f"Type: {args.type}")
    print(f"{'='*60}\n")

    collected: dict[str, pd.DataFrame | None] = {}

    if args.type in ["all", "list"]:
        collect_etf_list(symbols)
        print()

    if args.type in ["all", "info"]:
        collected["tickers"] = collect_etf_info(symbols, delay=args.delay)
        print()

    if args.type in ["all", "price"]:
        collected["prices"] = collect_etf_price(symbols, args.period, delay=args.delay)
        print()

    if args.type in ["all", "dividend"]:
        collected["dividends"] = collect_etf_dividend(symbols, delay=args.delay)
        print()

    if args.type in ["all", "holdings"]:
        collect_etf_holdings(symbols, delay=args.delay)
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
