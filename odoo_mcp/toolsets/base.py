"""Base toolset class - stub for Group 4.

Defines BaseToolset and ToolsetMetadata that all toolsets extend.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from odoo_mcp.connection.manager import ConnectionManager


@dataclass
class ToolsetMetadata:
    """Metadata describing a toolset's requirements and identity."""

    name: str
    description: str
    version: str = "0.1.0"
    required_modules: list[str] = field(default_factory=list)
    min_odoo_version: int | None = None
    max_odoo_version: int | None = None
    depends_on: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


class BaseToolset(ABC):
    """Abstract base class for all toolsets."""

    @abstractmethod
    def metadata(self) -> ToolsetMetadata:
        """Return toolset metadata."""
        ...

    @abstractmethod
    def register_tools(
        self, server: Any, connection: ConnectionManager
    ) -> list[str]:
        """Register this toolset's tools with the MCP server.

        Returns list of tool names registered.
        """
        ...
