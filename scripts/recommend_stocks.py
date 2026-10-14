#!/usr/bin/env python3
"""Recommend stocks from collected data and metrics (step 4).

Which criteria run is decided per invocation: every criterion is registered
under a key and can be switched on or off, and its threshold overridden, from a
JSON config or the command line.

Usage:
    python scripts/recommend_stocks.py [options]

Examples:
    # List every available criterion with its tunable parameters
    python scripts/recommend_stocks.py --list-filters

    # Default: all eight criteria at their default thresholds
    python scripts/recommend_stocks.py --market US

    # Remove two criteria
    python scripts/recommend_stocks.py --disable revenue_growth,quick_ratio

    # Run only three criteria
    python scripts/recommend_stocks.py --enable dividend_yield,consecutive_dividends,debt_ratio

    # Loosen a threshold
    python scripts/recommend_stocks.py --set dividend_yield.min_dividend_yield=3.0

    # Reuse a saved criteria set
    python scripts/recommend_stocks.py --config configs/conservative.json
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from smart_investor.analysis.calculator import MetricsCalculator
from smart_investor.db.config import DatabaseConfig
from smart_investor.db.connection import DatabaseConnection
from smart_investor.db.models import GlobalTicker
from smart_investor.filters import registry
from smart_investor.filters.config import FilterConfig
from smart_investor.filters.engine import StockFilterEngine
from smart_investor.models.stock import FinancialMetrics, Market

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

COUNTRY_BY_MARKET = {
    "US": "United States",
    "KR": "South Korea",
}

# A strategy is a saved criteria selection, not a different engine - the same
# metrics are computed once and each strategy filters them its own way.
STRATEGY_CONFIGS = {
    "dividend": "configs/dividend.json",
    "value": "configs/value.json",
}


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    Separate from :func:`main` so the defaults can be asserted directly.

    Returns:
        The configured parser.
    """
    parser = argparse.ArgumentParser(
        description="Recommend stocks using configurable criteria",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--list-filters",
        action="store_true",
        help="List available criteria and their parameters, then exit",
    )
    parser.add_argument(
        "--strategy",
        choices=["dividend", "value", "both"],
        help="Criteria preset: dividend (배당주), value (가치주), or both. "
             "'both' screens once and writes one workbook with a sheet each",
    )
    parser.add_argument(
        "--config",
        help="JSON file selecting criteria and thresholds",
    )
    parser.add_argument(
        "--enable",
        help="Comma-separated criteria to run (default: all registered)",
    )
    parser.add_argument(
        "--disable",
        help="Comma-separated criteria to drop",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY.PARAM=VALUE",
        help="Override a threshold, e.g. --set debt_ratio.max_debt_ratio=150",
    )
    parser.add_argument(
        "--market",
        choices=["US", "KR", "ALL"],
        default="ALL",
        help="Market to screen (default: ALL)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of tickers to process (0 = no limit)",
    )
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="Read indicators from global_value instead of recomputing",
    )
    parser.add_argument(
        "--show-failures",
        type=int,
        default=0,
        metavar="N",
        help="Also print N near-miss stocks with their failed criteria",
    )
    parser.add_argument(
        "--save-config",
        metavar="PATH",
        help="Write the resolved criteria selection to a JSON file and exit",
    )
    parser.add_argument(
        "--notify",
        metavar="CHANNELS",
        help="Notification channels: slack, telegram, email (comma-separated). "
             "Defaults to slack when SLACK_TOKEN is configured",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="Do not send anywhere, overriding the default",
    )
    parser.add_argument(
        "--notify-channel",
        help="Slack channel override, e.g. '#investing' (default: SLACK_CHANNEL)",
    )
    parser.add_argument(
        "--notify-empty",
        action="store_true",
        help="Notify even when no stock passes (default: stay quiet)",
    )
    parser.add_argument(
        "--excel",
        nargs="?",
        const="auto",
        default="auto",
        metavar="PATH",
        help="Write the result to an xlsx file (default: on, into reports/). "
             "Attached to the Slack message when notifying",
    )
    parser.add_argument(
        "--no-excel",
        action="store_true",
        help="Skip the xlsx report",
    )
    parser.add_argument(
        "--enrich-delay",
        type=float,
        default=0.0,
        help="Seconds between profile lookups when building the Excel report",
    )
    return parser


