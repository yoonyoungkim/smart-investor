"""Registry of recommendation criteria.

The engine used to hard-code its eight criteria, so choosing a different set
meant editing code. Criteria are registered here under a stable key instead, and
a run selects which keys to apply and what thresholds to use. New criteria plug
in via :func:`register` without touching the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .criteria import (
    ConsecutiveDividendFilter,
    DebtRatioFilter,
    DividendGrowthFilter,
    DividendYieldFilter,
    FilterCriterion,
    GrahamNumberFilter,
    InterestCoverageFilter,
    OperatingIncomeGrowthFilter,
    OperatingMarginFilter,
    PBRFilter,
    PERFilter,
    QuickRatioFilter,
    RevenueGrowthFilter,
    ROEFilter,
)


class UnknownFilterError(KeyError):
    """Raised when a configuration references a criterion key that is not registered."""


@dataclass(frozen=True)
class FilterSpec:
    """Describes one registered criterion.

    Attributes:
        key: Stable identifier used in configuration and CLI flags.
        label: Human-readable name shown in reports and failure statistics.
        factory: Callable that builds the criterion from keyword parameters.
        params: Tunable parameter names mapped to their default values. An empty
            mapping means the criterion has no threshold to adjust.
        description: One-line summary of what the criterion checks.
        in_default: Whether an unconfigured run applies this criterion.
            Criteria from different strategies live in one registry, and
            requiring all of them at once passes almost nothing, so only the
            dividend set is on by default. The rest are opted into by preset,
            ``--enable`` or ``--strategy``.
    """

    key: str
    label: str
    factory: Callable[..., FilterCriterion]
    params: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    in_default: bool = True

    def build(self, overrides: dict[str, Any] | None = None) -> FilterCriterion:
        """Instantiate the criterion, applying parameter overrides.

        Args:
            overrides: Parameter values replacing the registered defaults.

        Returns:
            A ready-to-use criterion instance.

        Raises:
            TypeError: If an override names a parameter the criterion lacks.
        """
        if not overrides:
            return self.factory()

        unknown = set(overrides) - set(self.params)
        if unknown:
            raise TypeError(
                f"{self.key} has no parameter(s): {', '.join(sorted(unknown))}. "
                f"Available: {', '.join(sorted(self.params)) or 'none'}"
            )

        return self.factory(**overrides)


# Insertion order defines the order criteria are evaluated and reported.
_REGISTRY: dict[str, FilterSpec] = {}


def register(spec: FilterSpec, replace: bool = False) -> FilterSpec:
    """Add a criterion to the registry.

    Args:
        spec: The criterion specification.
        replace: Allow overwriting an existing key.

    Returns:
        The registered spec, so this can be used as a one-liner.

    Raises:
        ValueError: If the key is already registered and ``replace`` is False.
    """
    if spec.key in _REGISTRY and not replace:
        raise ValueError(f"Filter '{spec.key}' is already registered")

    _REGISTRY[spec.key] = spec
    return spec


def unregister(key: str) -> None:
    """Remove a criterion from the registry.

    Args:
        key: Criterion key to remove.

    Raises:
        UnknownFilterError: If the key is not registered.
    """
    if key not in _REGISTRY:
        raise UnknownFilterError(key)
    del _REGISTRY[key]


def get(key: str) -> FilterSpec:
    """Look up one registered criterion.

    Args:
        key: Criterion key.

    Returns:
        The registered spec.

    Raises:
        UnknownFilterError: If the key is not registered.
    """
    try:
        return _REGISTRY[key]
    except KeyError as exc:
        raise UnknownFilterError(
            f"Unknown filter '{key}'. Available: {', '.join(available_keys())}"
        ) from exc


def all_specs() -> list[FilterSpec]:
    """Return every registered criterion in evaluation order."""
    return list(_REGISTRY.values())


def available_keys() -> list[str]:
    """Return every registered criterion key in evaluation order."""
    return list(_REGISTRY)


def default_keys() -> list[str]:
    """Return the criterion keys an unconfigured run applies.

    Returns:
        Keys marked ``in_default``, in evaluation order.
    """
    return [key for key, spec in _REGISTRY.items() if spec.in_default]


def _register_defaults() -> None:
    """Register the eight criteria the project ships with."""
    register(FilterSpec(
        key="dividend_yield",
        label="Dividend Yield",
        factory=DividendYieldFilter,
        params={"min_dividend_yield": DividendYieldFilter.MIN_DIVIDEND_YIELD},
        description="최근 12개월 정기배당 기준 배당수익률 하한 (특별배당 제외)",
    ))
    register(FilterSpec(
        key="consecutive_dividends",
        label="Consecutive Dividends",
        factory=ConsecutiveDividendFilter,
        params={"min_years": ConsecutiveDividendFilter.MIN_YEARS},
        description="연속 배당 지급 연수 하한",
    ))
    register(FilterSpec(
        key="dividend_growth",
        label="Dividend Growth",
        factory=DividendGrowthFilter,
        description="배당금 선형회귀 상승 추세 (R² >= 0.3)",
    ))
    register(FilterSpec(
        key="operating_income_growth",
        label="Operating Income Growth",
        factory=OperatingIncomeGrowthFilter,
        description="영업이익 선형회귀 상승 추세 (R² >= 0.3)",
    ))
    register(FilterSpec(
        key="revenue_growth",
        label="Revenue Growth",
        factory=RevenueGrowthFilter,
        description="매출 선형회귀 상승 추세 (R² >= 0.3)",
    ))
    register(FilterSpec(
        key="debt_ratio",
        label="Debt Ratio",
        factory=DebtRatioFilter,
        params={"max_debt_ratio": DebtRatioFilter.MAX_DEBT_RATIO},
        description="총부채 / 총자산 상한",
    ))
    register(FilterSpec(
        key="quick_ratio",
        label="Quick Ratio",
        factory=QuickRatioFilter,
        params={"min_quick_ratio": QuickRatioFilter.MIN_QUICK_RATIO},
        description="(현금 + 매출채권) / 유동부채 하한",
    ))
    register(FilterSpec(
        key="interest_coverage",
        label="Interest Coverage",
        factory=InterestCoverageFilter,
        params={"min_coverage_ratio": InterestCoverageFilter.MIN_COVERAGE_RATIO},
        description="EBIT / 이자비용 하한",
    ))

    # Valuation criteria. Registered alongside the dividend ones rather than in
    # a separate registry: a run picks whichever keys it wants, so a strategy is
    # a selection rather than a different engine.
    register(FilterSpec(
        key="per",
        in_default=False,
        label="PER",
        factory=PERFilter,
        params={"max_per": PERFilter.MAX_PER},
        description="주가수익비율 상한 (시총 / 당기순이익)",
    ))
    register(FilterSpec(
        key="pbr",
        in_default=False,
        label="PBR",
        factory=PBRFilter,
        params={"max_pbr": PBRFilter.MAX_PBR},
        description="주가순자산비율 상한 (시총 / 자본총계)",
    ))
    register(FilterSpec(
        key="graham_number",
        in_default=False,
        label="Graham Number",
        factory=GrahamNumberFilter,
        params={"max_product": GrahamNumberFilter.MAX_PRODUCT},
        description="PER × PBR 상한 (그레이엄 복합 기준)",
    ))
    register(FilterSpec(
        key="roe",
        in_default=False,
        label="ROE",
        factory=ROEFilter,
        params={"min_roe": ROEFilter.MIN_ROE},
        description="자기자본이익률 하한",
    ))
    register(FilterSpec(
        key="operating_margin",
        in_default=False,
        label="Operating Margin",
        factory=OperatingMarginFilter,
        params={"min_operating_margin": OperatingMarginFilter.MIN_OPERATING_MARGIN},
        description="영업이익률 하한",
    ))


_register_defaults()
