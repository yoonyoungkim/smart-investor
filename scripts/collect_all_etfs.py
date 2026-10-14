#!/usr/bin/env python3
"""Collect the full Korean + US ETF ticker universe and save to the database.

ETFs are stored in their own ``global_etf`` table (separate from stocks in
``global_ticker``) because they carry different fields and are not subject to
the stock financial-filter scan.

    # Collect every KR + US ETF and save
    python scripts/collect_all_etfs.py

    # Only one side
    python scripts/collect_all_etfs.py --market KR
    python scripts/collect_all_etfs.py --market US

    # Preview without writing to the database
    python scripts/collect_all_etfs.py --dry-run

Note:
    FinanceDataReader's ``ETF/US`` listing provides only Symbol and Name, so
    category/nav/market_cap are stored as NULL for US ETFs. ``ETF/KR`` provides
    category, NAV, and market cap.
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

# Persistence-ready column order for the global_etf table.
ETF_COLUMNS = ["Symbol", "Name", "Exchange", "category", "nav", "Market Cap", "country", "date"]


def _clean_number(value):
    """Coerce a numeric value to a Python scalar, or None if missing/NaN."""
    if value is None or pd.isna(value):
        return None
    return value


def collect_kr_etfs() -> pd.DataFrame | None:
    """Collect all Korean ETF tickers as a persistence-ready DataFrame."""
    logger.info("Fetching ETF/KR listing...")
    raw = fdr.StockListing("ETF/KR")
    logger.info(f"  ETF/KR: {len(raw)} ETFs")

    if raw.empty:
        return None

    etf_df = pd.DataFrame({
        "Symbol": raw["Symbol"].astype(str),
        "Name": raw["Name"].astype(str).str.slice(0, 255),
        "Exchange": "KRX",
        "category": raw.get("Category").astype(str).str.slice(0, 100),
        "nav": raw.get("NAV").apply(_clean_number),
        "Market Cap": raw.get("MarCap").apply(_clean_number),
        "country": "South Korea",
        "date": date.today(),
    })
    return etf_df[ETF_COLUMNS]


def collect_us_etfs() -> pd.DataFrame | None:
    """Collect all US ETF tickers as a persistence-ready DataFrame.

    FinanceDataReader's US ETF listing has only Symbol + Name, so category,
    NAV, and market cap are stored as NULL.
    """
    logger.info("Fetching ETF/US listing...")
    raw = fdr.StockListing("ETF/US")
    logger.info(f"  ETF/US: {len(raw)} ETFs")

    if raw.empty:
        return None

    etf_df = pd.DataFrame({
        "Symbol": raw["Symbol"].astype(str),
        "Name": raw["Name"].astype(str).str.slice(0, 255),
        "Exchange": "US",
        "category": None,
        "nav": None,
        "Market Cap": None,
        "country": "United States",
        "date": date.today(),
    })
    return etf_df[ETF_COLUMNS]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect full KR + US ETF universe and save to database"
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
    print("All ETFs Collector (KR + US)")
    print(f"{'='*60}")
    print(f"Market: {args.market}")
    print(f"Mode: {'dry-run (no save)' if args.dry_run else 'save to database'}")
    print(f"{'='*60}\n")

    frames = []

    if args.market in ["ALL", "KR"]:
        kr = collect_kr_etfs()
        if kr is not None:
            frames.append(kr)
            logger.info(f"🇰🇷 KR ETFs collected: {len(kr)}")

    if args.market in ["ALL", "US"]:
        us = collect_us_etfs()
        if us is not None:
            frames.append(us)
            logger.info(f"🇺🇸 US ETFs collected: {len(us)}")

    if not frames:
        logger.error("❌ No ETFs collected.")
        return 1

    combined = pd.concat(frames, ignore_index=True)
    before = len(combined)
    combined = combined.drop_duplicates(subset=["Symbol"], keep="first").reset_index(drop=True)
    if before != len(combined):
        logger.info(f"Removed {before - len(combined)} duplicate symbols")

    print(f"\n총 {len(combined)}개 ETF 티커 수집 완료")
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
        counts = save_collected_data({"etfs": combined})
        logger.info(f"✅ Database save complete: {counts.get('etfs', 0)} ETFs")
    except Exception as e:
        logger.error(f"❌ Database save failed: {e}", exc_info=True)
        return 1

    print(f"\n{'='*60}")
    print("Collection complete!")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
