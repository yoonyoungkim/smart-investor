"""Stock filtering criteria based on fundamental analysis.

Every criterion takes its threshold as a constructor argument so a run can
tighten or loosen it without code changes. Class-level constants remain the
defaults, which keeps ``DividendYieldFilter()`` behaving as before.
"""

from typing import Protocol, runtime_checkable

from ..models.stock import FinancialMetrics


@runtime_checkable
class FilterCriterion(Protocol):
    """Protocol for stock filtering criteria."""

    def check(self, metrics: FinancialMetrics) -> tuple[bool, str]:
        """Check if stock passes this criterion.

        Args:
            metrics: Financial metrics for the stock

        Returns:
            Tuple of (passed: bool, reason: str)
        """
        ...

    def describe(self) -> str:
        """Return a human-readable description of the active threshold."""
        ...


class DividendYieldFilter:
    """Filter 1: Dividend yield must be >= a minimum percentage."""

    MIN_DIVIDEND_YIELD = 4.0

    def __init__(self, min_dividend_yield: float | None = None) -> None:
        """Initialize the filter.

        Args:
            min_dividend_yield: Minimum yield in percent. Defaults to 4.0.
        """
        self.min_dividend_yield = (
            self.MIN_DIVIDEND_YIELD if min_dividend_yield is None else min_dividend_yield
        )

    def check(self, metrics: FinancialMetrics) -> tuple[bool, str]:
        """Check dividend yield criterion."""
        if metrics.dividend_yield is None:
            return False, "No dividend yield data"

        if metrics.dividend_yield < self.min_dividend_yield:
            return (
                False,
                f"Dividend yield {metrics.dividend_yield:.2f}% < {self.min_dividend_yield}%",
            )

        return True, "Passed"

    def describe(self) -> str:
        """Describe the active threshold."""
        return f"배당수익률 >= {self.min_dividend_yield}%"


class ConsecutiveDividendFilter:
    """Filter 2: Must have paid dividends for a minimum number of years."""

    MIN_YEARS = 5

    def __init__(self, min_years: int | None = None) -> None:
        """Initialize the filter.

        Args:
            min_years: Minimum consecutive dividend years. Defaults to 5.
        """
        self.min_years = self.MIN_YEARS if min_years is None else min_years

    def check(self, metrics: FinancialMetrics) -> tuple[bool, str]:
        """Check consecutive dividend payment criterion."""
        if metrics.years_of_dividend < self.min_years:
            return (
                False,
                f"Only {metrics.years_of_dividend} years of dividends < {self.min_years} years",
            )

        return True, "Passed"

    def describe(self) -> str:
        """Describe the active threshold."""
        return f"연속 배당 >= {self.min_years}년"


class DividendGrowthFilter:
    """Filter 3: Dividend must show increasing trend."""

    def check(self, metrics: FinancialMetrics) -> tuple[bool, str]:
        """Check dividend growth criterion."""
        if not metrics.dividend_increasing:
            return False, "Dividend not in increasing trend"

        return True, "Passed"

    def describe(self) -> str:
        """Describe the criterion."""
        return "배당 성장 추세 (R² >= 0.3)"


class OperatingIncomeGrowthFilter:
    """Filter 4: Operating income must show increasing trend."""

    def check(self, metrics: FinancialMetrics) -> tuple[bool, str]:
        """Check operating income growth criterion."""
        if not metrics.operating_income_increasing:
            return False, "Operating income not in increasing trend"

        return True, "Passed"

    def describe(self) -> str:
        """Describe the criterion."""
        return "영업이익 성장 추세 (R² >= 0.3)"


class RevenueGrowthFilter:
    """Filter 5: Revenue must show increasing trend."""

    def check(self, metrics: FinancialMetrics) -> tuple[bool, str]:
        """Check revenue growth criterion."""
        if not metrics.revenue_increasing:
            return False, "Revenue not in increasing trend"

        return True, "Passed"

    def describe(self) -> str:
        """Describe the criterion."""
        return "매출 성장 추세 (R² >= 0.3)"


