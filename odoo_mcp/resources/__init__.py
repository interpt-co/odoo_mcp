"""MCP Resources for the Odoo MCP server."""

from odoo_mcp.resources.uri import OdooUri, parse_odoo_uri, OdooUriError
from odoo_mcp.resources.provider import ResourceProvider

__all__ = [
    "OdooUri",
    "parse_odoo_uri",
    "OdooUriError",
    "ResourceProvider",
]