def main() -> int:
    """Run the recommendation."""
    args = build_parser().parse_args()

    if args.list_filters:
        _print_filters()
        return 0

    if args.no_excel:
        args.excel = None

    # Built before screening starts so a missing token fails in a second rather
    # than after a full market scan.
    try:
        notifiers = _build_notifiers(args)
    except ValueError as e:
        logger.error(f"❌ Notification error: {e}")
        return 1

    try:
        filter_config = _build_config(args)
    except (ValueError, TypeError, KeyError, FileNotFoundError) as e:
        logger.error(f"❌ Filter configuration error: {e}")
        return 1

    if args.save_config:
        _save_config(filter_config, args.save_config)
        return 0

    # "both" screens once and filters the shared metrics twice, so the two
    # strategies come from identical inputs and land in one workbook.
    strategies = (
        ["dividend", "value"] if args.strategy == "both" else [args.strategy or "dividend"]
    )

    try:
        configs = {name: _config_for(args, name, filter_config) for name in strategies}
        engines = {name: StockFilterEngine(config=cfg) for name, cfg in configs.items()}
    except (TypeError, KeyError, ValueError, FileNotFoundError) as e:
        logger.error(f"❌ Filter configuration error: {e}")
        return 1

    try:
        db_config = DatabaseConfig.from_env()
    except ValueError as e:
        logger.error(f"❌ Configuration error: {e}")
        return 1

    results = {}

    with DatabaseConnection(db_config) as db:
        session = db.get_session()
        calculator = MetricsCalculator(session)

        tickers = _load_tickers(session, args)
        logger.info(f"Screening {len(tickers)} tickers...")

        all_metrics = []
        errors = []

        for index, ticker in enumerate(tickers, start=1):
            try:
                metrics_dict = calculator.calculate_all_metrics(
                    ticker.Symbol, use_cache=args.use_cache
                )
                all_metrics.append(_to_financial_metrics(ticker, metrics_dict))
            except Exception as e:
                errors.append((ticker.Symbol, str(e)))

            if index % 200 == 0:
                logger.info(f"  {index}/{len(tickers)} processed")

        for name in strategies:
            logger.info("")
            logger.info(f"[{name}] active criteria:")
            for line in configs[name].describe():
                logger.info(f"  - {line}")

            passed, failed = engines[name].filter_stocks(all_metrics)
            if _uses_valuation(configs[name]):
                passed = _verify_shortlist(session, passed, engines[name], args.enrich_delay)
            _print_results(passed, failed, len(all_metrics), args.show_failures, name)
            results[name] = {
                "strategy": name,
                "passed": passed,
                "criteria": configs[name].describe(),
                "total_analyzed": len(all_metrics),
            }

        if errors:
            logger.info(f"\n⚠️ {len(errors)} errors during processing")

        excel_path = None
        if args.excel and any(r["passed"] for r in results.values()):
            # Built while the session is open: the rows need price, volume and
            # company details that live in the database.
            excel_path = _build_excel(
                session=session,
                results=[results[name] for name in strategies],
                market=args.market,
                path=args.excel,
                enrich_delay=args.enrich_delay,
            )
        elif args.excel:
            logger.info("\nNo stocks passed - skipping Excel report")

        session.close()

    if notifiers:
        for name in strategies:
            _notify(
                notifiers,
                passed=results[name]["passed"],
                total_analyzed=len(all_metrics),
                criteria=results[name]["criteria"],
                market=args.market,
                strategy=name,
                send_when_empty=args.notify_empty,
                # One workbook covers every strategy, so it is attached once.
                excel_path=excel_path if name == strategies[-1] else None,
            )

    return 0


