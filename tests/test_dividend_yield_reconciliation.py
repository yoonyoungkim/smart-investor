"""Tests for putting filed dividends on the same share basis as stored prices.

``global_price`` holds split-adjusted closes; ``global_dividends`` holds the
per-share amounts exactly as filed with DART, on the share count at filing time.
After a split the two disagree by the split ratio, so the ratio is measured from
DART's own disclosed yield and snapped to a real split ratio before dividing.
"""

from decimal import Decimal

import pytest

from smart_investor.analysis.calculator import (
    DISCLOSED_YIELD_INDICATOR,
    PLAUSIBLE_SPLIT_RATIOS,
    SPLIT_TOLERANCE,
    MetricsCalculator,
    _median,
    _snap_to_split_ratio,
)


def snap(value):
    """Snap a measured basis difference onto a split ratio."""
    return _snap_to_split_ratio(Decimal(str(value)))


class TestSnapToSplitRatio:
    """A measurement only becomes an adjustment if it looks like a real split."""

    def test_ten_to_one_with_noise(self):
        """미원화학 measured 9.85-10.20 across five years."""
        for measured in (9.85, 9.94, 10.09, 10.16, 10.20, 10.53):
            assert snap(measured) == Decimal("10")

    def test_five_to_one(self):
        assert snap(5.01) == Decimal("5")

    def test_two_to_one(self):
        assert snap(2.03) == Decimal("2")

    def test_low_reading_of_a_five_to_one_still_snaps(self):
        """4.0 is a 20%-low reading of 5:1, which the tolerance is there to absorb."""
        assert snap(4.0) == Decimal("5")

    def test_three_times_is_unresolved(self):
        """3.0 sits between the 2x and 5x bands - no ladder ratio explains it."""
        assert snap(3.0) is None

    def test_no_split_snaps_to_one(self):
        """시공테크 measured 0.93-1.19 with no split."""
        for measured in (0.93, 0.95, 1.02, 1.04, 1.10, 1.19):
            assert snap(measured) == Decimal("1")

    def test_sub_one_readings_are_not_ratios(self):
        """Readings below 1 came from par-based yield disclosures, not splits."""
        for measured in (0.2, 0.1, 0.05):
            assert snap(measured) is None

    @pytest.mark.parametrize("ratio", PLAUSIBLE_SPLIT_RATIOS)
    def test_every_plausible_ratio_snaps_to_itself(self, ratio):
        assert snap(ratio) == Decimal(str(ratio))

    def test_unmatched_measurement_is_rejected(self):
        """3.4x is neither a clean split nor "no split" - do not invent a fix."""
        assert snap(3.4) is None

    def test_seven_times_is_rejected(self):
        assert snap(7.0) is None

    def test_between_no_split_and_two_is_rejected(self):
        """A big real price move can reach 1.4x; never call that a split."""
        assert snap(1.4) is None

    def test_one_point_five_is_rejected(self):
        """Halfway between no-split and 2:1; forcing either would be a guess."""
        assert snap(1.5) is None

    def test_zero_and_negative_rejected(self):
        assert snap(0) is None
        assert snap(-2) is None

    def test_tolerance_boundary_accepted(self):
        assert snap(10 * (1 + SPLIT_TOLERANCE)) == Decimal("10")

    def test_just_outside_tolerance_rejected(self):
        """12.1x lies between the 10x and 20x bands."""
        assert snap(10 * (1 + SPLIT_TOLERANCE) + 0.1) is None


class TestMedian:
    """The median keeps one bad year from moving the factor."""

    def test_odd_count(self):
        assert _median([Decimal("1"), Decimal("10"), Decimal("2")]) == Decimal("2")

    def test_even_count(self):
        assert _median([Decimal("2"), Decimal("4")]) == Decimal("3")

    def test_single_value(self):
        assert _median([Decimal("10.2")]) == Decimal("10.2")

    def test_outlier_year_ignored(self):
        """Four consistent years outvote one bad measurement."""
        values = [Decimal(v) for v in ("10.1", "9.9", "10.2", "10.0", "99")]
        assert _median(values) == Decimal("10.1")


class StubCalculator(MetricsCalculator):
    """Calculator with the per-year measurements supplied directly."""

    def __init__(self, measurements):
        super().__init__(session=None)
        self._measurements = [Decimal(str(m)) for m in measurements]

    def _measure_split_factors(self, ticker: str):
        return self._measurements


