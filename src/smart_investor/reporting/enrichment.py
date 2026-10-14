"""Fetch the profile fields a recommendation report shows but the pipeline does not store.

The collection pipeline stores what the screening criteria need. A report also
wants sector, industry, market cap and P/E, which are not part of any criterion:

- ``global_ticker`` has no ``Industry`` column at all.
- Korean ``Sector`` is always ``Unknown``; the FinanceDataReader listings that
  populate it carry no industry classification.
- US ``Market Cap`` is null; the FinanceDataReader US listing omits it.
- P/E is never collected.

Rather than widen the schema and re-collect thousands of tickers for fields no
filter reads, these are fetched on demand for the handful of stocks a report
actually lists.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import yfinance as yf

logger = logging.getLogger(__name__)

# yfinance addresses Korean tickers by market suffix.
_KR_SUFFIX = {"KOSPI": ".KS", "KOSDAQ": ".KQ"}


@dataclass
class Profile:
    """Descriptive fields for one ticker.

    Every field is optional: yfinance covers US tickers well but leaves gaps for
    Korean ones, and a report shows a placeholder rather than inventing a value.
    """

    ticker: str
    sector: str | None = None
    industry: str | None = None
    market_cap: float | None = None
    pe_ratio: float | None = None


def yfinance_symbol(ticker: str, country: str, exchange: str | None) -> str:
    """Translate a stored ticker into the symbol yfinance expects.

    Args:
        ticker: Symbol as stored in ``global_ticker``.
        country: ``South Korea`` or ``United States``.
        exchange: Exchange name, used to pick the Korean market suffix.

    Returns:
        Symbol usable with :class:`yfinance.Ticker`.
    """
    if country != "South Korea":
        return ticker

    # KOSDAQ tickers resolve only under .KQ and KOSPI only under .KS; using the
    # wrong one returns an empty profile rather than an error.
    return ticker + _KR_SUFFIX.get(exchange or "", ".KS")


def fetch_profile(ticker: str, country: str, exchange: str | None = None) -> Profile:
    """Fetch descriptive fields for one ticker.

    Args:
        ticker: Symbol as stored in ``global_ticker``.
        country: ``South Korea`` or ``United States``.
        exchange: Exchange name, for the Korean market suffix.

    Returns:
        Profile with whatever the source provided; missing fields stay None.
    """
    symbol = yfinance_symbol(ticker, country, exchange)

    try:
        info = yf.Ticker(symbol).info or {}
    except Exception as exc:
        logger.debug(f"{ticker}: profile lookup failed: {exc}")
        return Profile(ticker=ticker)

    return Profile(
        ticker=ticker,
        sector=_clean(info.get("sector")),
        industry=_clean(info.get("industry")),
        market_cap=_positive(info.get("marketCap")),
        pe_ratio=_pe_ratio(info),
    )


def fetch_profiles(
    tickers: list[tuple[str, str, str | None]],
    delay: float = 0.0,
) -> dict[str, Profile]:
    """Fetch profiles for several tickers.

    Args:
        tickers: Tuples of (ticker, country, exchange).
        delay: Seconds between requests, to stay under yfinance rate limits.

    Returns:
        Mapping of ticker to its profile.
    """
    import time

    profiles: dict[str, Profile] = {}

    for index, (ticker, country, exchange) in enumerate(tickers):
        profiles[ticker] = fetch_profile(ticker, country, exchange)
        if delay and index < len(tickers) - 1:
            time.sleep(delay)

    filled = sum(1 for p in profiles.values() if p.sector or p.market_cap)
    logger.info(f"Fetched {filled}/{len(tickers)} profiles")

    return profiles


def fetch_filing_currency(ticker: str, country: str, exchange: str | None = None) -> str | None:
    """Look up the currency a company files its statements in.

    US-listed foreign issuers trade in USD but file in their home currency, so
    a market cap and a net income taken from the two sources are not comparable.

    Args:
        ticker: Symbol as stored in ``global_ticker``.
        country: ``South Korea`` or ``United States``.
        exchange: Exchange name, for the Korean market suffix.

    Returns:
        Currency code, or None when the lookup fails.
    """
    # DART files in KRW and KRX quotes in KRW, so Korean tickers agree by
    # construction and need no lookup.
    if country == "South Korea":
        return "KRW"

    symbol = yfinance_symbol(ticker, country, exchange)

    try:
        info = yf.Ticker(symbol).info or {}
    except Exception as exc:
        logger.debug(f"{ticker}: filing currency lookup failed: {exc}")
        return None

    currency = info.get("financialCurrency")
    return str(currency).upper() if currency else None


def _pe_ratio(info: dict) -> float | None:
    """Derive a price/earnings ratio from a yfinance info payload.

    ``trailingPE`` is present for US tickers but consistently absent for Korean
    ones, which do carry market cap and net income - and their quotient is the
    same ratio.

    Args:
        info: yfinance ``info`` mapping.

    Returns:
        P/E ratio, or None when it cannot be derived or earnings are negative.
    """
    trailing = _positive(info.get("trailingPE"))
    if trailing:
        return round(trailing, 2)

    market_cap = _positive(info.get("marketCap"))
    net_income = info.get("netIncomeToCommon")

    # A loss-making company has no meaningful P/E; report nothing rather than a
    # negative number that would sort as "cheap".
    if not market_cap or not net_income or net_income <= 0:
        return None

    return round(market_cap / net_income, 2)


def _clean(value) -> str | None:
    """Normalise a text field to None when empty.

    Args:
        value: Raw field value.

    Returns:
        Stripped string, or None.
    """
    if not value or not isinstance(value, str):
        return None

    text = value.strip()
    return text or None


def _positive(value) -> float | None:
    """Return a number only when it is positive.

    Args:
        value: Raw numeric field.

    Returns:
        The value as a float, or None when missing or non-positive.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    return number if number > 0 else None
