"""Tests for data models."""

import pytest
from smart_investor.models.stock import Stock, FinancialMetrics, FilterResult, Market


class TestStock:
    """Tests for Stock model."""

    def test_us_stock_creation(self):
        """Test creating a US stock."""
        stock = Stock(
            symbol="AAPL",
            name="Apple Inc.",
            exchange="NASDAQ",
            sector="Technology",
            market_cap=3000000000000,
            market=Market.US,
        )
        assert stock.symbol == "AAPL"
        assert stock.market == Market.US
        assert stock.country == "United States"

    def test_kr_stock_creation(self):
        """Test creating a Korean stock."""
        stock = Stock(
            symbol="005930",
            name="삼성전자",
            exchange="KOSPI",
            sector="Technology",
            market_cap=500000000000000,
            market=Market.KR,
        )
        assert stock.symbol == "005930"
        assert stock.market == Market.KR
        assert stock.country == "South Korea"

    def test_kr_stock_country_auto_set(self):
        """Test that country is auto-set for Korean stocks."""
        stock = Stock(
            symbol="005930",
            name="삼성전자",
            exchange="KOSPI",
            sector="Technology",
            market_cap=500000000000000,
            market=Market.KR,
        )
        assert stock.country == "South Korea"


class TestFinancialMetrics:
    """Tests for FinancialMetrics model."""

    def test_default_values(self):
        """Test default values are set correctly."""
        metrics = FinancialMetrics(ticker="TEST")
        assert metrics.ticker == "TEST"
        assert metrics.market == Market.US
        assert metrics.dividend_yield is None
        assert metrics.dividend_increasing is False
        assert metrics.years_of_dividend == 0

    def test_all_fields(self):
        """Test setting all fields."""
        metrics = FinancialMetrics(
            ticker="TEST",
            market=Market.KR,
            dividend_yield=5.0,
            debt_ratio=100.0,
            quick_ratio=150.0,
            interest_coverage_ratio=200.0,
            dividend_increasing=True,
            operating_income_increasing=True,
            revenue_increasing=True,
            years_of_dividend=10,
            latest_close_price=100.0,
            per=15.0,
            pbr=1.5,
            eps=5000,
            bps=50000,
        )
        assert metrics.ticker == "TEST"
        assert metrics.market == Market.KR
        assert metrics.dividend_yield == 5.0
        assert metrics.per == 15.0


class TestFilterResult:
    """Tests for FilterResult model."""

    def test_passed_result(self):
        """Test creating a passed result."""
        result = FilterResult(
            ticker="TEST",
            passed=True,
            failed_criteria=[],
        )
        assert result.passed is True
        assert len(result.failed_criteria) == 0

    def test_failed_result(self):
        """Test creating a failed result."""
        result = FilterResult(
            ticker="TEST",
            passed=False,
            failed_criteria=["Dividend Yield: Too low", "Quick Ratio: Too low"],
        )
        assert result.passed is False
        assert len(result.failed_criteria) == 2

    def test_with_metrics(self):
        """Test result with attached metrics."""
        metrics = FinancialMetrics(ticker="TEST", dividend_yield=5.0)
        result = FilterResult(
            ticker="TEST",
            passed=True,
            failed_criteria=[],
            metrics=metrics,
        )
        assert result.metrics is not None
        assert result.metrics.dividend_yield == 5.0


class TestMarket:
    """Tests for Market enum."""

    def test_us_market(self):
        """Test US market value."""
        assert Market.US.value == "US"

    def test_kr_market(self):
        """Test KR market value."""
        assert Market.KR.value == "KR"
