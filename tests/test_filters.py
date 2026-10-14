"""Tests for stock filtering criteria and engine."""

import pytest
from smart_investor.models.stock import FinancialMetrics, Market
from smart_investor.filters.criteria import (
    DividendYieldFilter,
    ConsecutiveDividendFilter,
    DividendGrowthFilter,
    OperatingIncomeGrowthFilter,
    RevenueGrowthFilter,
    DebtRatioFilter,
    QuickRatioFilter,
    InterestCoverageFilter,
)
from smart_investor.filters.engine import StockFilterEngine


class TestDividendYieldFilter:
    """Tests for DividendYieldFilter."""

    def test_pass_high_yield(self):
        """Stock with high dividend yield should pass."""
        metrics = FinancialMetrics(ticker="TEST", dividend_yield=5.0)
        filter_obj = DividendYieldFilter()
        passed, reason = filter_obj.check(metrics)
        assert passed is True

    def test_fail_low_yield(self):
        """Stock with low dividend yield should fail."""
        metrics = FinancialMetrics(ticker="TEST", dividend_yield=3.0)
        filter_obj = DividendYieldFilter()
        passed, reason = filter_obj.check(metrics)
        assert passed is False
        assert "3.00%" in reason

    def test_fail_no_data(self):
        """Stock with no dividend yield data should fail."""
        metrics = FinancialMetrics(ticker="TEST", dividend_yield=None)
        filter_obj = DividendYieldFilter()
        passed, reason = filter_obj.check(metrics)
        assert passed is False
        assert "No dividend yield data" in reason

    def test_boundary_value(self):
        """Stock with exactly 4% yield should pass."""
        metrics = FinancialMetrics(ticker="TEST", dividend_yield=4.0)
        filter_obj = DividendYieldFilter()
        passed, reason = filter_obj.check(metrics)
        assert passed is True


class TestConsecutiveDividendFilter:
    """Tests for ConsecutiveDividendFilter."""

    def test_pass_many_years(self):
        """Stock with many years of dividends should pass."""
        metrics = FinancialMetrics(ticker="TEST", years_of_dividend=10)
        filter_obj = ConsecutiveDividendFilter()
        passed, reason = filter_obj.check(metrics)
        assert passed is True

    def test_fail_few_years(self):
        """Stock with few years of dividends should fail."""
        metrics = FinancialMetrics(ticker="TEST", years_of_dividend=3)
        filter_obj = ConsecutiveDividendFilter()
        passed, reason = filter_obj.check(metrics)
        assert passed is False

    def test_boundary_value(self):
        """Stock with exactly 5 years should pass."""
        metrics = FinancialMetrics(ticker="TEST", years_of_dividend=5)
        filter_obj = ConsecutiveDividendFilter()
        passed, reason = filter_obj.check(metrics)
        assert passed is True


class TestDividendGrowthFilter:
    """Tests for DividendGrowthFilter."""

    def test_pass_increasing(self):
        """Stock with increasing dividend should pass."""
        metrics = FinancialMetrics(ticker="TEST", dividend_increasing=True)
        filter_obj = DividendGrowthFilter()
        passed, reason = filter_obj.check(metrics)
        assert passed is True

    def test_fail_not_increasing(self):
        """Stock with non-increasing dividend should fail."""
        metrics = FinancialMetrics(ticker="TEST", dividend_increasing=False)
        filter_obj = DividendGrowthFilter()
        passed, reason = filter_obj.check(metrics)
        assert passed is False


class TestDebtRatioFilter:
    """Tests for DebtRatioFilter."""

    def test_pass_low_debt(self):
        """Stock with low debt ratio should pass."""
        metrics = FinancialMetrics(ticker="TEST", debt_ratio=100.0)
        filter_obj = DebtRatioFilter()
        passed, reason = filter_obj.check(metrics)
        assert passed is True

    def test_fail_high_debt(self):
        """Stock with high debt ratio should fail."""
        metrics = FinancialMetrics(ticker="TEST", debt_ratio=250.0)
        filter_obj = DebtRatioFilter()
        passed, reason = filter_obj.check(metrics)
        assert passed is False

    def test_boundary_value(self):
        """Stock with exactly 200% debt ratio should pass."""
        metrics = FinancialMetrics(ticker="TEST", debt_ratio=200.0)
        filter_obj = DebtRatioFilter()
        passed, reason = filter_obj.check(metrics)
        assert passed is True


