"""Tests for trend analysis using linear regression."""

import pytest
from smart_investor.analysis.calculator import MetricsCalculator


class TestTrendAnalysis:
    """Tests for the _is_increasing_trend static method."""

    def test_clearly_increasing_trend(self):
        """Test with clearly increasing values."""
        values = [100, 110, 120, 130, 140]
        result = MetricsCalculator._is_increasing_trend(values)
        assert result == True

    def test_clearly_decreasing_trend(self):
        """Test with clearly decreasing values."""
        values = [140, 130, 120, 110, 100]
        result = MetricsCalculator._is_increasing_trend(values)
        assert result == False

    def test_flat_trend(self):
        """Test with flat values (no trend)."""
        values = [100, 100, 100, 100, 100]
        result = MetricsCalculator._is_increasing_trend(values)
        # Flat trend has no positive slope
        assert result == False

    def test_noisy_increasing_trend(self):
        """Test with noisy but overall increasing trend."""
        values = [100, 95, 110, 105, 120, 115, 130]
        result = MetricsCalculator._is_increasing_trend(values, min_r_squared=0.3)
        assert result == True

    def test_insufficient_data(self):
        """Test with too few data points."""
        values = [100]
        result = MetricsCalculator._is_increasing_trend(values)
        assert result == False

    def test_two_points_increasing(self):
        """Test with exactly two increasing points."""
        values = [100, 110]
        result = MetricsCalculator._is_increasing_trend(values, min_r_squared=0.3)
        assert result == True

    def test_two_points_decreasing(self):
        """Test with exactly two decreasing points."""
        values = [110, 100]
        result = MetricsCalculator._is_increasing_trend(values, min_r_squared=0.3)
        assert result == False

    def test_weak_trend_low_r_squared(self):
        """Test with weak trend that might not meet R² threshold."""
        # Very noisy data with slight upward trend
        values = [100, 80, 120, 90, 110, 85, 105]
        # With lower threshold it might pass
        result_low = MetricsCalculator._is_increasing_trend(values, min_r_squared=0.1)
        # With higher threshold it should fail
        result_high = MetricsCalculator._is_increasing_trend(values, min_r_squared=0.8)
        assert result_high == False

    def test_strong_trend_high_r_squared(self):
        """Test with strong linear trend."""
        values = [100, 120, 140, 160, 180, 200]
        result = MetricsCalculator._is_increasing_trend(values, min_r_squared=0.9)
        assert result == True

    def test_empty_list(self):
        """Test with empty list."""
        values = []
        result = MetricsCalculator._is_increasing_trend(values)
        assert result == False

    def test_negative_values(self):
        """Test with negative values (still can have increasing trend)."""
        values = [-100, -80, -60, -40, -20]
        result = MetricsCalculator._is_increasing_trend(values)
        assert result == True

    def test_mixed_positive_negative(self):
        """Test trend crossing from negative to positive."""
        values = [-20, -10, 0, 10, 20]
        result = MetricsCalculator._is_increasing_trend(values)
        assert result == True


class TestSpecialDividendFilter:
    """Tests for special dividend filtering."""

    def test_no_outliers(self):
        """Test with regular dividends only."""
        dividends = [0.50, 0.52, 0.54, 0.56]
        calculator = MetricsCalculator.__new__(MetricsCalculator)
        result = calculator._filter_special_dividends(dividends)
        assert result == dividends

    def test_one_special_dividend(self):
        """Test filtering out one special dividend."""
        dividends = [0.50, 0.52, 5.00, 0.54]  # 5.00 is special
        calculator = MetricsCalculator.__new__(MetricsCalculator)
        result = calculator._filter_special_dividends(dividends)
        assert 5.00 not in result
        assert len(result) == 3

    def test_multiple_special_dividends(self):
        """Test filtering multiple special dividends."""
        # Need enough regular dividends so filtering doesn't exceed 30% rule
        dividends = [0.50, 0.52, 0.54, 0.56, 0.58, 0.60, 0.62, 5.00, 4.00]
        calculator = MetricsCalculator.__new__(MetricsCalculator)
        result = calculator._filter_special_dividends(dividends)
        # Outliers should be filtered (median ~0.56, threshold ~1.12)
        assert 5.00 not in result
        assert 4.00 not in result

    def test_too_many_filtered(self):
        """Test that we keep original if too many would be filtered."""
        # If more than 30% would be filtered, keep original
        dividends = [0.50, 5.00, 4.00, 3.00]  # Most are "special"
        calculator = MetricsCalculator.__new__(MetricsCalculator)
        result = calculator._filter_special_dividends(dividends)
        # Should return original since > 30% would be filtered
        assert result == dividends

    def test_single_value(self):
        """Test with single value."""
        dividends = [0.50]
        calculator = MetricsCalculator.__new__(MetricsCalculator)
        result = calculator._filter_special_dividends(dividends)
        assert result == dividends

    def test_empty_list(self):
        """Test with empty list."""
        dividends = []
        calculator = MetricsCalculator.__new__(MetricsCalculator)
        result = calculator._filter_special_dividends(dividends)
        assert result == []
