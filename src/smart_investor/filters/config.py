"""Configuration for which recommendation criteria run and with what thresholds.

A configuration is a small JSON document (stdlib only, no extra dependency):

.. code-block:: json

    {
      "enabled": ["dividend_yield", "consecutive_dividends", "debt_ratio"],
      "params": {
        "dividend_yield": {"min_dividend_yield": 3.0},
        "debt_ratio": {"max_debt_ratio": 150.0}
      }
    }

``enabled`` omitted means "every criterion in the default set" (the dividend
criteria - see :attr:`FilterSpec.in_default`); ``disabled`` subtracts from it.
This is what makes criteria addable and removable per run without editing code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import registry
from .criteria import FilterCriterion


@dataclass
class FilterConfig:
    """Selection of criteria and their threshold overrides.

    Attributes:
        enabled: Criterion keys to run. None means the default set.
        disabled: Criterion keys to drop from the enabled set.
        params: Per-criterion parameter overrides.
    """

    enabled: list[str] | None = None
    disabled: list[str] = field(default_factory=list)
    params: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FilterConfig":
        """Build a configuration from a plain dictionary.

        Args:
            data: Mapping with optional ``enabled``, ``disabled`` and ``params``.

        Returns:
            The parsed configuration.

        Raises:
            ValueError: If a field has the wrong shape.
        """
        enabled = data.get("enabled")
        if enabled is not None and not isinstance(enabled, list):
            raise ValueError("'enabled' must be a list of filter keys")

        disabled = data.get("disabled", [])
        if not isinstance(disabled, list):
            raise ValueError("'disabled' must be a list of filter keys")

        params = data.get("params", {})
        if not isinstance(params, dict):
            raise ValueError("'params' must be an object keyed by filter key")

        return cls(enabled=enabled, disabled=list(disabled), params=dict(params))

    @classmethod
    def load(cls, path: str | Path) -> "FilterConfig":
        """Load a configuration from a JSON file.

        Args:
            path: Path to the JSON configuration.

        Returns:
            The parsed configuration.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file is not valid JSON or has the wrong shape.
        """
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Filter config not found: {file_path}")

        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in {file_path}: {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError(f"{file_path} must contain a JSON object")

        return cls.from_dict(data)

    def resolve_keys(self) -> list[str]:
        """Determine which criterion keys this configuration selects.

        Returns:
            Criterion keys in registry order.

        Raises:
            UnknownFilterError: If a referenced key is not registered.
        """
        if self.enabled is None:
            # Not every registered criterion - see FilterSpec.in_default.
            selected = registry.default_keys()
        else:
            # Validate every requested key so a typo fails loudly rather than
            # silently narrowing the criteria a recommendation ran with.
            for key in self.enabled:
                registry.get(key)
            selected = [k for k in registry.available_keys() if k in set(self.enabled)]

        for key in self.disabled:
            registry.get(key)

        removed = set(self.disabled)
        return [key for key in selected if key not in removed]

    def build(self) -> list[tuple[str, FilterCriterion]]:
        """Instantiate the selected criteria.

        Returns:
            List of ``(label, criterion)`` pairs in evaluation order.

        Raises:
            UnknownFilterError: If a referenced key is not registered.
            TypeError: If an override names a parameter the criterion lacks.
        """
        built: list[tuple[str, FilterCriterion]] = []

        for key in self.resolve_keys():
            spec = registry.get(key)
            built.append((spec.label, spec.build(self.params.get(key))))

        return built

    def describe(self) -> list[str]:
        """Summarise the active criteria for logging.

        Returns:
            One description line per selected criterion.
        """
        lines = []
        for key in self.resolve_keys():
            spec = registry.get(key)
            criterion = spec.build(self.params.get(key))
            detail = criterion.describe() if hasattr(criterion, "describe") else spec.description
            lines.append(f"{key}: {detail}")
        return lines
