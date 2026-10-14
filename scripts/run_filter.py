#!/usr/bin/env python3
"""Run stock filtering script.

Usage:
    python scripts/run_filter.py [--market US|KR|ALL] [--limit N]

Examples:
    python scripts/run_filter.py --market US --limit 100
    python scripts/run_filter.py --market KR
    python scripts/run_filter.py --market ALL
"""

import argparse
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from smart_investor.db.config import DatabaseConfig
from smart_investor.db.connection import DatabaseConnection
from smart_investor.db.models import GlobalTicker
from smart_investor.analysis.calculator import MetricsCalculator
from smart_investor.filters.engine import StockFilterEngine
from smart_investor.models.stock import FinancialMetrics, Market


def main() -> int:
    """Run stock filtering."""
    parser = argparse.ArgumentParser(description="Run stock filtering")
    parser.add_argument(
        "--market",
        choices=["US", "KR", "ALL"],
        default="ALL",
        help="Market to filter (default: ALL)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of stocks to process (0 = no limit)"
    )
    args = parser.parse_args()

    try:
        config = DatabaseConfig.from_env()
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        return 1

    print(f"Connecting to database...")

    with DatabaseConnection(config) as db:
        session = db.get_session()
        calculator = MetricsCalculator(session)
        engine = StockFilterEngine()

        # Get tickers to analyze
        query = session.query(GlobalTicker)

        if args.market == "US":
            query = query.filter(GlobalTicker.country == "United States")
        elif args.market == "KR":
            query = query.filter(GlobalTicker.country == "South Korea")

        if args.limit > 0:
            query = query.limit(args.limit)

        tickers = query.all()
        print(f"Found {len(tickers)} tickers to analyze")

        # Calculate metrics and filter
        all_metrics = []
        errors = []

        for i, ticker in enumerate(tickers):
            try:
                print(f"\rProcessing {i+1}/{len(tickers)}: {ticker.Symbol}...", end="")

                # Calculate metrics
                metrics_dict = calculator.calculate_all_metrics(ticker.Symbol)

                # Determine market
                market = Market.KR if ticker.country == "South Korea" else Market.US

                # Convert to FinancialMetrics
                metrics = FinancialMetrics(
                    ticker=ticker.Symbol,
                    market=market,
                    dividend_yield=_to_float(metrics_dict.get("dividend_yield")),
                    debt_ratio=_to_float(metrics_dict.get("debt_ratio")),
                    quick_ratio=_to_float(metrics_dict.get("quick_ratio")),
                    interest_coverage_ratio=_to_float(metrics_dict.get("interest_coverage_ratio")),
                    has_interest_expense=metrics_dict.get("has_interest_expense"),
                    dividend_increasing=metrics_dict.get("dividend_increasing", False),
                    revenue_increasing=metrics_dict.get("revenue_increasing", False),
                    operating_income_increasing=metrics_dict.get("operating_income_increasing", False),
                    years_of_dividend=metrics_dict.get("years_of_dividend", 0),
                )
                all_metrics.append(metrics)

            except Exception as e:
                errors.append((ticker.Symbol, str(e)))

        print()  # New line after progress

        # Run filtering
        passed, failed = engine.filter_stocks(all_metrics)

        # Print results
        print(f"\n{'='*60}")
        print("PASSED STOCKS")
        print('='*60)

        if passed:
            for result in passed:
                m = result.metrics
                if m:
                    print(
                        f"  {result.ticker} ({result.market.value}): "
                        f"DY={m.dividend_yield:.2f}%, "
                        f"Years={m.years_of_dividend}"
                    )
                else:
                    print(f"  {result.ticker}")
        else:
            print("  No stocks passed all filters")

        print(f"\nTotal passed: {len(passed)}/{len(all_metrics)}")

        if errors:
            print(f"\n⚠️ {len(errors)} errors during processing")

        session.close()

    return 0


def _to_float(value) -> float | None:
    """Convert value to float or None."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    sys.exit(main())
