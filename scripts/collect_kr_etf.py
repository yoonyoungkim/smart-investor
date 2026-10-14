#!/usr/bin/env python3
"""Collect Korean ETF data."""

import argparse
import logging
import sys
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from io import StringIO

# Suppress pykrx KRX login warning (prints directly to stdout)
_original_stdout = sys.stdout
sys.stdout = StringIO()
try:
    from pykrx import stock as krx
finally:
    sys.stdout = _original_stdout

warnings.filterwarnings("ignore")
logging.getLogger("pykrx").setLevel(logging.CRITICAL)

import FinanceDataReader as fdr
import pandas as pd

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Popular Korean ETFs
DEFAULT_ETFS = [
    "069500",  # KODEX 200
    "102110",  # TIGER 200
    "360750",  # TIGER 미국S&P500
    "133690",  # TIGER 미국나스닥100
    "371460",  # TIGER 차이나전기차SOLACTIVE
    "305720",  # KODEX 2차전지산업
    "091160",  # KODEX 반도체
    "091180",  # KODEX 자동차
    "117700",  # KODEX 건설
    "228790",  # TIGER 화장품
    "139260",  # TIGER 미디어콘텐츠
    "157450",  # TIGER 헬스케어
    "143850",  # TIGER 200IT
    "139220",  # TIGER 200건설
    "266360",  # KODEX 배당성장
    "211560",  # TIGER 배당성장
    "329200",  # TIGER 미국테크TOP10
    "381170",  # TIGER 미국필라델피아반도체나스닥
    "379800",  # KODEX 미국S&P500TR
    "379810",  # KODEX 미국나스닥100TR
]


def get_all_kr_etfs() -> list[str]:
    """Fetch all Korean ETF symbols."""
    logger.info("Fetching all Korean ETF symbols...")
    etf_df = fdr.StockListing('ETF/KR')
    symbols = etf_df['Symbol'].tolist()
    logger.info(f"Found {len(symbols)} Korean ETFs")
    return symbols


def collect_etf_list(symbols: list[str]) -> None:
    """Collect ETF listing information."""
    logger.info(f"Collecting ETF list...")

    etf_df = fdr.StockListing('ETF/KR')

    if symbols:
        filtered = etf_df[etf_df['Symbol'].isin(symbols)]
    else:
        filtered = etf_df

    print(filtered[['Symbol', 'Name', 'MarCap']].head(30).to_string())
    print(f"\n총 {len(filtered)}개 ETF")


def collect_etf_info(symbols: list[str], delay: float = 0.0) -> "pd.DataFrame | None":
    """Collect detailed ETF information.

    Returns:
        Persistence-ready ticker DataFrame (saved to global_ticker), or None.

    Note:
        ``Market Cap`` stores FinanceDataReader's raw ``MarCap`` value (억 KRW units).
    """
    from datetime import date

    logger.info(f"Collecting ETF info for {len(symbols)} symbols...")

    etf_df = fdr.StockListing('ETF/KR')

    success_count = 0
    rows = []
    for symbol in symbols:
        try:
            row = etf_df[etf_df['Symbol'] == symbol]

            if not row.empty:
                row = row.iloc[0]
                print(f"\n{'='*50}")
                print(f"📊 {symbol}: {row.get('Name', 'N/A')}")
                print(f"{'='*50}")
                print(f"Category: {row.get('Category', 'N/A')}")
                print(f"Market Cap: ₩{row.get('MarCap', 0):,.0f}억")
                print(f"Volume: {row.get('Volume', 0):,}")
                print(f"Amount: ₩{row.get('Amount', 0):,}백만")

                marcap = row.get("MarCap")
                rows.append({
                    "Symbol": symbol,
                    "Name": row.get("Name", symbol),
                    "Exchange": "KRX",
                    "Sector": row.get("Category", "ETF") or "ETF",
                    "Market Cap": int(marcap) if pd.notna(marcap) else None,
                    "country": "South Korea",
                    "date": date.today(),
                })
                success_count += 1
            else:
                logger.warning(f"⚠️ {symbol}: Not found in ETF list")
        except Exception as e:
            logger.warning(f"⚠️ {symbol}: {e}")
        if delay > 0:
            time.sleep(delay)

    logger.info(f"ETF 정보 수집 완료: {success_count}/{len(symbols)}")

    if not rows:
        return None
    return pd.DataFrame(rows)


def collect_etf_price(symbols: list[str], days: int = 365, delay: float = 0.0) -> "pd.DataFrame | None":
    """Collect ETF price history.

    Returns:
        Combined persistence-ready price DataFrame, or None.
    """
    logger.info(f"Collecting price history for {len(symbols)} ETFs (days={days})...")

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    success_count = 0
    all_data = []
    for symbol in symbols:
        try:
            df = fdr.DataReader(symbol, start_date, end_date)

            if not df.empty:
                df = df.reset_index()
                # FinanceDataReader indexes by Date; normalize the column name
                if "Date" not in df.columns:
                    df = df.rename(columns={df.columns[0]: "Date"})
                df["ticker"] = symbol
                df["AdjClose"] = df["Close"]
                cols = ["Date", "Open", "High", "Low", "Close", "Volume", "AdjClose", "ticker"]
                df = df[[c for c in cols if c in df.columns]]
                all_data.append(df)
                success_count += 1
            else:
                logger.warning(f"⚠️ {symbol}: No data")
        except Exception as e:
            logger.warning(f"⚠️ {symbol}: {e}")
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


