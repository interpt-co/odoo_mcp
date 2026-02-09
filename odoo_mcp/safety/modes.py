"""
Safety mode enforcement and tool annotations for the Odoo MCP server.

Implements:
- Three operation modes: readonly, restricted, full (REQ-11-01 through REQ-11-05)
- Model filtering with allowlist/blocklist (REQ-11-06 through REQ-11-11)
- Field filtering with blocklist (REQ-11-12 through REQ-11-14)
- Method filtering with blocklist (REQ-11-15, REQ-11-16)
- MCP tool annotations (REQ-11-17, REQ-11-18)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from odoo_mcp.errors import (
    FieldBlockedError,
    MethodBlockedError,
    ModeViolationError,
    ModelAccessError,
)


class OperationMode(str, Enum):
    """Server operation modes (REQ-11-01)."""

    READONLY = "readonly"
    RESTRICTED = "restricted"
    FULL = "full"


# ── Default blocklists ──────────────────────────────────────────────

DEFAULT_MODEL_BLOCKLIST: list[str] = [
    "ir.config_parameter",
    "ir.cron",
    "base.automation",
    "ir.rule",
    "ir.model.access",
    "res.users",
    "ir.mail_server",
    "fetchmail.server",
    "payment.provider",
]

DEFAULT_FIELD_BLOCKLIST: list[str] = [
    "password",
    "password_crypt",
    "oauth_access_token",
    "oauth_provider_id",
    "api_key",
    "api_key_ids",
    "totp_secret",
    "totp_enabled",
    "signature",
]

DEFAULT_METHOD_BLOCKLIST: list[str] = [
    "sudo",
    "with_user",
    "with_env",
    "with_context",
    "invalidate_cache",
    "clear_caches",
    "init",
    "uninstall",
    "module_uninstall",
]


@dataclass
class SafetyConfig:
    """Safety configuration (REQ-11-01 through REQ-11-16)."""

    mode: OperationMode = OperationMode.READONLY
    model_allowlist: list[str] = field(default_factory=list)
    model_blocklist: list[str] = field(default_factory=list)
    write_allowlist: list[str] = field(default_factory=list)
    field_blocklist: list[str] = field(default_factory=list)
    method_blocklist: list[str] = field(default_factory=list)

    @property
    def effective_model_blocklist(self) -> set[str]:
        """Combine default and user blocklist."""
        return set(DEFAULT_MODEL_BLOCKLIST) | set(self.model_blocklist)

    @property
    def effective_field_blocklist(self) -> set[str]:
        """Combine default and user field blocklist."""
        return set(DEFAULT_FIELD_BLOCKLIST) | set(self.field_blocklist)

    @property
    def effective_method_blocklist(self) -> set[str]:
        """Combine default and user method blocklist."""
        return set(DEFAULT_METHOD_BLOCKLIST) | set(self.method_blocklist)


# ── Mode enforcement (REQ-11-03) ────────────────────────────────────

READ_OPERATIONS = frozenset({"read", "search"})


def enforce_mode(
    mode: OperationMode | str,
    operation: str,
    model: str,
    config: SafetyConfig,
) -> None:
    """Enforce the operation mode before any Odoo API call (REQ-11-03).

    Args:
        mode: Current operation mode.
        operation: One of "read", "search", "create", "write", "unlink", "execute".
        model: Odoo model name.
        config: Safety configuration.

    Raises:
        ModeViolationError: If the operation is not allowed.
    """
    mode_str = mode.value if isinstance(mode, OperationMode) else mode

    if mode_str == OperationMode.READONLY:
        if operation not in READ_OPERATIONS:
            raise ModeViolationError(
                f"'{operation}' not allowed in readonly mode"
            )

    elif mode_str == OperationMode.RESTRICTED:
        if operation in ("create", "write", "execute"):
            if model not in config.write_allowlist:
                raise ModeViolationError(
                    f"'{operation}' on '{model}' not allowed in restricted mode. "
                    f"Allowed models: {config.write_allowlist}"
                )
        if operation == "unlink":
            raise ModeViolationError("Delete not allowed in restricted mode")

    # "full" mode: all operations allowed (subject to model filtering)


# ── Tool visibility (REQ-11-04, REQ-11-05) ──────────────────────────

# Maps tool name → {mode: visible}
# "Hidden" means NOT registered with MCP server in that mode.
_TOOL_VISIBILITY: dict[str, dict[str, bool]] = {
    "odoo_core_search_read": {"readonly": True, "restricted": True, "full": True},
    "odoo_core_read": {"readonly": True, "restricted": True, "full": True},
    "odoo_core_count": {"readonly": True, "restricted": True, "full": True},
    "odoo_core_fields_get": {"readonly": True, "restricted": True, "full": True},
    "odoo_core_name_get": {"readonly": True, "restricted": True, "full": True},
    "odoo_core_default_get": {"readonly": True, "restricted": True, "full": True},
    "odoo_core_deep_search": {"readonly": True, "restricted": True, "full": True},
    "odoo_core_create": {"readonly": False, "restricted": True, "full": True},
    "odoo_core_write": {"readonly": False, "restricted": True, "full": True},
    "odoo_core_unlink": {"readonly": False, "restricted": False, "full": True},
    "odoo_core_execute": {"readonly": True, "restricted": True, "full": True},
    "odoo_core_list_models": {"readonly": True, "restricted": True, "full": True},
    "odoo_core_list_toolsets": {"readonly": True, "restricted": True, "full": True},
    # Workflow tools
    "odoo_sales_create_quotation": {"readonly": False, "restricted": True, "full": True},
    "odoo_sales_confirm_order": {"readonly": False, "restricted": True, "full": True},
    "odoo_sales_cancel_order": {"readonly": False, "restricted": True, "full": True},
    "odoo_accounting_create_invoice": {"readonly": False, "restricted": True, "full": True},
    "odoo_accounting_confirm_invoice": {"readonly": False, "restricted": True, "full": True},
    "odoo_inventory_create_transfer": {"readonly": False, "restricted": True, "full": True},
    "odoo_inventory_validate_transfer": {"readonly": False, "restricted": True, "full": True},
    "odoo_crm_create_lead": {"readonly": False, "restricted": True, "full": True},
    "odoo_project_create_task": {"readonly": False, "restricted": True, "full": True},
    "odoo_helpdesk_create_ticket": {"readonly": False, "restricted": True, "full": True},
    # Chatter & attachments
    "odoo_chatter_post_message": {"readonly": False, "restricted": True, "full": True},
    "odoo_attachments_upload": {"readonly": False, "restricted": True, "full": True},
    "odoo_attachments_delete": {"readonly": False, "restricted": False, "full": True},
    # Reports
    "odoo_reports_generate": {"readonly": True, "restricted": True, "full": True},
}


def get_tool_visibility(tool_name: str, mode: OperationMode | str) -> bool:
    """Return whether a tool should be visible (registered) in the given mode (REQ-11-04)."""
    mode_str = mode.value if isinstance(mode, OperationMode) else mode
    tool_entry = _TOOL_VISIBILITY.get(tool_name)
    if tool_entry is None:
        # Unknown tool: default visible in all modes
        return True
    return tool_entry.get(mode_str, True)


# ── Model filtering (REQ-11-06 through REQ-11-09) ──────────────────

def validate_model_access(
    model: str,
    operation: str,
    config: SafetyConfig,
) -> bool:
    """Validate that the model is accessible for the given operation.

    Args:
        model: Odoo model name.
        operation: One of "read", "search", "create", "write", "unlink", "execute".
        config: Safety configuration.

    Raises:
        ModelAccessError: If access to the model is denied.

    Returns:
        True if access is allowed.
    """
    # res.users special case (REQ-11-09): read allowed, write blocked
    if model == "res.users":
        if operation in READ_OPERATIONS:
            return True
        raise ModelAccessError(
            f"Write access to 'res.users' is blocked for safety. "
            f"Read access is allowed."
        )

    # Default blocklist always applied (REQ-11-08)
    if model in config.effective_model_blocklist:
        raise ModelAccessError(
            f"Access to model '{model}' is blocked by safety configuration."
        )

    # Allowlist check (REQ-11-06)
    if config.model_allowlist:
        if model not in config.model_allowlist:
            raise ModelAccessError(
                f"Model '{model}' is not in the model allowlist. "
                f"Allowed models: {config.model_allowlist}"
            )

    return True


# ── Field filtering (REQ-11-12 through REQ-11-14) ──────────────────

def filter_fields(
    fields: dict[str, Any] | list[str] | None,
    model: str,
    operation: str,
    config: SafetyConfig,
) -> dict[str, Any] | list[str] | None:
    """Filter fields based on the blocklist (REQ-11-14).

    For read operations: removes blocked fields from results.
    For write operations: raises FieldBlockedError if blocked field is present.

    Args:
        fields: Either a dict of field data (from fields_get/read results)
                or a list of field names (from search_read fields parameter).
        model: Odoo model name.
        operation: "read" or "write".
        config: Safety configuration.

    Returns:
        Filtered fields (same type as input).

    Raises:
        FieldBlockedError: If a blocked field is used in a write operation.
    """
    if fields is None:
        return None

    blocked = config.effective_field_blocklist

    if isinstance(fields, dict):
        if operation in ("create", "write"):
            # Reject blocked fields in write values
            blocked_found = set(fields.keys()) & blocked
            if blocked_found:
                raise FieldBlockedError(
                    f"Cannot write to blocked field(s): {', '.join(sorted(blocked_found))}. "
                    f"These fields are restricted for security."
                )
            return fields
        else:
            # Remove blocked fields from read results
            return {k: v for k, v in fields.items() if k not in blocked}

    if isinstance(fields, list):
        if operation in ("create", "write"):
            blocked_found = set(fields) & blocked
            if blocked_found:
                raise FieldBlockedError(
                    f"Cannot write to blocked field(s): {', '.join(sorted(blocked_found))}. "
                    f"These fields are restricted for security."
                )
            return fields
        else:
            return [f for f in fields if f not in blocked]

    return fields


# ── Method filtering (REQ-11-15, REQ-11-16) ─────────────────────────

def validate_method(method_name: str, config: SafetyConfig) -> bool:
    """Validate that a method is not in the blocklist (REQ-11-15, REQ-11-16).

    Raises:
        MethodBlockedError: If the method is blocked.

    Returns:
        True if allowed.
    """
    if method_name in config.effective_method_blocklist:
        raise MethodBlockedError(
            f"Method '{method_name}' is blocked for safety. "
            f"Blocked methods: {sorted(config.effective_method_blocklist)}"
        )
    return True


# ── Tool Annotations (REQ-11-17, REQ-11-18) ─────────────────────────

@dataclass
class ToolAnnotation:
    """MCP tool annotation (REQ-11-17)."""

    title: str
    readOnlyHint: bool = False
    destructiveHint: bool = False
    idempotentHint: bool = False
    openWorldHint: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "readOnlyHint": self.readOnlyHint,
            "destructiveHint": self.destructiveHint,
            "idempotentHint": self.idempotentHint,
            "openWorldHint": self.openWorldHint,
        }


# Complete annotation registry (REQ-11-18)
_TOOL_ANNOTATIONS: dict[str, ToolAnnotation] = {
    # Read tools
    "odoo_core_search_read": ToolAnnotation(
        title="Search & Read Records",
        readOnlyHint=True, destructiveHint=False, idempotentHint=True,
    ),
    "odoo_core_read": ToolAnnotation(
        title="Read Records",
        readOnlyHint=True, destructiveHint=False, idempotentHint=True,
    ),
    "odoo_core_count": ToolAnnotation(
        title="Count Records",
        readOnlyHint=True, destructiveHint=False, idempotentHint=True,
    ),
    "odoo_core_fields_get": ToolAnnotation(
        title="Get Field Definitions",
        readOnlyHint=True, destructiveHint=False, idempotentHint=True,
    ),
    "odoo_core_name_get": ToolAnnotation(
        title="Get Record Names",
        readOnlyHint=True, destructiveHint=False, idempotentHint=True,
    ),
    "odoo_core_default_get": ToolAnnotation(
        title="Get Default Values",
        readOnlyHint=True, destructiveHint=False, idempotentHint=True,
    ),
    "odoo_core_deep_search": ToolAnnotation(
        title="Deep Search",
        readOnlyHint=True, destructiveHint=False, idempotentHint=True,
    ),
    "odoo_core_list_models": ToolAnnotation(
        title="List Available Models",
        readOnlyHint=True, destructiveHint=False, idempotentHint=True,
    ),
    "odoo_core_list_toolsets": ToolAnnotation(
        title="List Toolsets",
        readOnlyHint=True, destructiveHint=False, idempotentHint=True,
    ),
    # Write tools
    "odoo_core_create": ToolAnnotation(
        title="Create Record",
        readOnlyHint=False, destructiveHint=False, idempotentHint=False,
    ),
    "odoo_core_write": ToolAnnotation(
        title="Update Record",
        readOnlyHint=False, destructiveHint=False, idempotentHint=True,
    ),
    "odoo_core_unlink": ToolAnnotation(
        title="Delete Record",
        readOnlyHint=False, destructiveHint=True, idempotentHint=True,
    ),
    "odoo_core_execute": ToolAnnotation(
        title="Execute Method",
        readOnlyHint=False, destructiveHint=False, idempotentHint=False,
    ),
    # Workflow creates
    "odoo_sales_create_quotation": ToolAnnotation(
        title="Create Quotation",
        readOnlyHint=False, destructiveHint=False, idempotentHint=False,
    ),
    "odoo_accounting_create_invoice": ToolAnnotation(
        title="Create Invoice",
        readOnlyHint=False, destructiveHint=False, idempotentHint=False,
    ),
    "odoo_inventory_create_transfer": ToolAnnotation(
        title="Create Transfer",
        readOnlyHint=False, destructiveHint=False, idempotentHint=False,
    ),
    "odoo_crm_create_lead": ToolAnnotation(
        title="Create Lead",
        readOnlyHint=False, destructiveHint=False, idempotentHint=False,
    ),
    "odoo_project_create_task": ToolAnnotation(
        title="Create Task",
        readOnlyHint=False, destructiveHint=False, idempotentHint=False,
    ),
    "odoo_helpdesk_create_ticket": ToolAnnotation(
        title="Create Ticket",
        readOnlyHint=False, destructiveHint=False, idempotentHint=False,
    ),
    # Workflow confirms
    "odoo_sales_confirm_order": ToolAnnotation(
        title="Confirm Sales Order",
        readOnlyHint=False, destructiveHint=False, idempotentHint=True,
    ),
    "odoo_accounting_confirm_invoice": ToolAnnotation(
        title="Confirm Invoice",
        readOnlyHint=False, destructiveHint=False, idempotentHint=True,
    ),
    "odoo_inventory_validate_transfer": ToolAnnotation(
        title="Validate Transfer",
        readOnlyHint=False, destructiveHint=False, idempotentHint=True,
    ),
    # Workflow cancels
    "odoo_sales_cancel_order": ToolAnnotation(
        title="Cancel Sales Order",
        readOnlyHint=False, destructiveHint=False, idempotentHint=True,
    ),
    # Chatter & attachments
    "odoo_chatter_post_message": ToolAnnotation(
        title="Post Message",
        readOnlyHint=False, destructiveHint=False, idempotentHint=False,
    ),
    "odoo_attachments_upload": ToolAnnotation(
        title="Upload Attachment",
        readOnlyHint=False, destructiveHint=False, idempotentHint=False,
    ),
    "odoo_attachments_delete": ToolAnnotation(
        title="Delete Attachment",
        readOnlyHint=False, destructiveHint=True, idempotentHint=True,
    ),
    # Reports
    "odoo_reports_generate": ToolAnnotation(
        title="Generate Report",
        readOnlyHint=True, destructiveHint=False, idempotentHint=True,
    ),
}


def get_annotation(tool_name: str) -> ToolAnnotation | None:
    """Look up the annotation for a tool (REQ-11-17)."""
    return _TOOL_ANNOTATIONS.get(tool_name)
