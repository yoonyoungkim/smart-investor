"""Base classes for data collectors."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Generic, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class CollectionResult(Generic[T]):
    """Result of a data collection operation."""

    success: bool
    data: T | None = None
    error: str | None = None
    collected_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, data: T, **metadata: Any) -> "CollectionResult[T]":
        """Create a successful result."""
        return cls(success=True, data=data, metadata=metadata)

    @classmethod
    def fail(cls, error: str, **metadata: Any) -> "CollectionResult[T]":
        """Create an error result.

        Named ``fail`` rather than ``error``: a classmethod sharing a dataclass
        field's name becomes that field's default, which left ``.error`` holding
        a bound method - and therefore truthy - on every successful result.
        """
        return cls(success=False, error=error, metadata=metadata)


class DataCollector(ABC, Generic[T]):
    """Abstract base class for data collectors."""

    def __init__(self) -> None:
        """Initialize the collector."""
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def collect(self, **kwargs: Any) -> CollectionResult[T]:
        """Collect data.

        Args:
            **kwargs: Collection parameters

        Returns:
            CollectionResult with collected data or error
        """
        ...

    def collect_safe(self, **kwargs: Any) -> CollectionResult[T]:
        """Safely collect data with exception handling.

        Args:
            **kwargs: Collection parameters

        Returns:
            CollectionResult with collected data or error
        """
        try:
            return self.collect(**kwargs)
        except Exception as e:
            self.logger.error(f"Collection failed: {e}", exc_info=True)
            return CollectionResult.fail(str(e))
