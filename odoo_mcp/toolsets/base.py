"""Base toolset abstract class and metadata structures.

Defines the contract that all toolsets must implement (REQ-03-01 through REQ-03-03)
and helpers for tool naming (REQ-03-11) and MCP annotations (REQ-03-13, REQ-03-14).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from odoo_mcp.connection.manager import ConnectionManager


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

@dataclass
class ToolsetMetadata:
    """Metadata describing a toolset's requirements and identity (REQ-03-01)."""

    name: str
    """Unique identifier (e.g. ``"sales"``)."""

    description: str
    """Human-readable description."""

    version: str = "0.1.0"
    """Toolset version (semver)."""

    required_modules: list[str] = field(default_factory=list)
    """Odoo modules that must be installed."""

    min_odoo_version: int | None = None
    """Minimum Odoo major version (e.g. 14)."""

    max_odoo_version: int | None = None
    """Maximum Odoo major version (e.g. 18)."""

    depends_on: list[str] = field(default_factory=list)
    """Other toolset names this toolset depends on."""

    tags: list[str] = field(default_factory=list)
    """Categorisation tags."""


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class BaseToolset(ABC):
    """Abstract base class for all toolsets (REQ-03-01)."""

    @abstractmethod
    def metadata(self) -> ToolsetMetadata:
        """Return toolset metadata (REQ-03-02)."""
        ...

    @abstractmethod
    def register_tools(self, server: Any, connection: ConnectionManager, **kwargs: Any) -> list[str]:
        """Register this toolset's tools with the MCP server.

        Returns a list of the tool names that were registered (REQ-03-03).
        """
        ...


# ---------------------------------------------------------------------------
# Tool naming convention  (REQ-03-11)
# ---------------------------------------------------------------------------

def tool_name(toolset: str, action: str) -> str:
    """Build a canonical tool name following ``odoo_{toolset}_{action}``."""
    return f"odoo_{toolset}_{action}"


# ---------------------------------------------------------------------------
# MCP tool annotations helper  (REQ-03-13 / REQ-03-14 / REQ-11-17 / REQ-11-18)
# ---------------------------------------------------------------------------

def make_annotations(
    *,
    title: str,
    read_only: bool = False,
    destructive: bool = False,
    idempotent: bool = False,
    open_world: bool = True,
) -> dict[str, Any]:
    """Return a dict suitable for MCP ``ToolAnnotations``.

    All Odoo tools set ``openWorldHint=True`` because they interact with an
    external Odoo instance.
    """
    return {
        "title": title,
        "readOnlyHint": read_only,
        "destructiveHint": destructive,
        "idempotentHint": idempotent,
        "openWorldHint": open_world,
    }


# Convenience pre-built annotation sets -----------------------------------

ANNOTATIONS_READ_ONLY = dict(read_only=True, destructive=False, idempotent=True, open_world=True)
ANNOTATIONS_WRITE = dict(read_only=False, destructive=False, idempotent=False, open_world=True)
ANNOTATIONS_WRITE_IDEMPOTENT = dict(read_only=False, destructive=False, idempotent=True, open_world=True)
ANNOTATIONS_DESTRUCTIVE = dict(read_only=False, destructive=True, idempotent=True, open_world=True)
