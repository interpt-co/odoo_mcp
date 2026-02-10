"""Odoo connection layer — protocol adapters, version detection, connection management."""

from odoo_mcp.connection.manager import ConnectionManager
from odoo_mcp.connection.protocol import (
    AccessDeniedError,
    AuthenticationError,
    BaseOdooProtocol,
    ConnectionError,
    ConnectionState,
    Json2EndpointNotFoundError,
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
    "Json2EndpointNotFoundError",
    "OdooProtocol",
    "OdooRpcError",
    "OdooVersion",
    "SessionExpiredError",
]