class TestQuickRatioFilter:
    """Tests for QuickRatioFilter."""

    def test_pass_high_ratio(self):
        """Stock with high quick ratio should pass."""
        metrics = FinancialMetrics(ticker="TEST", quick_ratio=150.0)
        filter_obj = QuickRatioFilter()
        passed, reason = filter_obj.check(metrics)
        assert passed is True

    def test_fail_low_ratio(self):
        """Stock with low quick ratio should fail."""
        metrics = FinancialMetrics(ticker="TEST", quick_ratio=80.0)
        filter_obj = QuickRatioFilter()
        passed, reason = filter_obj.check(metrics)
        assert passed is False


class TestInterestCoverageFilter:
    """Tests for InterestCoverageFilter."""

    def test_pass_high_coverage(self):
        """Stock with high interest coverage should pass."""
        metrics = FinancialMetrics(ticker="TEST", interest_coverage_ratio=200.0)
        filter_obj = InterestCoverageFilter()
        passed, reason = filter_obj.check(metrics)
        assert passed is True

    def test_fail_low_coverage(self):
        """Stock with low interest coverage should fail."""
        metrics = FinancialMetrics(ticker="TEST", interest_coverage_ratio=50.0)
        filter_obj = InterestCoverageFilter()
        passed, reason = filter_obj.check(metrics)
        assert passed is False


class TestStockFilterEngine:
    """Tests for StockFilterEngine."""

    def test_pass_all_filters(self):
        """Stock meeting all criteria should pass."""
        metrics = FinancialMetrics(
            ticker="TEST",
            dividend_yield=5.0,
            years_of_dividend=10,
            dividend_increasing=True,
            operating_income_increasing=True,
            revenue_increasing=True,
            debt_ratio=100.0,
            quick_ratio=150.0,
            interest_coverage_ratio=200.0,
        )
        engine = StockFilterEngine()
        result = engine.filter_stock(metrics)

        assert result.passed is True
        assert len(result.failed_criteria) == 0

    def test_fail_one_filter(self):
        """Stock failing one criterion should fail overall."""
        metrics = FinancialMetrics(
            ticker="TEST",
            dividend_yield=2.0,  # Fails this one
            years_of_dividend=10,
            dividend_increasing=True,
            operating_income_increasing=True,
            revenue_increasing=True,
            debt_ratio=100.0,
            quick_ratio=150.0,
            interest_coverage_ratio=200.0,
        )
        engine = StockFilterEngine()
        result = engine.filter_stock(metrics)

        assert result.passed is False
        assert len(result.failed_criteria) == 1
        assert "Dividend Yield" in result.failed_criteria[0]

    def test_fail_multiple_filters(self):
        """Stock failing multiple criteria should list all failures."""
        metrics = FinancialMetrics(
            ticker="TEST",
            dividend_yield=2.0,  # Fails
            years_of_dividend=2,  # Fails
            dividend_increasing=False,  # Fails
            operating_income_increasing=True,
            revenue_increasing=True,
            debt_ratio=100.0,
            quick_ratio=150.0,
            interest_coverage_ratio=200.0,
        )
        engine = StockFilterEngine()
        result = engine.filter_stock(metrics)

        assert result.passed is False
        assert len(result.failed_criteria) == 3

    def test_filter_multiple_stocks(self):
        """Filter engine should correctly separate passed and failed stocks."""
        stocks = [
            FinancialMetrics(
                ticker="PASS1",
                dividend_yield=5.0,
                years_of_dividend=10,
                dividend_increasing=True,
                operating_income_increasing=True,
                revenue_increasing=True,
                debt_ratio=100.0,
                quick_ratio=150.0,
                interest_coverage_ratio=200.0,
            ),
            FinancialMetrics(
                ticker="FAIL1",
                dividend_yield=2.0,
                years_of_dividend=10,
                dividend_increasing=True,
                operating_income_increasing=True,
                revenue_increasing=True,
                debt_ratio=100.0,
                quick_ratio=150.0,
                interest_coverage_ratio=200.0,
            ),
        ]
        engine = StockFilterEngine()
        passed, failed = engine.filter_stocks(stocks)

        assert len(passed) == 1
        assert len(failed) == 1
        assert passed[0].ticker == "PASS1"
        assert failed[0].ticker == "FAIL1"

    def test_korean_market_support(self):
        """Filter engine should work with Korean market stocks."""
        metrics = FinancialMetrics(
            ticker="005930",  # Samsung Electronics
            market=Market.KR,
            dividend_yield=5.0,
            years_of_dividend=10,
            dividend_increasing=True,
            operating_income_increasing=True,
            revenue_increasing=True,
            debt_ratio=100.0,
            quick_ratio=150.0,
            interest_coverage_ratio=200.0,
        )
        engine = StockFilterEngine()
        result = engine.filter_stock(metrics)

        assert result.passed is True
        assert result.market == Market.KR