def _build_excel(
    session,
    results: list[dict],
    market: str,
    path: str,
    enrich_delay: float,
) -> "Path | None":
    """Assemble report rows for every strategy and write one workbook.

    Args:
        session: Open SQLAlchemy session.
        results: One dict per strategy with ``strategy``, ``passed``,
            ``criteria`` and ``total_analyzed`` keys.
        market: Market label.
        path: Destination path, or ``auto`` to name it by market and date.
        enrich_delay: Seconds between profile lookups.

    Returns:
        The path written, or None on failure.
    """
    from datetime import datetime

    from smart_investor.reporting import build_multi_workbook, fetch_profiles

    # One stock can qualify under both strategies; look its profile up once.
    tickers = sorted({r.ticker for spec in results for r in spec["passed"]})
    details = _load_ticker_details(session, tickers)

    logger.info(f"\nFetching profiles for {len(tickers)} stocks...")
    profiles = fetch_profiles(
        [(t, details[t]["country"], details[t]["exchange"]) for t in tickers if t in details],
        delay=enrich_delay,
    )

    sheets = []
    for spec in results:
        rows = []
        for number, result in enumerate(rank(spec["passed"], spec["strategy"]), start=1):
            rows.append(_excel_row(number, result, details, profiles))

        sheets.append({
            "strategy": spec["strategy"],
            "rows": rows,
            "criteria": spec["criteria"],
            "total_analyzed": spec["total_analyzed"],
        })

    if path == "auto":
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        path = f"reports/recommendations_{market}_{stamp}.xlsx"

    try:
        written = build_multi_workbook(sheets, path, market=market)
        logger.info(f"📄 Excel report: {written}")
        return written
    except Exception as e:
        logger.error(f"❌ Failed to write Excel report: {e}")
        return None


def _excel_row(number: int, result, details: dict, profiles: dict) -> dict:
    """Build one report row from a filter result.

    Args:
        number: 1-based rank within its sheet.
        result: FilterResult for a passing stock.
        details: Company details keyed by ticker.
        profiles: Fetched profiles keyed by ticker.

    Returns:
        Row dict keyed by the workbook's column keys.
    """
    detail = details.get(result.ticker, {})
    profile = profiles.get(result.ticker)
    metrics = result.metrics

    return {
        "no": number,
        "ticker": result.ticker,
        "company": detail.get("name"),
        "sector": (profile.sector if profile else None) or detail.get("sector"),
        "industry": profile.industry if profile else None,
        "country": detail.get("country"),
        # The stored market cap is null for US tickers, so the freshly fetched
        # one takes precedence and the stored value is the fallback.
        "market_cap": (profile.market_cap if profile else None) or detail.get("market_cap"),
        "pe_ratio": (profile.pe_ratio if profile else None)
        or (metrics.per if metrics else None),
        "price": detail.get("price"),
        "change": detail.get("change"),
        "volume": detail.get("volume"),
        "dividend_yield": metrics.dividend_yield if metrics else None,
        "years_of_dividend": metrics.years_of_dividend if metrics else None,
        "debt_ratio": metrics.debt_ratio if metrics else None,
        "quick_ratio": metrics.quick_ratio if metrics else None,
        "per": metrics.per if metrics else None,
        "pbr": metrics.pbr if metrics else None,
        "roe": metrics.roe if metrics else None,
        "operating_margin": metrics.operating_margin if metrics else None,
    }


