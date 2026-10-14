"""Tests for the configurable criteria registry (step 4)."""

import json

import pytest

from smart_investor.filters import registry
from smart_investor.filters.config import FilterConfig
from smart_investor.filters.criteria import FilterCriterion
from smart_investor.filters.engine import StockFilterEngine
from smart_investor.filters.registry import FilterSpec, UnknownFilterError
from smart_investor.models.stock import FinancialMetrics


@pytest.fixture
def restore_registry():
    """Snapshot and restore the registry around tests that mutate it."""
    original = registry.available_keys()
    yield
    for key in registry.available_keys():
        if key not in original:
            registry.unregister(key)


class TestDefaultRegistry:
    """Shipped criteria are registered and buildable."""

    def test_dividend_criteria_are_the_default_set(self):
        """Requiring dividend and value criteria at once passes almost nothing."""
        assert registry.default_keys() == [
            "dividend_yield",
            "consecutive_dividends",
            "dividend_growth",
            "operating_income_growth",
            "revenue_growth",
            "debt_ratio",
            "quick_ratio",
            "interest_coverage",
        ]

    def test_value_criteria_are_registered_but_opt_in(self):
        available = registry.available_keys()
        for key in ("per", "pbr", "graham_number", "roe", "operating_margin"):
            assert key in available
            assert key not in registry.default_keys()

    def test_unknown_key_raises(self):
        with pytest.raises(UnknownFilterError):
            registry.get("does_not_exist")

    def test_presets_cover_both_strategies(self):
        """The shipped presets must reference only registered keys."""
        import json
        from pathlib import Path

        root = Path(__file__).parent.parent
        for name in ("dividend", "value"):
            data = json.loads((root / "configs" / f"{name}.json").read_text(encoding="utf-8"))
            config = FilterConfig.from_dict(data)
            assert config.resolve_keys()
            config.build()

    def test_every_spec_builds(self):
        for spec in registry.all_specs():
            criterion = spec.build()
            assert hasattr(criterion, "check")
            assert isinstance(criterion.describe(), str)


class TestFilterSelection:
    """Criteria can be added to and removed from a run."""

    def test_default_selects_the_default_set(self):
        assert FilterConfig().resolve_keys() == registry.default_keys()

    def test_value_criteria_selectable_explicitly(self):
        assert FilterConfig(enabled=["per", "pbr"]).resolve_keys() == ["per", "pbr"]

    def test_enable_subset(self):
        config = FilterConfig(enabled=["dividend_yield", "debt_ratio"])
        assert config.resolve_keys() == ["dividend_yield", "debt_ratio"]

    def test_disable_removes(self):
        config = FilterConfig(disabled=["quick_ratio", "revenue_growth"])
        keys = config.resolve_keys()
        assert "quick_ratio" not in keys
        assert "revenue_growth" not in keys
        assert len(keys) == len(registry.default_keys()) - 2

    def test_enabled_order_follows_registry(self):
        config = FilterConfig(enabled=["debt_ratio", "dividend_yield"])
        assert config.resolve_keys() == ["dividend_yield", "debt_ratio"]

    def test_disable_wins_over_enable(self):
        config = FilterConfig(enabled=["dividend_yield"], disabled=["dividend_yield"])
        assert config.resolve_keys() == []

    def test_unknown_enabled_key_raises(self):
        with pytest.raises(UnknownFilterError):
            FilterConfig(enabled=["nope"]).resolve_keys()

    def test_unknown_disabled_key_raises(self):
        with pytest.raises(UnknownFilterError):
            FilterConfig(disabled=["nope"]).resolve_keys()


class TestParameterOverrides:
    """Thresholds are adjustable per run."""

    def test_override_threshold(self):
        config = FilterConfig(
            enabled=["dividend_yield"],
            params={"dividend_yield": {"min_dividend_yield": 2.0}},
        )
        _, criterion = config.build()[0]

        passed, _ = criterion.check(FinancialMetrics(ticker="T", dividend_yield=3.0))
        assert passed is True

    def test_default_threshold_still_applies(self):
        _, criterion = FilterConfig(enabled=["dividend_yield"]).build()[0]

        passed, _ = criterion.check(FinancialMetrics(ticker="T", dividend_yield=3.0))
        assert passed is False

    def test_unknown_parameter_raises(self):
        config = FilterConfig(
            enabled=["debt_ratio"], params={"debt_ratio": {"bogus": 1}}
        )
        with pytest.raises(TypeError, match="bogus"):
            config.build()

    def test_parameterless_criterion_rejects_overrides(self):
        config = FilterConfig(
            enabled=["dividend_growth"], params={"dividend_growth": {"x": 1}}
        )
        with pytest.raises(TypeError):
            config.build()


