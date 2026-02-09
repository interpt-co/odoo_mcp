"""
Safety module for the Odoo MCP server.

Provides operation mode enforcement, model/field/method filtering,
tool annotations, rate limiting, and audit logging.
"""

from odoo_mcp.safety.modes import (
    DEFAULT_FIELD_BLOCKLIST,
    DEFAULT_METHOD_BLOCKLIST,
    DEFAULT_MODEL_BLOCKLIST,
    OperationMode,
    SafetyConfig,
    ToolAnnotation,
    enforce_mode,
    filter_fields,
    get_annotation,
    get_tool_visibility,
    validate_method,
    validate_model_access,
)
from odoo_mcp.safety.limits import RateLimiter, RateLimitConfig
from odoo_mcp.safety.audit import AuditLogger, AuditConfig