def _load_ticker_details(session, tickers: list[str]) -> dict:
    """Load company details and latest quote for the given tickers.

    Args:
        session: Open SQLAlchemy session.
        tickers: Symbols to load.

    Returns:
        Mapping of ticker to its detail dict.
    """
    from sqlalchemy import text

    if not tickers:
        return {}

    details = {}

    rows = session.execute(
        text(
            "SELECT Symbol, Name, Exchange, Sector, `Market Cap`, country "
            "FROM global_ticker WHERE Symbol IN :symbols"
        ),
        {"symbols": tuple(tickers)},
    ).all()

    for symbol, name, exchange, sector, market_cap, country in rows:
        details[symbol] = {
            "name": name,
            "exchange": exchange,
            # Korean rows carry the literal "Unknown"; treat it as absent so the
            # freshly fetched sector wins.
            "sector": None if sector in (None, "", "Unknown") else sector,
            "market_cap": float(market_cap) if market_cap else None,
            "country": country,
            "price": None,
            "change": None,
            "volume": None,
        }

    # Latest two closes per ticker give both the price and the daily change.
    for ticker in tickers:
        quote = session.execute(
            text(
                "SELECT Close, Volume FROM global_price WHERE ticker = :t "
                "ORDER BY Date DESC LIMIT 2"
            ),
            {"t": ticker},
        ).all()

        if not quote or ticker not in details:
            continue

        close = float(quote[0][0])
        details[ticker]["price"] = close
        details[ticker]["volume"] = int(quote[0][1]) if quote[0][1] else None

        if len(quote) > 1 and quote[1][0]:
            previous = float(quote[1][0])
            if previous:
                # Stored as a fraction; the sheet formats it as a percentage.
                details[ticker]["change"] = (close - previous) / previous

    return details


# Criteria that divide a market cap by a statement figure, and so break when
# the two are in different currencies.
_VALUATION_KEYS = frozenset({"per", "pbr", "psr", "graham_number"})


def _uses_valuation(config: FilterConfig) -> bool:
    """Whether a configuration includes a market-cap-based criterion.

    Args:
        config: Resolved criteria configuration.

    Returns:
        True when the currency guard is worth running.
    """
    return bool(_VALUATION_KEYS & set(config.resolve_keys()))


def _verify_shortlist(session, passed: list, engine, delay: float = 0.0) -> list:
    """Re-check the shortlist against live figures before publishing it.

    Screening runs on stored statement data, which has two failure modes that
    only ever produce *too cheap* a valuation, so they concentrate at the top of
    a value screen:

    - US-listed foreign issuers trade in USD but file in their home currency, so
      a USD market cap over a KRW net income gives a PER near 0.01.
    - The share count on an annual statement goes stale after heavy dilution;
      WHLR's filed 10,531 shares against a $0.365 price implied a $3,844 market
      cap where the real one was $916,022.

    Both are cheap to catch once the list is down to a few dozen names: the
    filing currency and a live market cap are one lookup each, and the ratios
    scale linearly with market cap, so they can be corrected and re-tested
    rather than merely flagged.

    Args:
        session: Open SQLAlchemy session.
        passed: Stocks passing every active criterion.
        engine: The engine whose criteria to re-apply.
        delay: Seconds between lookups.

    Returns:
        The stocks that still pass once corrected.
    """
    from dataclasses import replace

    from sqlalchemy import text

    from smart_investor.reporting import fetch_filing_currency

    if not passed:
        return passed

    tickers = [r.ticker for r in passed]
    rows = session.execute(
        text(
            "SELECT Symbol, country, Exchange, financial_currency "
            "FROM global_ticker WHERE Symbol IN :symbols"
        ),
        {"symbols": tuple(tickers)},
    ).all()
    details = {r[0]: {"country": r[1], "exchange": r[2], "currency": r[3]} for r in rows}

    logger.info(f"\nVerifying {len(tickers)} shortlisted stocks against live figures...")

    kept, dropped = [], []

    for result in passed:
        detail = details.get(result.ticker, {})
        country = detail.get("country")
        exchange = detail.get("exchange")

        currency = detail.get("currency")
        if not currency:
            currency = fetch_filing_currency(result.ticker, country, exchange)
            if currency:
                session.execute(
                    text(
                        "UPDATE global_ticker SET financial_currency = :c WHERE Symbol = :s"
                    ),
                    {"c": currency, "s": result.ticker},
                )

        trading = "KRW" if country == "South Korea" else "USD"
        # Unknown stays in: a failed lookup should not silently shrink the list.
        if currency and currency.upper() != trading:
            dropped.append(f"{result.ticker}(files in {currency})")
            continue

        corrected = _correct_with_live_market_cap(result, country, exchange, delay)
        if corrected is None:
            dropped.append(f"{result.ticker}(no live market cap)")
            continue

        if engine.filter_stock(corrected).passed:
            kept.append(replace(result, metrics=corrected))
        else:
            dropped.append(f"{result.ticker}(fails on corrected figures)")

    session.commit()

    if dropped:
        logger.info(f"Excluded {len(dropped)}: {', '.join(dropped[:8])}"
                    f"{' ...' if len(dropped) > 8 else ''}")

    return kept