class DebtRatioFilter:
    """Filter 6: Debt ratio must be <= a maximum percentage."""

    MAX_DEBT_RATIO = 200.0

    def __init__(self, max_debt_ratio: float | None = None) -> None:
        """Initialize the filter.

        Args:
            max_debt_ratio: Maximum debt ratio in percent. Defaults to 200.0.
        """
        self.max_debt_ratio = (
            self.MAX_DEBT_RATIO if max_debt_ratio is None else max_debt_ratio
        )

    def check(self, metrics: FinancialMetrics) -> tuple[bool, str]:
        """Check debt ratio criterion."""
        if metrics.debt_ratio is None:
            return False, "No debt ratio data"

        if metrics.debt_ratio > self.max_debt_ratio:
            return False, f"Debt ratio {metrics.debt_ratio:.2f}% > {self.max_debt_ratio}%"

        return True, "Passed"

    def describe(self) -> str:
        """Describe the active threshold."""
        return f"부채비율 <= {self.max_debt_ratio}%"


class QuickRatioFilter:
    """Filter 7: Quick ratio must be >= a minimum percentage."""

    MIN_QUICK_RATIO = 100.0

    def __init__(self, min_quick_ratio: float | None = None) -> None:
        """Initialize the filter.

        Args:
            min_quick_ratio: Minimum quick ratio in percent. Defaults to 100.0.
        """
        self.min_quick_ratio = (
            self.MIN_QUICK_RATIO if min_quick_ratio is None else min_quick_ratio
        )

    def check(self, metrics: FinancialMetrics) -> tuple[bool, str]:
        """Check quick ratio criterion."""
        if metrics.quick_ratio is None:
            return False, "No quick ratio data"

        if metrics.quick_ratio < self.min_quick_ratio:
            return False, f"Quick ratio {metrics.quick_ratio:.2f}% < {self.min_quick_ratio}%"

        return True, "Passed"

    def describe(self) -> str:
        """Describe the active threshold."""
        return f"당좌비율 >= {self.min_quick_ratio}%"


class InterestCoverageFilter:
    """Filter 8: Interest coverage ratio must be >= a minimum percentage.

    A company that reports no interest expense has no debt service to cover and
    passes. That case is distinguished from missing financials via
    ``FinancialMetrics.has_interest_expense`` rather than the sentinel value the
    calculator previously returned.
    """

    MIN_COVERAGE_RATIO = 100.0

    def __init__(self, min_coverage_ratio: float | None = None) -> None:
        """Initialize the filter.

        Args:
            min_coverage_ratio: Minimum coverage in percent. Defaults to 100.0.
        """
        self.min_coverage_ratio = (
            self.MIN_COVERAGE_RATIO if min_coverage_ratio is None else min_coverage_ratio
        )

    def check(self, metrics: FinancialMetrics) -> tuple[bool, str]:
        """Check interest coverage ratio criterion."""
        if metrics.interest_coverage_ratio is None:
            # False (not None) means financials were read and carried no
            # interest expense; None means there were no financials to read.
            if metrics.has_interest_expense is False:
                return True, "No interest expense"
            return False, "No interest coverage ratio data"

        if metrics.interest_coverage_ratio < self.min_coverage_ratio:
            return (
                False,
                f"Interest coverage {metrics.interest_coverage_ratio:.2f}% "
                f"< {self.min_coverage_ratio}%",
            )

        return True, "Passed"

    def describe(self) -> str:
        """Describe the active threshold."""
        return f"이자보상배율 >= {self.min_coverage_ratio}%"


class PERFilter:
    """Value filter: price/earnings ratio must be <= a maximum.

    A loss-making company has no PER at all, which fails rather than passes -
    absence of a ratio is not evidence of cheapness.
    """

    MAX_PER = 15.0

    def __init__(self, max_per: float | None = None) -> None:
        """Initialize the filter.

        Args:
            max_per: Maximum price/earnings ratio. Defaults to 15.0 (Graham).
        """
        self.max_per = self.MAX_PER if max_per is None else max_per

    def check(self, metrics: FinancialMetrics) -> tuple[bool, str]:
        """Check the PER criterion."""
        if metrics.per is None:
            return False, "No PER data"

        if metrics.per > self.max_per:
            return False, f"PER {metrics.per:.2f} > {self.max_per}"

        return True, "Passed"

    def describe(self) -> str:
        """Describe the active threshold."""
        return f"PER <= {self.max_per}"


