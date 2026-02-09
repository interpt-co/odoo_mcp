"""Abstract protocol interface - stub for Group 1.

This file defines the interface contract that Group 1 will implement.
Group 5 codes against this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class OdooProtocol(ABC):
    """Abstract base class for Odoo RPC protocol adapters."""

    @abstractmethod
    async def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> Any:
        """Execute an Odoo ORM method."""
        ...

    @abstractmethod
    async def search_read(
        self,
        model: str,
        domain: list[Any],
        fields: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search and read records."""
        ...

    @abstractmethod
    async def search_count(
        self,
        model: str,
        domain: list[Any],
    ) -> int:
        """Count records matching domain."""
        ...