def _correct_with_live_market_cap(result, country, exchange, delay: float):
    """Rescale a stock's valuation ratios onto its live market cap.

    PER, PBR and PSR are all market cap over a statement figure, so correcting
    the market cap scales each of them by the same factor.

    Args:
        result: FilterResult for a shortlisted stock.
        country: Country recorded on the ticker.
        exchange: Exchange recorded on the ticker.
        delay: Seconds to wait after the lookup.

    Returns:
        Corrected FinancialMetrics, the original metrics when no correction is
        needed, or None when the stock has ratios but no live market cap to
        check them against.
    """
    import time
    from dataclasses import replace

    from smart_investor.reporting import fetch_profile

    metrics = result.metrics
    if metrics is None:
        return metrics

    has_ratios = any(v is not None for v in (metrics.per, metrics.pbr, metrics.psr))
    if not has_ratios:
        return metrics

    profile = fetch_profile(result.ticker, country, exchange)
    if delay:
        time.sleep(delay)

    live = profile.market_cap
    if not live or not metrics.market_cap:
        return None

    factor = live / metrics.market_cap
    # Within a few percent the stored figure is fine; rescaling would only add
    # noise from the price moving between the two snapshots.
    if 0.9 <= factor <= 1.1:
        return metrics

    return replace(
        metrics,
        market_cap=live,
        per=metrics.per * factor if metrics.per is not None else None,
        pbr=metrics.pbr * factor if metrics.pbr is not None else None,
        psr=metrics.psr * factor if metrics.psr is not None else None,
    )


def _config_for(args, strategy: str, base: FilterConfig) -> FilterConfig:
    """Resolve the criteria configuration for one strategy.

    An explicit --config or --enable/--disable always wins, so a manual
    selection is never silently replaced by a preset.

    Args:
        args: Parsed CLI arguments.
        strategy: ``dividend`` or ``value``.
        base: Configuration already assembled from the CLI.

    Returns:
        The configuration to screen with.
    """
    if args.config or args.enable or args.disable or args.strategy != "both":
        return base

    config = FilterConfig.load(_project_path(STRATEGY_CONFIGS[strategy]))
    # --set overrides still apply on top of the preset.
    for key, params in base.params.items():
        config.params.setdefault(key, {}).update(params)
    return config


def _requested_channels(args) -> list[str]:
    """Decide which notification channels a run should use.

    Notifying is the default so a scheduled run needs no flags, but only when a
    Slack token is actually configured - defaulting to a channel that cannot
    deliver would turn every run on an unconfigured machine into an error.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Channel names, empty when nothing should be sent.
    """
    import os

    from smart_investor.db.config import load_env

    if args.no_notify:
        return []

    # The token lives in .env, which nothing has read yet at this point.
    load_env()

    if args.notify:
        return [name.strip().lower() for name in args.notify.split(",") if name.strip()]

    if os.getenv("SLACK_TOKEN"):
        return ["slack"]

    logger.info("SLACK_TOKEN not set - skipping notification (use --notify to force)")
    return []


