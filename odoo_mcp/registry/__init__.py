"""Model/Field/Method Registry for the Odoo MCP server."""

from odoo_mcp.registry.model_registry import (
    FieldInfo,
    MethodInfo,
    ModelInfo,
    Registry,
    ModelRegistry,
    NO_KWARGS_METHODS,
    FIELD_TYPE_MAP,
    DEFAULT_INTROSPECTION_MODELS,
)

__all__ = [
    "FieldInfo",
    "MethodInfo",
    "ModelInfo",
    "Registry",
    "ModelRegistry",
    "NO_KWARGS_METHODS",
    "FIELD_TYPE_MAP",
    "DEFAULT_INTROSPECTION_MODELS",
]
