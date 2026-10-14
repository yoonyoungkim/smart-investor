"""Stock filtering module."""

from .config import FilterConfig
from .criteria import (
    ConsecutiveDividendFilter,
    DebtRatioFilter,
    DividendGrowthFilter,
    DividendYieldFilter,
    FilterCriterion,
    InterestCoverageFilter,
    OperatingIncomeGrowthFilter,
    QuickRatioFilter,
    RevenueGrowthFilter,
)
from .engine import StockFilterEngine
from .registry import FilterSpec, UnknownFilterError, register, unregister

__all__ = [
    "FilterConfig",
    "FilterSpec",
    "UnknownFilterError",
    "register",
    "unregister",
    "FilterCriterion",
    "DividendYieldFilter",
    "ConsecutiveDividendFilter",
    "DividendGrowthFilter",
    "OperatingIncomeGrowthFilter",
    "RevenueGrowthFilter",
    "DebtRatioFilter",
    "QuickRatioFilter",
    "InterestCoverageFilter",
    "StockFilterEngine",
]
