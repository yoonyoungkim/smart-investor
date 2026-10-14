"""Financial metrics calculator."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from scipy.stats import linregress
from sqlalchemy import and_, func
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from smart_investor.db.models import (
    GlobalDividend,
    GlobalFinancialStatement,
    GlobalPrice,
    GlobalTicker,
    GlobalValue,
)

# Accounts pulled for every ticker in a single query rather than one lookup each.
_REQUIRED_ACCOUNTS = (
    "Total Debt",
    "Total Liabilities",
    "Total Assets",
    "Cash And Cash Equivalents",
    "Accounts Receivable",
    "Current Liabilities",
    "EBIT",
    "Operating Income",
    "Interest Expense",
    "Finance Costs",
    "Net Income",
    "Total Revenue",
    "EBITDA",
    # Equity is filed under a different name per market - see _EQUITY_ACCOUNTS.
    "Stockholders Equity",
    "Total Equity",
    # Shares outstanding lets US market cap be computed at the current price;
    # Korean filings carry no share count, so those fall back to the stored one.
    "Ordinary Shares Number",
    "Share Issued",
)

# yfinance files total equity as "Stockholders Equity"; DART's Korean statements
# map to "Total Equity". Reading only one name would silently drop an entire
# market from every equity-based metric, so both are tried in order.
_EQUITY_ACCOUNTS = ("Stockholders Equity", "Total Equity")

# Same pattern for the share count, which yfinance reports under either name.
_SHARE_COUNT_ACCOUNTS = ("Ordinary Shares Number", "Share Issued")

# Balance-sheet accounts: a balance at a point in time. A quarterly figure is
# simply a fresher reading of the same thing, so the newest one wins regardless
# of frequency - it cuts the staleness of the debt, quick and book ratios from
# as much as fifteen months down to three.
_STOCK_ACCOUNTS = frozenset({
    "Total Debt",
    "Total Liabilities",
    "Total Assets",
    "Cash And Cash Equivalents",
    "Accounts Receivable",
    "Current Liabilities",
    "Stockholders Equity",
    "Total Equity",
    "Ordinary Shares Number",
    "Share Issued",
})

# Income-statement accounts: an amount accumulated over a period, so a single
# quarter is roughly a quarter of the annual figure and cannot be substituted
# for it. Using one would divide every PER and PSR by four. Mixing them in would
# need a trailing-twelve-month sum, which is a separate piece of work, so these
# stay annual.
_FLOW_ACCOUNTS = frozenset({
    "EBIT",
    "EBITDA",
    "Operating Income",
    "Net Income",
    "Total Revenue",
    "Interest Expense",
    "Finance Costs",
})

# Indicators cached in ``global_value``.
CACHED_INDICATORS = (
    "DY", "DR", "QR", "ICR",          # dividend and stability
    "PER", "PBR", "PSR", "ROE", "OPM", "MKTCAP",   # valuation
)

# Indicator holding the dividend yield the filer disclosed to DART.
DISCLOSED_YIELD_INDICATOR = "DY_DART"

# ``global_price`` holds split-adjusted prices (pykrx returns 수정주가), while
# ``global_dividends`` holds the per-share amounts exactly as filed with DART,
# on the share count at filing time. After a split the two are on different
# bases, so dividing one by the other inflates the yield by the split ratio.
#
# The ratio is recoverable rather than guessable: DART discloses the yield it
# calculated for the same year, so DPS / (yield/100) is the unadjusted price at
# that year end, and dividing it by the stored adjusted price gives the factor.
# For 미원화학 that lands on 9.85-10.20 across five years - a 10:1 split.
#
# A real split ratio is a clean number, so the measured factor is snapped to the
# nearest one; anything that does not land near a clean ratio is treated as
# unresolved rather than forced.
#
# The tolerance is wide because the measurement is inherently noisy: DART's
# disclosed yield is computed against an average price over the year, not the
# year-end close the measurement divides by. Unsplit tickers were observed
# scattering between 0.93 and 1.19 for that reason. Every neighbouring pair of
# candidate ratios stays separated at this tolerance (see the test that asserts
# it), so widening it costs no precision - it only widens the band that is
# reported as unresolved.
SPLIT_TOLERANCE = 0.20

# Ratios KRX splits actually use, following the 액면가 ladder (5,000 -> 2,500 /
# 1,000 / 500 / 250 / 100 / 50). Ratios too close to their neighbours to be told
# apart at this tolerance are left out on purpose - snapping to the wrong one is
# worse than reporting unresolved.
#
# Only the split direction is corrected. Every measurement below 1 that this code
# produced traced back to a filer disclosing 현금배당수익률 against par value
# rather than share price (흥국 filed 56% on a 500원 par with a 280원 dividend),
# not to a share consolidation. Adjusting on those would have multiplied the
# dividend and manufactured a 50% yield. Erring toward leaving a yield
# understated only costs a missed candidate; overstating one puts a bogus stock
# at the top of the recommendation list.
PLAUSIBLE_SPLIT_RATIOS = (2, 5, 10, 20, 50, 100)

# How far from a fiscal year end a closing price may sit and still represent it.
# Year-end weekends and holidays put the last trading day a few days earlier.
_PRICE_LOOKBACK_DAYS = 30

# Years that must agree before a factor is trusted, and how far they may spread
# (as a fraction of the median) while still counting as agreement. A split moves
# every year by the same factor; price movement does not.
_MIN_SPLIT_MEASUREMENTS = 2
SPLIT_CONSISTENCY = 0.30

# With only one year to go on, consistency cannot be checked, so the factor has
# to be large enough that no price move explains it. Observed unsplit tickers
# reached 2.4x from price movement alone, so the bar sits at 5x.
_SINGLE_YEAR_MIN_FACTOR = 5

logger = logging.getLogger(__name__)


def _median(values: list[Decimal]) -> Decimal:
    """Return the median, which ignores a single bad year.

    Args:
        values: Non-empty list of measurements.

    Returns:
        The median value.
    """
    ordered = sorted(values)
    middle = len(ordered) // 2

    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _snap_to_split_ratio(measured: Decimal) -> Decimal | None:
    """Snap a measured basis difference onto a real split ratio.

    A split changes the share count by a clean factor, so a measurement near
    10.2 means a 10:1 split plus rounding noise, while one near 3.4 means the
    difference is not a split at all and must not be silently "corrected".

    Args:
        measured: Ratio of filed share basis to stored share basis.

    Returns:
        The matching ratio, ``Decimal("1")`` when no split is indicated, or None
        when the measurement matches no plausible ratio.
    """
    if measured <= 0:
        return None

    candidates: list[Decimal] = [Decimal("1")]
    candidates.extend(Decimal(str(ratio)) for ratio in PLAUSIBLE_SPLIT_RATIOS)

    for candidate in candidates:
        if abs(measured - candidate) / candidate <= Decimal(str(SPLIT_TOLERANCE)):
            return candidate

    return None


_INDICATOR_TO_METRIC = {
    "DY": "dividend_yield",
    "DR": "debt_ratio",
    "QR": "quick_ratio",
    "ICR": "interest_coverage_ratio",
    "PER": "per",
    "PBR": "pbr",
    "PSR": "psr",
    "ROE": "roe",
    "OPM": "operating_margin",
    "MKTCAP": "market_cap",
}


class MetricsCalculator:
    """Calculates financial metrics for stocks."""

    def __init__(self, session: Session) -> None:
        """Initialize calculator.

        Args:
            session: SQLAlchemy session
        """
        self.session = session

    def calculate_dividend_yield(self, ticker: str) -> Decimal | None:
        """Calculate dividend yield (DY) using trailing 12-month regular dividends.

        DY = (Annual Regular Dividend / Current Price) * 100

        Special dividends are filtered out using statistical outlier detection:
        - Dividends greater than median * 2.0 are considered special dividends
        - Only regular dividends are summed for annual dividend calculation

        Args:
            ticker: Stock symbol

        Returns:
            Dividend yield percentage or None
        """
        # Get latest price
        latest_price = (
            self.session.query(GlobalPrice.Close)
            .filter(GlobalPrice.ticker == ticker)
            .order_by(GlobalPrice.Date.desc())
            .first()
        )

        if not latest_price or not latest_price[0]:
            return None

        # Get all dividends from last 12 months
        one_year_ago = date.today() - timedelta(days=365)
        dividends = (
            self.session.query(GlobalDividend.cash_amount)
            .filter(
                and_(
                    GlobalDividend.ticker == ticker,
                    GlobalDividend.ex_dividend_date >= one_year_ago,
                )
            )
            .order_by(GlobalDividend.ex_dividend_date.desc())
            .all()
        )

        if not dividends:
            return Decimal("0.0")

        dividend_amounts = [float(d.cash_amount) for d in dividends]

        # Filter out special dividends using statistical method
        regular_dividends = self._filter_special_dividends(dividend_amounts)

        if not regular_dividends:
            return Decimal("0.0")

        annual_dividend = sum(regular_dividends)

        if annual_dividend == 0:
            return Decimal("0.0")

        # Put the dividend on the same share basis as the price before dividing.
        factor = self.dividend_split_factor(ticker)
        adjusted_dividend = Decimal(str(annual_dividend)) / factor

        dividend_yield = round(
            (adjusted_dividend / Decimal(str(latest_price[0]))) * 100, 2
        )

        return dividend_yield

    def dividend_split_factor(self, ticker: str) -> Decimal:
        """Measure how many stored shares one filed share corresponds to.

        Returns 1 when no adjustment is needed, which covers every US ticker
        (yfinance already reports split-adjusted dividends) and every Korean
        ticker that has not split.

        Args:
            ticker: Stock symbol

        Returns:
            Divisor to bring a filed per-share dividend onto the price's basis.
        """
        measurements = self._measure_split_factors(ticker)
        if not measurements:
            return Decimal("1")

        measured = _median(measurements)

        if not self._measurement_is_conclusive(ticker, measurements, measured):
            return Decimal("1")

        snapped = _snap_to_split_ratio(measured)

        if snapped is None:
            logger.warning(
                f"{ticker}: dividend/price basis differs by {measured:.2f}x, which "
                f"matches no plausible split ratio - leaving the dividend "
                f"unadjusted; its yield may be overstated"
            )
            return Decimal("1")

        if snapped < Decimal("1"):
            # See PLAUSIBLE_SPLIT_RATIOS: sub-1 readings come from par-based
            # yield disclosures, not consolidations.
            logger.debug(f"{ticker}: sub-1 factor {measured:.2f}x ignored")
            return Decimal("1")

        if snapped != Decimal("1"):
            logger.info(
                f"{ticker}: dividends filed pre-split; measured {measured:.2f}x "
                f"across {len(measurements)} year(s), adjusting by {snapped}x"
            )

        return snapped

    @staticmethod
    def _measurement_is_conclusive(
        ticker: str,
        measurements: list[Decimal],
        measured: Decimal,
    ) -> bool:
        """Decide whether a measurement is strong enough to act on.

        The measurement divides a price implied by DART's yield - which the filer
        computed against an average price over the year - by the year-end close.
        For an unsplit ticker that ratio is just the year's price movement, and
        was observed spanning 0.4x to 2.4x. Magnitude alone therefore cannot tell
        a 2:1 split from a stock that halved.

        What does distinguish them is consistency: a split shifts every year by
        the same factor, while price movement scatters. So several years that
        agree are conclusive, and a single year is only conclusive when the
        factor is far outside what any price move produces.

        Args:
            ticker: Stock symbol, for logging.
            measurements: Per-year factors.
            measured: Their median.

        Returns:
            True when the measurement may be turned into an adjustment.
        """
        if len(measurements) >= _MIN_SPLIT_MEASUREMENTS:
            spread = (max(measurements) - min(measurements)) / measured
            if spread <= Decimal(str(SPLIT_CONSISTENCY)):
                return True

            logger.debug(
                f"{ticker}: per-year factors scatter by {spread:.2f} - reads as "
                f"price movement rather than a split"
            )
            return False

        # One year only: act just on factors no price move plausibly reaches.
        if measured >= Decimal(str(_SINGLE_YEAR_MIN_FACTOR)):
            return True

        logger.debug(
            f"{ticker}: single-year factor {measured:.2f}x is within the range "
            f"ordinary price movement produces - not treated as a split"
        )
        return False

    def _measure_split_factors(self, ticker: str) -> list[Decimal]:
        """Compare filed and stored share bases for each disclosed fiscal year.

        For every year where DART disclosed both a per-share dividend and the
        yield it produced, ``DPS / (yield/100)`` is the unadjusted price at that
        year end. Dividing by the stored (adjusted) close gives the factor
        between the two bases.

        Args:
            ticker: Stock symbol

        Returns:
            One factor per usable fiscal year; empty when the ticker has no
            disclosed yields or no matching prices.
        """
        rows = (
            self.session.query(
                GlobalDividend.ex_dividend_date,
                GlobalDividend.cash_amount,
                GlobalValue.value,
            )
            .join(
                GlobalValue,
                and_(
                    GlobalValue.ticker == GlobalDividend.ticker,
                    GlobalValue.date == GlobalDividend.ex_dividend_date,
                    GlobalValue.indicator == DISCLOSED_YIELD_INDICATOR,
                ),
            )
            .filter(GlobalDividend.ticker == ticker)
            .all()
        )

        factors: list[Decimal] = []

        for period_end, dps, disclosed_yield in rows:
            if not dps or not disclosed_yield or disclosed_yield <= 0:
                continue

            price = self._close_near(ticker, period_end)
            if not price:
                continue

            implied_price = Decimal(str(dps)) / (Decimal(str(disclosed_yield)) / 100)
            factors.append(implied_price / Decimal(str(price)))

        return factors

    def _close_near(self, ticker: str, target: date) -> Decimal | None:
        """Get the last close at or shortly before a date.

        Args:
            ticker: Stock symbol
            target: Date to look back from.

        Returns:
            Closing price, or None when the window holds no trading day.
        """
        row = (
            self.session.query(GlobalPrice.Close)
            .filter(
                and_(
                    GlobalPrice.ticker == ticker,
                    GlobalPrice.Date <= target,
                    GlobalPrice.Date >= target - timedelta(days=_PRICE_LOOKBACK_DAYS),
                )
            )
            .order_by(GlobalPrice.Date.desc())
            .first()
        )

        return row[0] if row and row[0] else None

    def _disclosed_dividend_yield(self, ticker: str) -> Decimal | None:
        """Get the most recent dividend yield the filer disclosed to DART.

        Args:
            ticker: Stock symbol

        Returns:
            Disclosed yield percentage, or None for tickers with no filing
            (every US ticker, and Korean ones collected before this indicator
            existed).
        """
        value = (
            self.session.query(GlobalValue.value)
            .filter(
                and_(
                    GlobalValue.ticker == ticker,
                    GlobalValue.indicator == DISCLOSED_YIELD_INDICATOR,
                )
            )
            .order_by(GlobalValue.date.desc())
            .first()
        )

        return Decimal(str(value[0])) if value else None

    @staticmethod
    def _is_increasing_trend(values: list[float], min_r_squared: float = 0.3) -> bool:
        """Check if values show increasing trend using linear regression.

        Uses linear regression to determine if there's a positive trend.
        More robust than simple counting as it considers overall trend.

        Args:
            values: List of values in chronological order (oldest to newest)
            min_r_squared: Minimum R² value to consider trend reliable (default: 0.3)

        Returns:
            True if positive slope with sufficient confidence
        """
        if len(values) < 2:
            return False

        # x = time points (0, 1, 2, ...)
        x = list(range(len(values)))
        y = values

        # Perform linear regression
        slope, intercept, r_value, p_value, std_err = linregress(x, y)

        # Positive slope indicates increasing trend
        # R² (r_value²) indicates how well the line fits (0-1)
        # Higher R² means more reliable trend
        r_squared = r_value ** 2

        # Return True if slope is positive and trend is reliable
        return slope > 0 and r_squared >= min_r_squared

    def _filter_special_dividends(self, dividends: list[float]) -> list[float]:
        """Filter out special dividends from dividend list.

        Uses statistical outlier detection to identify special dividends.
        Dividends greater than median * 2.0 are considered special dividends.

        Args:
            dividends: List of dividend amounts

        Returns:
            List of regular dividends with special dividends removed
        """
        if not dividends or len(dividends) < 2:
            return dividends

        # Calculate median
        sorted_divs = sorted(dividends)
        n = len(sorted_divs)
        if n % 2 == 0:
            median = (sorted_divs[n // 2 - 1] + sorted_divs[n // 2]) / 2
        else:
            median = sorted_divs[n // 2]

        # Filter out outliers (special dividends)
        # Threshold: median * 2.0 (dividends above this are likely special)
        threshold = median * 2.0
        regular_dividends = [d for d in dividends if d <= threshold]

        # If we filtered out too many (>30%), use original list
        # This handles cases where dividend increased significantly
        if len(regular_dividends) < len(dividends) * 0.7:
            return dividends

        return regular_dividends

    def _latest_financial_date(self, ticker: str, freq: str = "y") -> date | None:
        """Get the most recent financial statement date for a ticker.

        Args:
            ticker: Stock symbol
            freq: ``y`` for annual or ``q`` for quarterly

        Returns:
            Latest statement date or None
        """
        return (
            self.session.query(func.max(GlobalFinancialStatement.date))
            .filter(
                and_(
                    GlobalFinancialStatement.ticker == ticker,
                    GlobalFinancialStatement.freq == freq,
                )
            )
            .scalar()
        )

    def _accounts_at(
        self,
        ticker: str,
        freq: str,
        statement_date: date,
        accounts,
    ) -> dict[str, float]:
        """Read a set of accounts from one statement date.

        Args:
            ticker: Stock symbol
            freq: ``y`` or ``q``
            statement_date: Date of the statement to read.
            accounts: Account names to fetch.

        Returns:
            Mapping of account name to value.
        """
        rows = (
            self.session.query(
                GlobalFinancialStatement.account,
                GlobalFinancialStatement.value,
            )
            .filter(
                and_(
                    GlobalFinancialStatement.ticker == ticker,
                    GlobalFinancialStatement.date == statement_date,
                    GlobalFinancialStatement.freq == freq,
                    GlobalFinancialStatement.account.in_(tuple(accounts)),
                )
            )
            .all()
        )

        return {row.account: float(row.value) for row in rows if row.value is not None}

    def _financial_snapshot(self, ticker: str) -> dict[str, float]:
        """Fetch every account the ratio metrics need, in one pass per frequency.

        Annual statements supply everything, then balance-sheet accounts are
        overlaid from the latest quarterly statement when that is more recent.
        Income-statement accounts are deliberately left on the annual figure -
        see :data:`_FLOW_ACCOUNTS`.

        Args:
            ticker: Stock symbol

        Returns:
            Mapping of account name to value. Empty when the ticker has no
            financial statements at all.
        """
        snapshot: dict[str, float] = {}

        annual_date = self._latest_financial_date(ticker, "y")
        if annual_date:
            snapshot = self._accounts_at(ticker, "y", annual_date, _REQUIRED_ACCOUNTS)

        quarterly_date = self._latest_financial_date(ticker, "q")
        if not quarterly_date:
            return snapshot

        # An older quarter than the last annual report is not fresher data.
        if annual_date and quarterly_date <= annual_date:
            return snapshot

        fresher = self._accounts_at(ticker, "q", quarterly_date, _STOCK_ACCOUNTS)
        snapshot.update(fresher)

        return snapshot

    def calculate_debt_ratio(self, ticker: str) -> Decimal | None:
        """Calculate debt ratio (DR).

        DR = (Total Debt / Total Assets) * 100

        Korean filings from DART disclose borrowings separately from total
        liabilities; when no borrowing lines were disclosed, total liabilities
        are used so the ratio stays defined (and conservative).

        Args:
            ticker: Stock symbol

        Returns:
            Debt ratio percentage or None
        """
        snapshot = self._financial_snapshot(ticker)
        if not snapshot:
            return None

        total_assets = snapshot.get("Total Assets")
        if not total_assets:
            return None

        total_debt = snapshot.get("Total Debt")
        if total_debt is None:
            total_debt = snapshot.get("Total Liabilities")

        if total_debt is None:
            return Decimal("0.0")

        debt_ratio = (Decimal(str(total_debt)) / Decimal(str(total_assets))) * 100
        return round(debt_ratio, 2)

    def calculate_quick_ratio(self, ticker: str) -> Decimal | None:
        """Calculate quick ratio (QR).

        QR = ((Cash + Accounts Receivable) / Current Liabilities) * 100

        Args:
            ticker: Stock symbol

        Returns:
            Quick ratio percentage or None
        """
        snapshot = self._financial_snapshot(ticker)
        if not snapshot:
            return None

        current_liabilities = snapshot.get("Current Liabilities")
        if not current_liabilities:
            return None

        quick_assets = snapshot.get("Cash And Cash Equivalents", 0.0) + snapshot.get(
            "Accounts Receivable", 0.0
        )

        quick_ratio = (Decimal(str(quick_assets)) / Decimal(str(current_liabilities))) * 100
        return round(quick_ratio, 2)

    def calculate_interest_coverage_ratio(self, ticker: str) -> Decimal | None:
        """Calculate interest coverage ratio (ICR).

        ICR = (EBIT / Interest Expense) * 100

        Korean filings rarely tag EBIT, so operating income is used as a
        fallback - the two are equivalent for most non-financial filers.

        Returns None both when financials are missing and when no interest
        expense was reported. Use :meth:`has_interest_expense` to tell the two
        apart; a company with no interest expense has nothing to cover rather
        than unknown coverage.

        Args:
            ticker: Stock symbol

        Returns:
            Interest coverage ratio percentage or None
        """
        snapshot = self._financial_snapshot(ticker)
        if not snapshot:
            return None

        interest_expense = self._interest_expense_from(snapshot)
        if not interest_expense:
            return None

        ebit = snapshot.get("EBIT")
        if ebit is None:
            ebit = snapshot.get("Operating Income")

        if ebit is None:
            return Decimal("0.0")

        icr = (Decimal(str(ebit)) / Decimal(str(interest_expense))) * 100
        return round(icr, 2)

    @staticmethod
    def _interest_expense_from(snapshot: dict[str, float]) -> float | None:
        """Pick the interest expense figure from a financial snapshot.

        Korean filers frequently disclose only aggregate 금융비용 (finance costs,
        which bundles interest with FX and other charges) in the primary
        statements, leaving interest expense to the notes. Falling back to
        finance costs overstates the denominator and therefore understates
        coverage, which errs on the conservative side rather than treating an
        indebted company as debt-free.

        Args:
            snapshot: Account values for the latest yearly statement.

        Returns:
            Interest expense, or None when neither account is present or usable.
        """
        for account in ("Interest Expense", "Finance Costs"):
            value = snapshot.get(account)
            if value:
                return value
        return None

    def _interest_expense(self, ticker: str) -> float | None:
        """Get the latest reported interest expense for a ticker.

        Args:
            ticker: Stock symbol

        Returns:
            Interest expense, or None when the account is absent or zero.
        """
        return self._interest_expense_from(self._financial_snapshot(ticker))

    def has_interest_expense(self, ticker: str) -> bool | None:
        """Whether the ticker reported a non-zero interest expense.

        Args:
            ticker: Stock symbol

        Returns:
            True when interest expense was reported, False when financials were
            found but carried none, and None when the ticker has no financials
            at all - the last case means coverage is unknown, not excellent.
        """
        snapshot = self._financial_snapshot(ticker)
        if not snapshot:
            return None
        return self._interest_expense_from(snapshot) is not None

    # ------------------------------------------------------------------
    # Valuation metrics
    # ------------------------------------------------------------------

    def calculate_market_cap(self, ticker: str) -> Decimal | None:
        """Calculate market capitalisation.

        Prefers shares outstanding times the latest close, which moves with the
        price. Korean filings carry no share count, so those fall back to the
        figure stored on ``global_ticker`` - a snapshot from the last ticker
        collection rather than a live value.

        Args:
            ticker: Stock symbol

        Returns:
            Market capitalisation, or None when neither source has it.
        """
        shares = self._first_account(self._financial_snapshot(ticker), _SHARE_COUNT_ACCOUNTS)
        price = self._latest_close(ticker)

        if shares and price:
            return round(Decimal(str(shares)) * Decimal(str(price)), 2)

        stored = (
            self.session.query(GlobalTicker.market_cap)
            .filter(GlobalTicker.Symbol == ticker)
            .first()
        )

        if stored and stored[0]:
            return Decimal(str(stored[0]))

        return None

    def calculate_per(self, ticker: str) -> Decimal | None:
        """Calculate the price/earnings ratio.

        Args:
            ticker: Stock symbol

        Returns:
            PER, or None when earnings are missing or non-positive - a negative
            ratio would sort as though the stock were cheap.
        """
        return self._ratio_to_market_cap(ticker, self._snapshot_value(ticker, ("Net Income",)))

    def calculate_pbr(self, ticker: str) -> Decimal | None:
        """Calculate the price/book ratio.

        Args:
            ticker: Stock symbol

        Returns:
            PBR, or None when equity is missing or non-positive.
        """
        return self._ratio_to_market_cap(ticker, self._snapshot_value(ticker, _EQUITY_ACCOUNTS))

    def calculate_psr(self, ticker: str) -> Decimal | None:
        """Calculate the price/sales ratio.

        Args:
            ticker: Stock symbol

        Returns:
            PSR, or None when revenue is missing or non-positive.
        """
        return self._ratio_to_market_cap(ticker, self._snapshot_value(ticker, ("Total Revenue",)))

    def calculate_roe(self, ticker: str) -> Decimal | None:
        """Calculate return on equity as a percentage.

        Args:
            ticker: Stock symbol

        Returns:
            ROE percentage, or None without both net income and positive equity.
            Losses are reported (a negative ROE is meaningful) but negative
            equity is not, since it flips the sign of an otherwise bad result.
        """
        snapshot = self._financial_snapshot(ticker)
        net_income = snapshot.get("Net Income")
        equity = self._first_account(snapshot, _EQUITY_ACCOUNTS)

        if net_income is None or not equity or equity <= 0:
            return None

        return round(Decimal(str(net_income)) / Decimal(str(equity)) * 100, 2)

    def calculate_operating_margin(self, ticker: str) -> Decimal | None:
        """Calculate operating margin as a percentage.

        Args:
            ticker: Stock symbol

        Returns:
            Operating margin percentage, or None without revenue.
        """
        snapshot = self._financial_snapshot(ticker)
        operating_income = snapshot.get("Operating Income")
        revenue = snapshot.get("Total Revenue")

        if operating_income is None or not revenue or revenue <= 0:
            return None

        return round(Decimal(str(operating_income)) / Decimal(str(revenue)) * 100, 2)

    def _ratio_to_market_cap(self, ticker: str, denominator: float | None) -> Decimal | None:
        """Divide market cap by a fundamental, rejecting non-positive divisors.

        Args:
            ticker: Stock symbol
            denominator: Earnings, equity or revenue.

        Returns:
            The ratio, or None when either term is unusable or the two are in
            different currencies.
        """
        if not denominator or denominator <= 0:
            return None

        if not self.currencies_match(ticker):
            return None

        market_cap = self.calculate_market_cap(ticker)
        if not market_cap:
            return None

        ratio = round(market_cap / Decimal(str(denominator)), 2)

        # A ratio that rounds to zero means the market cap is under half a
        # percent of the fundamental - no real company is valued at 1/200th of
        # its earnings. It is a data error (a stale share count, a mismatched
        # currency), and left as 0.00 it would sail through every "<= max"
        # valuation test as the cheapest stock on the list.
        if ratio == 0:
            logger.debug(
                f"{ticker}: market cap {market_cap} is negligible against "
                f"{denominator} - ratio unusable"
            )
            return None

        return ratio

    def currencies_match(self, ticker: str) -> bool:
        """Whether price and financial statements share a currency.

        US-listed foreign issuers trade in USD but file in their home currency,
        so a USD market cap over a KRW net income yields a PER near 0.01 - which
        then sorts to the top of a value screen. Ratios that mix the two are
        refused rather than published.

        Args:
            ticker: Stock symbol

        Returns:
            True when the currencies agree or the filing currency is unknown.
            Unknown is permissive on purpose: withholding every ratio until the
            whole market has been looked up would be worse than the mismatch it
            guards against, and the mismatch is rare.
        """
        row = (
            self.session.query(GlobalTicker.financial_currency, GlobalTicker.country)
            .filter(GlobalTicker.Symbol == ticker)
            .first()
        )

        if not row or not row[0]:
            return True

        filing_currency, country = row
        trading_currency = "KRW" if country == "South Korea" else "USD"

        if filing_currency.upper() == trading_currency:
            return True

        logger.debug(
            f"{ticker}: files in {filing_currency} but trades in {trading_currency} - "
            f"valuation ratios skipped"
        )
        return False

    def _snapshot_value(self, ticker: str, accounts: tuple[str, ...]) -> float | None:
        """Read the first available account from a ticker's snapshot.

        Args:
            ticker: Stock symbol
            accounts: Account names to try, in priority order.

        Returns:
            The value, or None when none of the accounts are present.
        """
        return self._first_account(self._financial_snapshot(ticker), accounts)

    @staticmethod
    def _first_account(snapshot: dict[str, float], accounts: tuple[str, ...]) -> float | None:
        """Return the first present account value from a snapshot.

        Args:
            snapshot: Account values for the latest yearly statement.
            accounts: Account names to try, in priority order.

        Returns:
            The value, or None.
        """
        for account in accounts:
            value = snapshot.get(account)
            if value is not None:
                return value
        return None

    def _latest_close(self, ticker: str) -> Decimal | None:
        """Get the most recent closing price.

        Args:
            ticker: Stock symbol

        Returns:
            Closing price, or None when the ticker has no price history.
        """
        row = (
            self.session.query(GlobalPrice.Close)
            .filter(GlobalPrice.ticker == ticker)
            .order_by(GlobalPrice.Date.desc())
            .first()
        )

        return row[0] if row and row[0] else None

    def check_dividend_trend(self, ticker: str, years: int = 5) -> bool:
        """Check if dividends are in increasing trend using linear regression.

        Uses linear regression to determine overall dividend growth trend.
        More robust than simple counting as it considers statistical significance.

        The current calendar year is excluded: it is still in progress, so its
        partial total sits far below a full year and drags the regression slope
        negative for virtually every dividend payer.

        Args:
            ticker: Stock symbol
            years: Number of complete years to check

        Returns:
            True if dividends show statistically significant increasing trend
        """
        current_year = date.today().year

        # Get annual dividends for the last N *complete* years
        dividends = (
            self.session.query(
                func.year(GlobalDividend.ex_dividend_date).label("year"),
                func.sum(GlobalDividend.cash_amount).label("total"),
            )
            .filter(
                and_(
                    GlobalDividend.ticker == ticker,
                    func.year(GlobalDividend.ex_dividend_date) < current_year,
                )
            )
            .group_by(func.year(GlobalDividend.ex_dividend_date))
            .order_by(func.year(GlobalDividend.ex_dividend_date).desc())
            .limit(years)
            .all()
        )

        if len(dividends) < 2:
            return False

        # Values in chronological order (oldest to newest)
        values = [float(d.total) for d in reversed(dividends)]

        # Use linear regression to check for positive trend
        return self._is_increasing_trend(values, min_r_squared=0.3)

    def _check_account_trend(self, ticker: str, account: str, years: int) -> bool:
        """Check whether a yearly financial account trends upward.

        Args:
            ticker: Stock symbol
            account: Account name in ``global_fs``
            years: Number of years to check

        Returns:
            True if the account shows a statistically significant upward trend
        """
        rows = (
            self.session.query(GlobalFinancialStatement.date, GlobalFinancialStatement.value)
            .filter(
                and_(
                    GlobalFinancialStatement.ticker == ticker,
                    GlobalFinancialStatement.account == account,
                    GlobalFinancialStatement.freq == "y",
                )
            )
            .order_by(GlobalFinancialStatement.date.desc())
            .limit(years)
            .all()
        )

        if len(rows) < 2:
            return False

        # Values in chronological order (oldest to newest)
        values = [float(r.value) for r in reversed(rows)]

        return self._is_increasing_trend(values, min_r_squared=0.3)

    def check_revenue_trend(self, ticker: str, years: int = 3) -> bool:
        """Check if revenue is in increasing trend using linear regression.

        Args:
            ticker: Stock symbol
            years: Number of years to check

        Returns:
            True if revenue shows statistically significant increasing trend
        """
        return self._check_account_trend(ticker, "Total Revenue", years)

    def check_operating_income_trend(self, ticker: str, years: int = 3) -> bool:
        """Check if operating income is in increasing trend using linear regression.

        Args:
            ticker: Stock symbol
            years: Number of years to check

        Returns:
            True if operating income shows statistically significant increasing trend
        """
        return self._check_account_trend(ticker, "Operating Income", years)

    def count_dividend_years(self, ticker: str) -> int:
        """Count consecutive years of dividend payments.

        Args:
            ticker: Stock symbol

        Returns:
            Number of consecutive years
        """
        years_with_dividends = (
            self.session.query(func.year(GlobalDividend.ex_dividend_date).distinct())
            .filter(GlobalDividend.ticker == ticker)
            .order_by(func.year(GlobalDividend.ex_dividend_date).desc())
            .all()
        )

        if not years_with_dividends:
            return 0

        # Check for consecutive years
        years = sorted([y[0] for y in years_with_dividends], reverse=True)
        consecutive = 1

        for i in range(len(years) - 1):
            if years[i] - years[i + 1] == 1:
                consecutive += 1
            else:
                break

        return consecutive

    def calculate_all_metrics(self, ticker: str, use_cache: bool = False) -> dict[str, Any]:
        """Calculate all metrics for a stock.

        Args:
            ticker: Stock symbol
            use_cache: Whether to try cache first

        Returns:
            Dictionary with all metrics
        """
        if use_cache:
            return self.get_or_calculate_metrics(ticker, use_cache=True)

        return {
            "ticker": ticker,
            "dividend_yield": self.calculate_dividend_yield(ticker),
            "market_cap": self.calculate_market_cap(ticker),
            "per": self.calculate_per(ticker),
            "pbr": self.calculate_pbr(ticker),
            "psr": self.calculate_psr(ticker),
            "roe": self.calculate_roe(ticker),
            "operating_margin": self.calculate_operating_margin(ticker),
            "debt_ratio": self.calculate_debt_ratio(ticker),
            "quick_ratio": self.calculate_quick_ratio(ticker),
            "interest_coverage_ratio": self.calculate_interest_coverage_ratio(ticker),
            "has_interest_expense": self.has_interest_expense(ticker),
            "dividend_increasing": self.check_dividend_trend(ticker),
            "revenue_increasing": self.check_revenue_trend(ticker),
            "operating_income_increasing": self.check_operating_income_trend(ticker),
            "years_of_dividend": self.count_dividend_years(ticker),
        }

    def save_metrics(self, ticker: str, metrics: dict[str, Any]) -> None:
        """Save calculated metrics to database.

        Args:
            ticker: Stock symbol
            metrics: Calculated metrics dictionary from calculate_all_metrics()
        """
        current_date = date.today()

        rows = [
            {
                "ticker": ticker,
                "date": current_date,
                "indicator": indicator,
                "value": metrics[metric_key],
            }
            for indicator, metric_key in _INDICATOR_TO_METRIC.items()
            if metrics.get(metric_key) is not None
        ]

        if rows:
            # Upsert rather than delete-then-insert: the uq_value_ticker_date_ind
            # constraint would turn two concurrent runs of the same ticker into
            # an IntegrityError, and this needs no read first.
            stmt = mysql_insert(GlobalValue.__table__).values(rows)
            stmt = stmt.on_duplicate_key_update(value=stmt.inserted.value)
            self.session.execute(stmt)

        # Drop indicators that no longer compute, so a stale value from an
        # earlier run today is not mistaken for a current one.
        stale = set(CACHED_INDICATORS) - {row["indicator"] for row in rows}
        if stale:
            self.session.query(GlobalValue).filter(
                and_(
                    GlobalValue.ticker == ticker,
                    GlobalValue.date == current_date,
                    GlobalValue.indicator.in_(stale),
                )
            ).delete(synchronize_session=False)

        self.session.commit()

    def get_cached_metrics(self, ticker: str, max_age_days: int = 1) -> dict[str, Any] | None:
        """Get cached metrics from database.

        A ticker legitimately has no value for some indicators (a debt-free
        company reports no interest coverage), so a cache entry is considered
        usable when any indicator was stored for the ticker within the window.

        Args:
            ticker: Stock symbol
            max_age_days: Maximum age of cached metrics in days

        Returns:
            Dictionary with cached metrics or None if not found or too old
        """
        cutoff_date = date.today() - timedelta(days=max_age_days)

        cached = (
            self.session.query(GlobalValue)
            .filter(
                and_(
                    GlobalValue.ticker == ticker,
                    GlobalValue.date >= cutoff_date,
                    GlobalValue.indicator.in_(CACHED_INDICATORS),
                )
            )
            .order_by(GlobalValue.date.desc())
            .all()
        )

        if not cached:
            return None

        metrics: dict[str, Any] = {"ticker": ticker}
        for metric_key in _INDICATOR_TO_METRIC.values():
            metrics[metric_key] = None

        for record in cached:
            metric_key = _INDICATOR_TO_METRIC.get(record.indicator)
            if metric_key and metrics.get(metric_key) is None:
                metrics[metric_key] = float(record.value) if record.value is not None else None

        return metrics

    def get_or_calculate_metrics(
        self,
        ticker: str,
        use_cache: bool = True,
        cache_max_age_days: int = 1,
    ) -> dict[str, Any]:
        """Get metrics from cache or calculate if not available.

        Args:
            ticker: Stock symbol
            use_cache: Whether to use cached metrics
            cache_max_age_days: Maximum age of cached metrics in days

        Returns:
            Dictionary with all metrics
        """
        if use_cache:
            cached = self.get_cached_metrics(ticker, cache_max_age_days)
            if cached:
                # Trend indicators are booleans and counts, not stored in
                # global_value, so they are always recomputed.
                cached["has_interest_expense"] = self.has_interest_expense(ticker)
                cached["dividend_increasing"] = self.check_dividend_trend(ticker)
                cached["revenue_increasing"] = self.check_revenue_trend(ticker)
                cached["operating_income_increasing"] = self.check_operating_income_trend(ticker)
                cached["years_of_dividend"] = self.count_dividend_years(ticker)
                return cached

        metrics = self.calculate_all_metrics(ticker)

        if use_cache:
            self.save_metrics(ticker, metrics)

        return metrics

    def _get_financial_value(
        self, ticker: str, account: str, date: date
    ) -> float | None:
        """Get financial statement value.

        Args:
            ticker: Stock symbol
            account: Account name
            date: Date

        Returns:
            Account value or None
        """
        result = (
            self.session.query(GlobalFinancialStatement.value)
            .filter(
                and_(
                    GlobalFinancialStatement.ticker == ticker,
                    GlobalFinancialStatement.account == account,
                    GlobalFinancialStatement.date == date,
                    GlobalFinancialStatement.freq == "y",
                )
            )
            .first()
        )

        return float(result[0]) if result else None