class TestConfigFile:
    """Criteria sets round-trip through JSON."""

    def test_load_from_file(self, tmp_path):
        path = tmp_path / "criteria.json"
        path.write_text(
            json.dumps({
                "enabled": ["dividend_yield", "consecutive_dividends"],
                "params": {"dividend_yield": {"min_dividend_yield": 5.0}},
            }),
            encoding="utf-8",
        )

        config = FilterConfig.load(path)
        assert config.resolve_keys() == ["dividend_yield", "consecutive_dividends"]
        assert config.params["dividend_yield"]["min_dividend_yield"] == 5.0

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            FilterConfig.load(tmp_path / "absent.json")

    def test_invalid_json_raises(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError):
            FilterConfig.load(path)

    def test_wrong_shape_raises(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"enabled": "dividend_yield"}), encoding="utf-8")
        with pytest.raises(ValueError):
            FilterConfig.load(path)


class TestCustomCriterion:
    """New criteria plug in without touching the engine."""

    def test_register_and_use(self, restore_registry):
        class MarketCapFilter:
            """Toy criterion used to prove the registry is open for extension."""

            def __init__(self, min_years: int = 1) -> None:
                self.min_years = min_years

            def check(self, metrics: FinancialMetrics) -> tuple[bool, str]:
                if metrics.years_of_dividend < self.min_years:
                    return False, "too few years"
                return True, "Passed"

            def describe(self) -> str:
                return f"years >= {self.min_years}"

        registry.register(FilterSpec(
            key="toy_years",
            label="Toy Years",
            factory=MarketCapFilter,
            params={"min_years": 1},
            description="test-only criterion",
        ))

        assert "toy_years" in registry.available_keys()

        engine = StockFilterEngine(
            config=FilterConfig(
                enabled=["toy_years"], params={"toy_years": {"min_years": 3}}
            )
        )
        result = engine.filter_stock(FinancialMetrics(ticker="X", years_of_dividend=5))
        assert result.passed is True

        result = engine.filter_stock(FinancialMetrics(ticker="Y", years_of_dividend=2))
        assert result.passed is False

    def test_duplicate_registration_raises(self, restore_registry):
        spec = FilterSpec(key="dividend_yield", label="dup", factory=lambda: None)
        with pytest.raises(ValueError):
            registry.register(spec)

    def test_unregister_unknown_raises(self):
        with pytest.raises(UnknownFilterError):
            registry.unregister("never_registered")


class TestEngineWiring:
    """The engine honours the configured selection."""

    def test_engine_uses_configured_subset(self):
        engine = StockFilterEngine(config=FilterConfig(enabled=["dividend_yield"]))
        assert len(engine.filters) == 1

    def test_engine_defaults_to_the_default_set(self):
        assert len(StockFilterEngine().filters) == len(registry.default_keys())

    def test_explicit_filters_bypass_registry(self):
        class AlwaysPass:
            def check(self, metrics: FinancialMetrics) -> tuple[bool, str]:
                return True, "Passed"

            def describe(self) -> str:
                return "always"

        engine = StockFilterEngine(filters=[("Always", AlwaysPass())])
        assert engine.filter_stock(FinancialMetrics(ticker="Z")).passed is True

    def test_no_filters_means_everything_passes(self):
        engine = StockFilterEngine(config=FilterConfig(enabled=[]))
        passed, failed = engine.filter_stocks([FinancialMetrics(ticker="Z")])
        assert len(passed) == 1
        assert failed == []

    def test_empty_input_does_not_divide_by_zero(self):
        passed, failed = StockFilterEngine().filter_stocks([])
        assert passed == []
        assert failed == []

    def test_criteria_are_protocol_compatible(self):
        for _, criterion in StockFilterEngine().filters:
            assert isinstance(criterion, FilterCriterion)