def collect_etf_dividend(symbols: list[str], delay: float = 0.0) -> "pd.DataFrame | None":
    """Collect ETF dividend history using yfinance.

    Returns:
        Combined persistence-ready dividend DataFrame, or None.
    """
    import yfinance as yf

    logger.info(f"Collecting dividend history for {len(symbols)} ETFs...")

    success_count = 0
    all_data = []
    for symbol in symbols:
        try:
            # Korean ETFs need .KS suffix for yfinance
            yf_symbol = f"{symbol}.KS"
            etf = yf.Ticker(yf_symbol)
            divs = etf.dividends

            if not divs.empty:
                print(f"\n{'='*50}")
                print(f"💰 {symbol} 배당(분배금) 내역 (최근 10건)")
                print(f"{'='*50}")
                print(divs.tail(10).to_string())

                div_df = pd.DataFrame(divs).reset_index()
                div_df.columns = ["Date", "Cash Amount"]
                div_df["ticker"] = symbol
                div_df["Ex-Dividend Date"] = div_df["Date"]
                div_df["Pay Date"] = div_df["Date"]
                div_df = div_df[["ticker", "Ex-Dividend Date", "Cash Amount", "Pay Date"]]
                all_data.append(div_df)
                success_count += 1
            else:
                logger.warning(f"⚠️ {symbol}: No dividend data")
        except Exception as e:
            logger.warning(f"⚠️ {symbol}: {e}")
        if delay > 0:
            time.sleep(delay)

    logger.info(f"배당 수집 완료: {success_count}/{len(symbols)}")

    if not all_data:
        return None
    return pd.concat(all_data, ignore_index=True)


def collect_etf_pdf(symbols: list[str], delay: float = 0.0) -> None:
    """Collect ETF PDF (Price, Dividend, NAV) data."""
    logger.info(f"Collecting PDF data for {len(symbols)} ETFs...")

    import io
    import contextlib

    today = datetime.now().strftime("%Y%m%d")

    success_count = 0
    for symbol in symbols:
        try:
            # Suppress stderr to hide pykrx logging bugs
            with contextlib.redirect_stderr(io.StringIO()):
                # Get ETF basic info from pykrx
                df = krx.get_etf_ohlcv_by_date(
                    fromdate=(datetime.now() - timedelta(days=30)).strftime("%Y%m%d"),
                    todate=today,
                    ticker=symbol
                )

            if not df.empty:
                latest = df.iloc[-1]
                print(f"\n📊 {symbol}")
                print(f"  Close: ₩{latest.get('종가', 0):,}")
                print(f"  Volume: {latest.get('거래량', 0):,}")
                print(f"  NAV: ₩{latest.get('NAV', 0):,.0f}")
                print(f"  Base Index: {latest.get('기초지수', 'N/A')}")
                success_count += 1
            else:
                logger.warning(f"⚠️ {symbol}: No PDF data")
        except Exception as e:
            logger.warning(f"⚠️ {symbol}: {e}")
        if delay > 0:
            time.sleep(delay)

    logger.info(f"PDF 수집 완료: {success_count}/{len(symbols)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect Korean ETF data")
    parser.add_argument(
        "symbols",
        nargs="*",
        default=None,
        help="ETF symbols to collect (default: popular ETFs)"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Collect ALL Korean ETFs (~1100 symbols)"
    )
    parser.add_argument(
        "--type",
        choices=["all", "list", "info", "price", "dividend", "pdf"],
        default="info",
        help="Type of data to collect"
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
        symbols = get_all_kr_etfs()
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
    print(f"Korean ETF Data Collector")
    print(f"{'='*60}")
    print(f"ETFs: {', '.join(symbols[:5])}{'...' if len(symbols) > 5 else ''}")
    print(f"Total: {len(symbols)} ETFs")
    print(f"Type: {args.type}")
    print(f"{'='*60}\n")

    collected: dict[str, "pd.DataFrame | None"] = {}

    if args.type in ["all", "list"]:
        collect_etf_list(symbols)
        print()

    if args.type in ["all", "info"]:
        collected["tickers"] = collect_etf_info(symbols, delay=args.delay)
        print()

    if args.type in ["all", "price"]:
        collected["prices"] = collect_etf_price(symbols, args.days, delay=args.delay)
        print()

    if args.type in ["all", "dividend"]:
        collected["dividends"] = collect_etf_dividend(symbols, delay=args.delay)
        print()

    if args.type in ["all", "pdf"]:
        collect_etf_pdf(symbols, delay=args.delay)
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