def _build_notifiers(args) -> list:
    """Create the notification services a run should send to.

    Args:
        args: Parsed CLI arguments.

    Returns:
        List of notification services, empty when nothing should be sent.

    Raises:
        ValueError: If a channel name is unknown or is not configured.
    """
    channels = _requested_channels(args)
    if not channels:
        return []

    from smart_investor.notifications.email import EmailNotifier
    from smart_investor.notifications.slack import SlackNotifier
    from smart_investor.notifications.telegram import TelegramNotifier

    notifiers = []

    for name in channels:
        if name == "slack":
            notifier = SlackNotifier(channel=args.notify_channel)
            # Checked up front so a missing token fails before a full screening
            # run rather than after it.
            if not notifier.token:
                raise ValueError(
                    "SLACK_TOKEN is not set. Create a Slack app at "
                    "https://api.slack.com/apps, install it to the workspace, and "
                    "put its bot token in .env as SLACK_TOKEN"
                )
        elif name == "telegram":
            notifier = TelegramNotifier()
            if not notifier.token:
                raise ValueError("TELEGRAM_TOKEN is not set in .env")
        elif name == "email":
            notifier = EmailNotifier()
            if not notifier.username:
                raise ValueError("SMTP_USERNAME is not set in .env")
        else:
            raise ValueError(f"Unknown channel '{name}' (use slack, telegram or email)")

        notifiers.append(notifier)

    return notifiers


def _notify(
    notifiers: list,
    passed: list,
    total_analyzed: int,
    criteria: list[str],
    market: str,
    send_when_empty: bool,
    strategy: str = "dividend",
    excel_path=None,
) -> None:
    """Send the recommendation to every configured channel.

    Args:
        notifiers: Notification services.
        passed: Stocks passing every active criterion.
        total_analyzed: How many stocks were screened.
        criteria: Descriptions of the active criteria.
        market: Market label for the heading.
        send_when_empty: Send even when nothing passed.
        strategy: Strategy label shown in the heading.
        excel_path: Workbook to attach where the channel supports uploads.
    """
    from smart_investor.reporting.excel import STRATEGY_TITLES

    label = f"{STRATEGY_TITLES.get(strategy, strategy)} · {market}"
    import asyncio

    if not passed and not send_when_empty:
        logger.info("\nNo stocks passed - skipping notification (use --notify-empty to send)")
        return

    async def run() -> None:
        for notifier in notifiers:
            name = type(notifier).__name__
            try:
                result = await notifier.send_recommendation(
                    stocks=passed,
                    total_analyzed=total_analyzed,
                    criteria=criteria,
                    market=label,
                )
            except Exception as e:
                logger.error(f"❌ {name}: {e}")
                continue

            if result.success:
                logger.info(f"✅ {name}: {result.message}")
            else:
                logger.error(f"❌ {name}: {result.error}")
                continue

            # Only Slack supports uploads today; other channels get the summary.
            if excel_path and hasattr(notifier, "send_file"):
                # Slack's upload endpoint needs a channel ID; the message just
                # sent carries the resolved one, avoiding a channels:read scope.
                upload = await notifier.send_file(
                    str(excel_path),
                    comment=f"종목 추천 ({market}) 상세",
                    title=f"recommendations_{market}",
                    channel=result.metadata.get("channel_id"),
                )
                if upload.success:
                    logger.info(f"✅ {name}: {upload.message}")
                else:
                    logger.error(f"❌ {name} file upload: {upload.error}")

    logger.info("")
    asyncio.run(run())


def _print_filters() -> None:
    """Print every registered criterion with its tunable parameters."""
    logger.info("Available criteria (use the key with --enable / --disable / --set):\n")

    for spec in registry.all_specs():
        logger.info(f"  {spec.key}")
        logger.info(f"      {spec.description or spec.label}")
        if spec.params:
            for name, default in spec.params.items():
                logger.info(f"      param: {name} (default: {default})")
        else:
            logger.info("      param: none")
        logger.info("")


