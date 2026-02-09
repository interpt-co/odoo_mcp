"""Odoo connection layer — protocol adapters, version detection, connection management."""

from odoo_mcp.connection.manager import ConnectionManager
from odoo_mcp.connection.protocol import (
    AccessDeniedError,
    AuthenticationError,
    BaseOdooProtocol,
    ConnectionError,
    ConnectionState,
    OdooProtocol,
    OdooRpcError,
    OdooVersion,
    SessionExpiredError,
)

__all__ = [
    "AccessDeniedError",
    "AuthenticationError",
    "BaseOdooProtocol",
    "ConnectionError",
    "ConnectionManager",
    "ConnectionState",
    "OdooProtocol",
    "OdooRpcError",
    "OdooVersion",
    "SessionExpiredError",
]