class TestSplitFactor:
    """The factor combines measurement, consistency, median and snapping."""

    def test_single_noisy_year_is_not_a_split(self):
        """One year at 2.1x is ordinary price movement, not evidence."""
        assert StubCalculator([2.1]).dividend_split_factor("X") == Decimal("1")

    def test_single_decisive_year_is_accepted(self):
        """미원화학 had only 2025 prices stored; 10.2x needs no corroboration."""
        assert StubCalculator([10.2]).dividend_split_factor("X") == Decimal("10")

    def test_agreeing_years_detect_a_two_to_one_split(self):
        """Consistency is what separates 2:1 from a halved price."""
        assert StubCalculator([2.02, 1.98, 2.05]).dividend_split_factor("X") == Decimal("2")

    def test_scattered_years_are_price_movement(self):
        """The same median, but the years disagree - do not adjust."""
        assert StubCalculator([0.9, 1.4, 2.0, 3.2]).dividend_split_factor("X") == Decimal("1")

    def test_sub_one_measurement_never_multiplies_the_dividend(self):
        """흥국 measured 0.09x from a par-based disclosure; adjusting would
        have turned a 280원 dividend into 3,111원 and a 50% yield."""
        assert StubCalculator([0.09, 0.09]).dividend_split_factor("X") == Decimal("1")

    def test_no_measurements_means_no_adjustment(self):
        """US tickers have no disclosed yield, so nothing to measure."""
        assert StubCalculator([]).dividend_split_factor("KO") == Decimal("1")

    def test_consistent_split_detected(self):
        factor = StubCalculator([9.85, 9.94, 10.09, 10.16, 10.20]).dividend_split_factor("X")
        assert factor == Decimal("10")

    def test_unsplit_ticker_returns_one(self):
        factor = StubCalculator([0.95, 1.02, 1.04, 1.19]).dividend_split_factor("X")
        assert factor == Decimal("1")

    def test_unresolvable_measurement_leaves_dividend_alone(self):
        """Better an overstated yield than a fabricated correction."""
        assert StubCalculator([7.0, 7.1, 7.05]).dividend_split_factor("X") == Decimal("1")

    def test_unresolvable_measurement_warns(self, caplog):
        with caplog.at_level("WARNING"):
            StubCalculator([7.0, 7.1]).dividend_split_factor("X")

        assert "no plausible split ratio" in caplog.text

    def test_adjustment_is_logged(self, caplog):
        with caplog.at_level("INFO"):
            StubCalculator([10.2, 10.1]).dividend_split_factor("X")

        assert "pre-split" in caplog.text
        assert "10x" in caplog.text

    def test_no_adjustment_is_not_logged(self, caplog):
        with caplog.at_level("INFO"):
            StubCalculator([1.02]).dividend_split_factor("X")

        assert caplog.text == ""


class TestConstants:
    """Cross-module agreement."""

    def test_indicator_name_matches_collector(self):
        from smart_investor.collectors.kr import dividend as kr_dividend

        assert DISCLOSED_YIELD_INDICATOR == kr_dividend.DISCLOSED_YIELD_INDICATOR

    def test_tolerance_separates_adjacent_ratios(self):
        """Tolerance bands around neighbouring ratios must not overlap."""
        ratios = sorted(Decimal(str(r)) for r in PLAUSIBLE_SPLIT_RATIOS)
        tolerance = Decimal(str(SPLIT_TOLERANCE))

        for lower, upper in zip(ratios, ratios[1:], strict=False):
            assert lower * (1 + tolerance) < upper * (1 - tolerance), (
                f"{lower} and {upper} tolerance bands overlap"
            )


class TestCurrencyGuard:
    """Valuation ratios refuse to mix currencies.

    US-listed foreign issuers trade in USD but file in their home currency, so
    a USD market cap over a KRW net income yields a PER near 0.01 - which then
    sorts to the top of a value screen.
    """

    class _StubSession:
        def __init__(self, row):
            self._row = row

        def query(self, *args):
            return self

        def filter(self, *args):
            return self

        def first(self):
            return self._row

    def _calculator(self, row):
        from smart_investor.analysis.calculator import MetricsCalculator

        return MetricsCalculator(session=self._StubSession(row))

    def test_matching_us_currency_allowed(self):
        assert self._calculator(("USD", "United States")).currencies_match("KIM") is True

    def test_matching_kr_currency_allowed(self):
        assert self._calculator(("KRW", "South Korea")).currencies_match("005930") is True

    def test_adr_filing_in_home_currency_blocked(self):
        """GRVY files in KRW and trades in USD; its raw PER read 0.01."""
        assert self._calculator(("KRW", "United States")).currencies_match("GRVY") is False

    def test_other_foreign_filings_blocked(self):
        for currency in ("ARS", "CNY", "EUR"):
            assert self._calculator((currency, "United States")).currencies_match("X") is False

    def test_case_insensitive(self):
        assert self._calculator(("usd", "United States")).currencies_match("X") is True

    def test_unknown_currency_is_permissive(self):
        """Withholding every ratio until the market is fully looked up is worse."""
        assert self._calculator((None, "United States")).currencies_match("X") is True

    def test_missing_ticker_is_permissive(self):
        assert self._calculator(None).currencies_match("X") is True