def _build_config(args) -> FilterConfig:
    """Assemble a FilterConfig from the config file and CLI overrides.

    CLI flags are applied after the file so they win.

    Args:
        args: Parsed CLI arguments.

    Returns:
        The resolved configuration.

    Raises:
        ValueError: If a ``--set`` expression is malformed.
    """
    if args.config:
        config = FilterConfig.load(args.config)
    elif args.strategy and args.strategy != "both":
        config = FilterConfig.load(_project_path(STRATEGY_CONFIGS[args.strategy]))
    else:
        config = FilterConfig()

    if args.enable:
        config.enabled = [key.strip() for key in args.enable.split(",") if key.strip()]

    if args.disable:
        config.disabled = list(config.disabled) + [
            key.strip() for key in args.disable.split(",") if key.strip()
        ]

    for expression in args.set:
        key, param, value = _parse_override(expression)
        config.params.setdefault(key, {})[param] = value

    # Surfaces unknown keys and bad parameter names before any DB work starts.
    config.build()
    return config


def _project_path(relative: str) -> Path:
    """Resolve a path relative to the project root.

    Args:
        relative: Path relative to the repository root.

    Returns:
        Absolute path, so presets resolve regardless of the working directory.
    """
    return Path(__file__).parent.parent / relative


def _parse_override(expression: str) -> tuple[str, str, float | int | str]:
    """Parse a ``key.param=value`` override.

    Args:
        expression: Raw ``--set`` argument.

    Returns:
        Tuple of (filter key, parameter name, parsed value).

    Raises:
        ValueError: If the expression is not in ``key.param=value`` form.
    """
    if "=" not in expression:
        raise ValueError(f"--set expects KEY.PARAM=VALUE, got '{expression}'")

    target, raw_value = expression.split("=", 1)
    if "." not in target:
        raise ValueError(f"--set expects KEY.PARAM=VALUE, got '{expression}'")

    key, param = target.rsplit(".", 1)
    return key.strip(), param.strip(), _parse_value(raw_value.strip())


def _parse_value(raw: str) -> float | int | str:
    """Convert an override value to int or float when possible.

    Args:
        raw: Raw value text.

    Returns:
        Parsed value.
    """
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def _save_config(config: FilterConfig, path: str) -> None:
    """Write the resolved criteria selection to a JSON file.

    Args:
        config: Resolved configuration.
        path: Destination path.
    """
    payload = {
        "enabled": config.resolve_keys(),
        "params": config.params,
    }
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    logger.info(f"✅ Saved criteria selection to {destination}")


def _load_tickers(session, args) -> list:
    """Load the tickers to screen.

    Args:
        session: SQLAlchemy session.
        args: Parsed CLI arguments.

    Returns:
        List of GlobalTicker rows.
    """
    query = session.query(GlobalTicker)

    country = COUNTRY_BY_MARKET.get(args.market)
    if country:
        query = query.filter(GlobalTicker.country == country)

    if args.limit > 0:
        query = query.limit(args.limit)

    return query.all()


def _to_financial_metrics(ticker, metrics_dict: dict) -> FinancialMetrics:
    """Convert a metrics dictionary into a FinancialMetrics instance.

    Args:
        ticker: GlobalTicker row.
        metrics_dict: Result of ``calculate_all_metrics``.

    Returns:
        Populated FinancialMetrics.
    """
    market = Market.KR if ticker.country == "South Korea" else Market.US

    return FinancialMetrics(
        ticker=ticker.Symbol,
        market=market,
        dividend_yield=_to_float(metrics_dict.get("dividend_yield")),
        debt_ratio=_to_float(metrics_dict.get("debt_ratio")),
        quick_ratio=_to_float(metrics_dict.get("quick_ratio")),
        interest_coverage_ratio=_to_float(metrics_dict.get("interest_coverage_ratio")),
        has_interest_expense=metrics_dict.get("has_interest_expense"),
        per=_to_float(metrics_dict.get("per")),
        pbr=_to_float(metrics_dict.get("pbr")),
        psr=_to_float(metrics_dict.get("psr")),
        roe=_to_float(metrics_dict.get("roe")),
        operating_margin=_to_float(metrics_dict.get("operating_margin")),
        market_cap=_to_float(metrics_dict.get("market_cap")),
        dividend_increasing=metrics_dict.get("dividend_increasing", False),
        revenue_increasing=metrics_dict.get("revenue_increasing", False),
        operating_income_increasing=metrics_dict.get("operating_income_increasing", False),
        years_of_dividend=metrics_dict.get("years_of_dividend", 0),
    )


