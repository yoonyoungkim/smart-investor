"""Stock data models with Korean market support."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Market(Enum):
    """Stock market identifier."""

    US = "US"  # United States (NYSE, NASDAQ, AMEX)
    KR = "KR"  # Korea (KOSPI, KOSDAQ)


@dataclass
class Stock:
    """Basic stock information with market support."""

    symbol: str
    name: str
    exchange: str
    sector: str
    market_cap: float
    market: Market = Market.US
    country: str = "United States"

    def __post_init__(self) -> None:
        """Set country based on market if not provided."""
        if self.market == Market.KR and self.country == "United States":
            self.country = "South Korea"


@dataclass
class FinancialMetrics:
    """Financial metrics for stock analysis with market support."""

    ticker: str
    market: Market = Market.US
    dividend_yield: Optional[float] = None
    debt_ratio: Optional[float] = None
    quick_ratio: Optional[float] = None
    interest_coverage_ratio: Optional[float] = None

    # Trend indicators
    dividend_increasing: bool = False
    operating_income_increasing: bool = False
    revenue_increasing: bool = False

    # Three-state on purpose: True = interest expense reported, False =
    # financials present but no interest expense (nothing to cover, a pass),
    # None = no financials at all (coverage unknown, a fail).
    has_interest_expense: Optional[bool] = None

    # Additional info
    years_of_dividend: int = 0
    latest_close_price: Optional[float] = None

    # Valuation metrics, used by the value-stock criteria
    per: Optional[float] = None  # Price to Earnings Ratio
    pbr: Optional[float] = None  # Price to Book Ratio
    psr: Optional[float] = None  # Price to Sales Ratio
    roe: Optional[float] = None  # Return on Equity (%)
    operating_margin: Optional[float] = None  # Operating income / revenue (%)
    # In the listing currency: USD for US tickers, KRW for Korean ones.
    market_cap: Optional[float] = None

    eps: Optional[float] = None  # Earnings Per Share
    bps: Optional[float] = None  # Book Value Per Share


@dataclass
class FilterResult:
    """Result of stock filtering."""

    ticker: str
    passed: bool
    failed_criteria: list[str] = field(default_factory=list)
    metrics: Optional[FinancialMetrics] = None
    market: Market = Market.US
