#!/usr/bin/env python3
"""Collect the full Korean + US ticker universe and save to the database.

Unlike the per-symbol collectors, this pulls the entire listing for each market
in bulk via FinanceDataReader and upserts it into ``global_ticker`` in one run.

    # Collect every KR + US ticker and save
    python scripts/collect_all_tickers.py

    # Only one side
    python scripts/collect_all_tickers.py --market KR
    python scripts/collect_all_tickers.py --market US

    # Preview without writing to the database
    python scripts/collect_all_tickers.py --dry-run

Note:
    FinanceDataReader's US listings do not include market cap, so ``Market Cap``
    is stored as NULL for US tickers. KR listings include market cap (KRW).
"""

import argparse
import logging
import sys
import warnings
from datetime import date
from pathlib import Path

warnings.filterwarnings("ignore")

import FinanceDataReader as fdr
import pandas as pd

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Persistence-ready column order for the global_ticker table.
TICKER_COLUMNS = ["Symbol", "Name", "Exchange", "Sector", "Market Cap", "country", "date"]

KR_MARKETS = ["KOSPI", "KOSDAQ"]
US_MARKETS = ["NASDAQ", "NYSE", "AMEX"]


def _clean_market_cap(value) -> int | None:
    """Coerce a market-cap value to a Python int, or None if missing/NaN."""
    if value is None or pd.isna(value):
        return None
    return int(value)


def collect_kr_tickers() -> pd.DataFrame | None:
    """Collect all KOSPI + KOSDAQ tickers as a persistence-ready DataFrame."""
    frames = []
    for market in KR_MARKETS:
        logger.info(f"Fetching {market} listing...")
        df = fdr.StockListing(market)
        df = df.assign(Market=market)
        frames.append(df)
        logger.info(f"  {market}: {len(df)} tickers")

    if not frames:
        return None

    raw = pd.concat(frames, ignore_index=True)
    ticker_df = pd.DataFrame({
        "Symbol": raw["Code"].astype(str),
        "Name": raw["Name"].astype(str).str.slice(0, 255),
        "Exchange": raw["Market"],
        "Sector": "Unknown",  # KRX listing has no clean sector field
        "Market Cap": raw.get("Marcap").apply(_clean_market_cap),
        "country": "South Korea",
        "date": date.today(),
    })
    return ticker_df[TICKER_COLUMNS]


def collect_us_tickers() -> pd.DataFrame | None:
    """Collect all NASDAQ + NYSE + AMEX tickers as a persistence-ready DataFrame.

    FinanceDataReader's US listings carry no market cap, so it is stored as NULL.
    """
    frames = []
    for market in US_MARKETS:
        logger.info(f"Fetching {market} listing...")
        df = fdr.StockListing(market)
        df = df.assign(Exchange=market)
        frames.append(df)
        logger.info(f"  {market}: {len(df)} tickers")

    if not frames:
        return None

    raw = pd.concat(frames, ignore_index=True)
    sector = raw.get("Industry")
    if sector is None:
        sector = pd.Series("Unknown", index=raw.index)
    sector = sector.fillna("Unknown").astype(str).str.slice(0, 100)

    ticker_df = pd.DataFrame({
        "Symbol": raw["Symbol"].astype(str),
        "Name": raw["Name"].astype(str).str.slice(0, 255),
        "Exchange": raw["Exchange"],
        "Sector": sector,
        "Market Cap": None,  # not provided by fdr US listings
        "country": "United States",
        "date": date.today(),
    })
    return ticker_df[TICKER_COLUMNS]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect full KR + US ticker universe and save to database"
    )
    parser.add_argument(
        "--market",
        choices=["ALL", "KR", "US"],
        default="ALL",
        help="Which markets to collect (default: ALL)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Collect and report counts without writing to the database",
    )

    args = parser.parse_args()

    print(f"\n{'='*60}")
    print("All Tickers Collector (KR + US)")
    print(f"{'='*60}")
    print(f"Market: {args.market}")
    print(f"Mode: {'dry-run (no save)' if args.dry_run else 'save to database'}")
    print(f"{'='*60}\n")

    frames = []

    if args.market in ["ALL", "KR"]:
        kr = collect_kr_tickers()
        if kr is not None:
            frames.append(kr)
            logger.info(f"🇰🇷 KR tickers collected: {len(kr)}")

    if args.market in ["ALL", "US"]:
        us = collect_us_tickers()
        if us is not None:
            frames.append(us)
            logger.info(f"🇺🇸 US tickers collected: {len(us)}")

    if not frames:
        logger.error("❌ No tickers collected.")
        return 1

    combined = pd.concat(frames, ignore_index=True)
    # A symbol can appear in more than one source listing; keep the first.
    before = len(combined)
    combined = combined.drop_duplicates(subset=["Symbol"], keep="first").reset_index(drop=True)
    if before != len(combined):
        logger.info(f"Removed {before - len(combined)} duplicate symbols")

    print(f"\n총 {len(combined)}개 티커 수집 완료")
    print(combined.groupby("country")["Symbol"].count().to_string())
    print("\nSample:")
    print(combined.head().to_string())

    if args.dry_run:
        print(f"\n{'='*60}")
        print("Dry-run complete (nothing saved).")
        print(f"{'='*60}\n")
        return 0

    logger.info("💾 Saving to database...")
    from smart_investor.db.saver import save_collected_data

    try:
        counts = save_collected_data({"tickers": combined})
        logger.info(f"✅ Database save complete: {counts.get('tickers', 0)} tickers")
    except Exception as e:
        logger.error(f"❌ Database save failed: {e}", exc_info=True)
        return 1

    print(f"\n{'='*60}")
    print("Collection complete!")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