class PBRFilter:
    """Value filter: price/book ratio must be <= a maximum."""

    MAX_PBR = 1.5

    def __init__(self, max_pbr: float | None = None) -> None:
        """Initialize the filter.

        Args:
            max_pbr: Maximum price/book ratio. Defaults to 1.5 (Graham).
        """
        self.max_pbr = self.MAX_PBR if max_pbr is None else max_pbr

    def check(self, metrics: FinancialMetrics) -> tuple[bool, str]:
        """Check the PBR criterion."""
        if metrics.pbr is None:
            return False, "No PBR data"

        if metrics.pbr > self.max_pbr:
            return False, f"PBR {metrics.pbr:.2f} > {self.max_pbr}"

        return True, "Passed"

    def describe(self) -> str:
        """Describe the active threshold."""
        return f"PBR <= {self.max_pbr}"


class GrahamNumberFilter:
    """Value filter: PER x PBR must be <= a maximum.

    Graham's combined test, which lets a low ratio on one side offset a higher
    one on the other - something the separate PER and PBR limits cannot do.
    """

    MAX_PRODUCT = 22.5

    def __init__(self, max_product: float | None = None) -> None:
        """Initialize the filter.

        Args:
            max_product: Maximum PER x PBR. Defaults to 22.5 (Graham).
        """
        self.max_product = self.MAX_PRODUCT if max_product is None else max_product

    def check(self, metrics: FinancialMetrics) -> tuple[bool, str]:
        """Check the combined valuation criterion."""
        if metrics.per is None or metrics.pbr is None:
            return False, "No PER/PBR data"

        product = metrics.per * metrics.pbr
        if product > self.max_product:
            return False, f"PER x PBR {product:.2f} > {self.max_product}"

        return True, "Passed"

    def describe(self) -> str:
        """Describe the active threshold."""
        return f"PER x PBR <= {self.max_product}"


class ROEFilter:
    """Value filter: return on equity must be >= a minimum."""

    MIN_ROE = 10.0

    def __init__(self, min_roe: float | None = None) -> None:
        """Initialize the filter.

        Args:
            min_roe: Minimum return on equity in percent. Defaults to 10.0.
        """
        self.min_roe = self.MIN_ROE if min_roe is None else min_roe

    def check(self, metrics: FinancialMetrics) -> tuple[bool, str]:
        """Check the ROE criterion."""
        if metrics.roe is None:
            return False, "No ROE data"

        if metrics.roe < self.min_roe:
            return False, f"ROE {metrics.roe:.2f}% < {self.min_roe}%"

        return True, "Passed"

    def describe(self) -> str:
        """Describe the active threshold."""
        return f"ROE >= {self.min_roe}%"


class OperatingMarginFilter:
    """Value filter: operating margin must be >= a minimum."""

    MIN_OPERATING_MARGIN = 5.0

    def __init__(self, min_operating_margin: float | None = None) -> None:
        """Initialize the filter.

        Args:
            min_operating_margin: Minimum operating margin in percent.
                Defaults to 5.0.
        """
        self.min_operating_margin = (
            self.MIN_OPERATING_MARGIN
            if min_operating_margin is None
            else min_operating_margin
        )

    def check(self, metrics: FinancialMetrics) -> tuple[bool, str]:
        """Check the operating margin criterion."""
        if metrics.operating_margin is None:
            return False, "No operating margin data"

        if metrics.operating_margin < self.min_operating_margin:
            return (
                False,
                f"Operating margin {metrics.operating_margin:.2f}% "
                f"< {self.min_operating_margin}%",
            )

        return True, "Passed"

    def describe(self) -> str:
        """Describe the active threshold."""
        return f"영업이익률 >= {self.min_operating_margin}%"