def _sort_key(strategy: str):
    """Return the ranking key for a strategy.

    Args:
        strategy: ``dividend`` or ``value``.

    Returns:
        Tuple of (key function, reverse flag).
    """
    if strategy == "value":
        # Cheapest first. Missing PER sorts last rather than first.
        return (lambda r: (r.metrics.per if r.metrics and r.metrics.per else 1e9)), False

    # Highest yield first: among stocks clearing every criterion, yield is what
    # the dividend criteria are built around.
    return (lambda r: (r.metrics.dividend_yield if r.metrics else 0) or 0), True


def rank(passed: list, strategy: str) -> list:
    """Order results the way the strategy cares about.

    Args:
        passed: Stocks passing every active criterion.
        strategy: ``dividend`` or ``value``.

    Returns:
        Sorted list.
    """
    key, reverse = _sort_key(strategy)
    return sorted(passed, key=key, reverse=reverse)


def _print_results(passed, failed, analyzed: int, show_failures: int, strategy: str) -> None:
    """Print the recommendation report.

    Args:
        passed: Stocks passing every active criterion.
        failed: Stocks failing at least one criterion.
        analyzed: Number of stocks analysed.
        show_failures: How many near-misses to list.
        strategy: Which metrics to show and how to rank.
    """
    title = "VALUE STOCKS" if strategy == "value" else "DIVIDEND STOCKS"

    logger.info("")
    logger.info("=" * 70)
    logger.info(f"RECOMMENDED - {title}")
    logger.info("=" * 70)

    if passed:
        for result in rank(passed, strategy):
            m = result.metrics
            if not m:
                logger.info(f"  {result.ticker}")
                continue

            if strategy == "value":
                logger.info(
                    f"  {result.ticker:8s} ({result.market.value}) "
                    f"PER={_fmt(m.per)}  PBR={_fmt(m.pbr)}  "
                    f"ROE={_fmt(m.roe)}%  OPM={_fmt(m.operating_margin)}%"
                )
            else:
                logger.info(
                    f"  {result.ticker:8s} ({result.market.value}) "
                    f"DY={_fmt(m.dividend_yield)}%  "
                    f"Years={m.years_of_dividend:<3d} "
                    f"DR={_fmt(m.debt_ratio)}%  QR={_fmt(m.quick_ratio)}%"
                )
    else:
        logger.info("  No stocks passed every active criterion")

    logger.info("")
    logger.info(f"Passed: {len(passed)}/{analyzed}")

    if show_failures and failed:
        near_misses = sorted(failed, key=lambda r: len(r.failed_criteria))[:show_failures]
        logger.info("")
        logger.info("-" * 70)
        logger.info(f"NEAR MISSES (fewest failed criteria, top {len(near_misses)})")
        logger.info("-" * 70)
        for result in near_misses:
            logger.info(f"  {result.ticker} - {len(result.failed_criteria)} failed")
            for reason in result.failed_criteria:
                logger.info(f"      {reason}")


def _fmt(value) -> str:
    """Format an optional number for the report.

    Args:
        value: Number or None.

    Returns:
        Fixed-width formatted value, or ``n/a``.
    """
    return f"{value:7.2f}" if value is not None else "    n/a"


def _to_float(value) -> float | None:
    """Convert a value to float or None.

    Args:
        value: Raw value.

    Returns:
        Float value or None.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    sys.exit(main())
