#!/usr/bin/env python3
"""Test Korean stock data collection.

Usage:
    python scripts/test_kr_collector.py [ticker]

Examples:
    python scripts/test_kr_collector.py 005930  # Samsung Electronics
    python scripts/test_kr_collector.py 000660  # SK Hynix
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from smart_investor.collectors.kr import (
    KRTickerCollector,
    KRPriceCollector,
    KRDividendCollector,
    KRFinancialCollector,
)


def test_ticker_collection(symbol: str) -> bool:
    """Test ticker info collection."""
    print(f"\n{'='*60}")
    print("Testing Ticker Collection")
    print('='*60)

    collector = KRTickerCollector()
    result = collector.collect(symbols=[symbol])

    if result.success and result.data is not None:
        print(f"✅ Ticker collection successful!")
        print(f"\nData:\n{result.data.to_string()}")
        return True
    else:
        print(f"❌ Ticker collection failed: {result.error}")
        return False


def test_price_collection(symbol: str) -> bool:
    """Test price data collection."""
    print(f"\n{'='*60}")
    print("Testing Price Collection")
    print('='*60)

    collector = KRPriceCollector(default_years=1)
    result = collector.collect(symbol=symbol)

    if result.success and result.data is not None:
        print(f"✅ Price collection successful!")
        print(f"Rows: {len(result.data)}")
        print(f"\nLatest prices:\n{result.data.tail().to_string()}")
        return True
    else:
        print(f"❌ Price collection failed: {result.error}")
        return False


def test_dividend_collection(symbol: str) -> bool:
    """Test dividend data collection."""
    print(f"\n{'='*60}")
    print("Testing Dividend Collection")
    print('='*60)

    collector = KRDividendCollector()
    result = collector.collect(symbol=symbol)

    if result.success and result.data is not None:
        print(f"✅ Dividend collection successful!")
        print(f"Rows: {len(result.data)}")
        print(f"\nDividend data:\n{result.data.to_string()}")
        return True
    else:
        print(f"⚠️ Dividend collection: {result.error}")
        return False


def test_financial_collection(symbol: str) -> bool:
    """Test financial data collection."""
    print(f"\n{'='*60}")
    print("Testing Financial Collection")
    print('='*60)

    collector = KRFinancialCollector()
    result = collector.collect(symbol=symbol)

    if result.success and result.data is not None:
        print(f"✅ Financial collection successful!")
        print(f"Rows: {len(result.data)}")
        print(f"\nFinancial data:\n{result.data.to_string()}")
        return True
    else:
        print(f"⚠️ Financial collection: {result.error}")
        return False


def main() -> int:
    """Run all collection tests."""
    # Default to Samsung Electronics
    symbol = sys.argv[1] if len(sys.argv) > 1 else "005930"

    print(f"Testing Korean stock collectors with symbol: {symbol}")

    results = []
    results.append(("Ticker", test_ticker_collection(symbol)))
    results.append(("Price", test_price_collection(symbol)))
    results.append(("Dividend", test_dividend_collection(symbol)))
    results.append(("Financial", test_financial_collection(symbol)))

    print(f"\n{'='*60}")
    print("SUMMARY")
    print('='*60)

    for name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"  {name}: {status}")

    all_passed = all(r[1] for r in results)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
