"""Abstract protocol interface, shared base class, and unified error types.

REQ-02b-01, REQ-02b-02, REQ-02b-12.
"""

from __future__ import annotations

import enum
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Connection state machine (REQ-02-18)
# ---------------------------------------------------------------------------

class ConnectionState(enum.Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    AUTHENTICATED = "authenticated"
    READY = "ready"
    ERROR = "error"
    RECONNECTING = "reconnecting"


# ---------------------------------------------------------------------------
# OdooVersion dataclass (REQ-02-11)
# ---------------------------------------------------------------------------

@dataclass
class OdooVersion:
    major: int = 14
    minor: int = 0
    micro: int = 0
    level: str = "final"
    serial: int = 0
    full_string: str = ""
    edition: str = "community"

    def __str__(self) -> str:
        return self.full_string or f"{self.major}.{self.minor}"


# ---------------------------------------------------------------------------
# Error types (REQ-02b-12)
# ---------------------------------------------------------------------------

class OdooRpcError(Exception):
    """Unified Odoo RPC error."""

    def __init__(
        self,
        message: str,
        error_class: str | None = None,
        traceback: str | None = None,
        model: str | None = None,
        method: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.traceback = traceback
        self.model = model
        self.method = method

    @classmethod
    def from_xmlrpc_fault(cls, fault: Any, **ctx: Any) -> OdooRpcError:
        """Create from xmlrpc.client.Fault."""
        fault_string = str(getattr(fault, "faultString", fault))
        lines = fault_string.strip().split("\n")
        last_line = lines[-1] if lines else str(fault)
        match = re.match(r"^([\w.]+(?:Error|Warning|Exception)):\s*(.*)", last_line)
        if match:
            return cls(
                message=match.group(2),
                error_class=match.group(1),
                traceback=fault_string,
                **ctx,
            )
        return cls(message=fault_string, traceback=fault_string, **ctx)

    @classmethod
    def from_jsonrpc_error(cls, error_data: dict, **ctx: Any) -> OdooRpcError:
        """Create from JSON-RPC error response."""
        data = error_data.get("data", {})
        return cls(
            message=data.get("message", error_data.get("message", "Unknown error")),
            error_class=data.get("name"),
            traceback=data.get("debug"),
            **ctx,
        )

    @classmethod
    def from_json2_error(cls, error_data: dict, **ctx: Any) -> OdooRpcError:
        """Create from JSON-2 error response."""
        data = error_data.get("data", {})
        return cls(
            message=data.get("message", error_data.get("message", "Unknown error")),
            error_class=data.get("name"),
            traceback=data.get("debug"),
            **ctx,
        )


class AuthenticationError(OdooRpcError):
    """Authentication failed."""


class ConnectionError(Exception):  # noqa: A001 — intentional shadow of builtin
    """Network / transport-level connection error."""


class SessionExpiredError(OdooRpcError):
    """Session has expired and needs re-authentication."""


class AccessDeniedError(OdooRpcError):
    """Access denied by Odoo security rules."""


# ---------------------------------------------------------------------------
# Abstract protocol interface (REQ-02b-01)
# ---------------------------------------------------------------------------

class OdooProtocol(ABC):
    """Abstract interface for Odoo RPC communication."""

    @property
    @abstractmethod
    def protocol_name(self) -> str:
        """Return 'xmlrpc', 'jsonrpc', or 'json2'."""
        ...

    @abstractmethod
    async def authenticate(self, db: str, login: str, password: str) -> int:
        """Authenticate and return uid."""
        ...

    @abstractmethod
    async def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> Any:
        """Execute an Odoo model method."""
        ...

    @abstractmethod
    async def version_info(self) -> dict:
        """Get server version information."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close the connection and release resources."""
        ...

    def is_connected(self) -> bool:
        """Check if the connection is alive."""
        return False


# ---------------------------------------------------------------------------
# Base protocol with shared convenience methods (REQ-02b-02)
# ---------------------------------------------------------------------------

class BaseOdooProtocol(OdooProtocol):
    """Shared convenience methods built on execute_kw."""

    def __init__(self) -> None:
        self._base_context: dict[str, Any] = {}

    def set_base_context(self, ctx: dict[str, Any]) -> None:
        self._base_context = dict(ctx)

    async def search_read(
        self,
        model: str,
        domain: list,
        fields: list[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
        context: dict | None = None,
    ) -> list[dict]:
        kwargs: dict[str, Any] = {}
        if fields is not None:
            kwargs["fields"] = fields
        if offset:
            kwargs["offset"] = offset
        if limit is not None:
            kwargs["limit"] = limit
        if order:
            kwargs["order"] = order
        return await self.execute_kw(model, "search_read", [domain], kwargs, context)

    async def read(
        self,
        model: str,
        ids: list[int],
        fields: list[str] | None = None,
        context: dict | None = None,
    ) -> list[dict]:
        kwargs: dict[str, Any] = {}
        if fields is not None:
            kwargs["fields"] = fields
        return await self.execute_kw(model, "read", [ids], kwargs, context)

    async def create(
        self, model: str, values: dict, context: dict | None = None
    ) -> int:
        return await self.execute_kw(model, "create", [values], context=context)

    async def write(
        self,
        model: str,
        ids: list[int],
        values: dict,
        context: dict | None = None,
    ) -> bool:
        return await self.execute_kw(model, "write", [ids, values], context=context)

    async def unlink(
        self, model: str, ids: list[int], context: dict | None = None
    ) -> bool:
        return await self.execute_kw(model, "unlink", [ids], context=context)

    async def search_count(
        self, model: str, domain: list, context: dict | None = None
    ) -> int:
        return await self.execute_kw(model, "search_count", [domain], context=context)

    async def fields_get(
        self,
        model: str,
        attributes: list[str] | None = None,
        context: dict | None = None,
    ) -> dict:
        kwargs: dict[str, Any] = {}
        if attributes:
            kwargs["attributes"] = attributes
        return await self.execute_kw(model, "fields_get", [], kwargs, context)

    async def name_search(
        self,
        model: str,
        name: str,
        args: list | None = None,
        operator: str = "ilike",
        limit: int = 5,
        context: dict | None = None,
    ) -> list:
        kwargs = {"args": args or [], "operator": operator, "limit": limit}
        return await self.execute_kw(model, "name_search", [name], kwargs, context)
