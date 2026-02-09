"""Odoo MCP Server — exposes Odoo ERP as MCP tools, resources, and prompts."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("odoo-mcp")
except PackageNotFoundError:
    __version__ = "0.1.0"
