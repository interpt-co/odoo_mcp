"""MCP Resource Provider.

Implements REQ-06-02 through REQ-06-16, REQ-06-22, REQ-06-23, REQ-07-20.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from odoo_mcp.resources.uri import (
    OdooUri,
    OdooUriError,
    parse_odoo_uri,
    DEFAULT_LIMIT,
    MAX_LIMIT,
)
from odoo_mcp.registry.model_registry import (
    ModelRegistry,
    ModelInfo,
    OdooProtocolInterface,
)

logger = logging.getLogger(__name__)

MAX_SUBSCRIPTIONS = 50


@dataclass
class SubscriptionEntry:
    """Tracks a resource subscription."""

    uri: str
    model: str | None
    record_id: int | None
    last_write_date: str | None = None


@dataclass
class ResourceContext:
    """Dependencies injected into the resource provider."""

    registry: ModelRegistry | None = None
    protocol: OdooProtocolInterface | None = None
    server_version: str = ""
    server_edition: str = ""
    database: str = ""
    url: str = ""
    protocol_name: str = ""
    user_uid: int = 0
    user_name: str = ""
    mcp_server_version: str = "0.1.0"
    safety_config: dict[str, Any] = field(default_factory=dict)
    toolsets: list[dict[str, Any]] = field(default_factory=list)
    installed_modules: list[dict[str, Any]] = field(default_factory=list)
    model_blocklist: set[str] = field(default_factory=set)
    field_blocklist: set[str] = field(default_factory=set)
    readonly_mode: bool = False


class ResourceProvider:
    """Provides MCP resources for the Odoo MCP server.

    Handles static resources, resource templates, and subscriptions.
    """

    def __init__(self, context: ResourceContext) -> None:
        self._ctx = context
        self._subscriptions: dict[str, SubscriptionEntry] = {}
        self._poll_task: asyncio.Task | None = None
        self._poll_interval: float = 60.0
        self._notification_callback: Any = None

    @property
    def context(self) -> ResourceContext:
        return self._ctx

    def set_notification_callback(self, callback: Any) -> None:
        self._notification_callback = callback

    # -- Resource definitions for MCP registration --

    def get_resource_definitions(self) -> list[dict[str, Any]]:
        """Return static resource definitions."""
        return [
            {
                "uri": "odoo://system/info",
                "name": "Odoo Instance Info",
                "mimeType": "application/json",
                "description": "Connection details, Odoo version, and server capabilities",
            },
            {
                "uri": "odoo://system/modules",
                "name": "Installed Modules",
                "mimeType": "application/json",
                "description": "List of installed Odoo modules",
            },
            {
                "uri": "odoo://system/toolsets",
                "name": "Available Toolsets",
                "mimeType": "application/json",
                "description": "Registered toolsets and their tools",
            },
            {
                "uri": "odoo://config/safety",
                "name": "Safety Configuration",
                "mimeType": "application/json",
                "description": "Current safety configuration and access rules",
            },
        ]

    def get_resource_templates(self) -> list[dict[str, Any]]:
        """Return resource template definitions."""
        return [
            {
                "uriTemplate": "odoo://model/{model_name}/fields",
                "name": "Model Fields",
                "mimeType": "application/json",
                "description": "Field definitions for an Odoo model",
            },
            {
                "uriTemplate": "odoo://model/{model_name}/methods",
                "name": "Model Methods",
                "mimeType": "application/json",
                "description": "Available methods for an Odoo model",
            },
            {
                "uriTemplate": "odoo://model/{model_name}/states",
                "name": "Model States",
                "mimeType": "application/json",
                "description": "State machine / workflow for an Odoo model",
            },
            {
                "uriTemplate": "odoo://record/{model_name}/{record_id}",
                "name": "Odoo Record",
                "mimeType": "application/json",
                "description": "Read a specific Odoo record by model and ID",
            },
            {
                "uriTemplate": "odoo://record/{model_name}",
                "name": "Record Listing",
                "mimeType": "application/json",
                "description": "Search and list records with optional domain filter",
            },
        ]

    # -- Resource resolution --

    async def read_resource(self, uri: str) -> dict[str, Any]:
        """Resolve a resource URI and return its content."""
        try:
            parsed = parse_odoo_uri(uri)
        except OdooUriError as exc:
            return {"error": True, "message": str(exc)}

        # Check blocklist
        if parsed.model_name and parsed.model_name in self._ctx.model_blocklist:
            return {
                "error": True,
                "code": "MODEL_BLOCKED",
                "message": f"Model '{parsed.model_name}' is blocked by safety configuration",
            }

        if parsed.category == "system":
            return await self._read_system_resource(parsed)
        elif parsed.category == "config":
            return await self._read_config_resource(parsed)
        elif parsed.category == "model":
            return await self._read_model_resource(parsed)
        elif parsed.category == "record":
            return await self._read_record_resource(parsed)
        else:
            return {"error": True, "message": f"Unknown category: {parsed.category}"}

    # -- Static resources --

    async def _read_system_resource(self, parsed: OdooUri) -> dict[str, Any]:
        rt = parsed.resource_type
        if rt == "info":
            return {
                "server_version": self._ctx.server_version,
                "server_edition": self._ctx.server_edition,
                "database": self._ctx.database,
                "url": self._ctx.url,
                "protocol": self._ctx.protocol_name,
                "user": {"uid": self._ctx.user_uid, "name": self._ctx.user_name},
                "mcp_server_version": self._ctx.mcp_server_version,
            }
        elif rt == "modules":
            return {
                "modules": self._ctx.installed_modules,
                "count": len(self._ctx.installed_modules),
            }
        elif rt == "toolsets":
            return {"toolsets": self._ctx.toolsets}
        else:
            return {"error": True, "message": f"Unknown system resource: {rt}"}

    async def _read_config_resource(self, parsed: OdooUri) -> dict[str, Any]:
        rt = parsed.resource_type
        if rt == "safety":
            return self._ctx.safety_config or {
                "operation_mode": "restricted",
                "model_allowlist": [],
                "model_blocklist": list(self._ctx.model_blocklist),
                "rate_limit": {"calls_per_minute": 60},
            }
        return {"error": True, "message": f"Unknown config resource: {rt}"}

    # -- Model metadata resources (REQ-07-20) --

    async def _read_model_resource(self, parsed: OdooUri) -> dict[str, Any]:
        model_name = parsed.model_name
        rt = parsed.resource_type
        reg = self._ctx.registry
        if reg is None:
            return {"error": True, "message": "Registry not available"}

        model = reg.get_model(model_name)
        if model is None:
            return {"error": True, "message": f"Model '{model_name}' not found in registry"}

        if rt == "fields":
            fields_out = {}
            for fname, finfo in model.fields.items():
                # Filter blocked fields
                fq = f"{model_name}.{fname}"
                if fq in self._ctx.field_blocklist or fname in self._ctx.field_blocklist:
                    continue
                if finfo.type == "binary":
                    continue
                fields_out[fname] = finfo.to_dict()
            return {"model": model_name, "fields": fields_out, "count": len(fields_out)}

        elif rt == "methods":
            methods_out = [
                m.to_dict() for m in model.methods.values()
            ]
            return {"model": model_name, "methods": methods_out}

        elif rt == "states":
            if model.states is None:
                return {"model": model_name, "state_field": None, "states": [], "transitions": []}
            return {
                "model": model_name,
                "state_field": "state",
                "states": [{"value": s[0], "label": s[1]} for s in model.states],
                "transitions": [],
            }

        return {"error": True, "message": f"Unknown model resource type: {rt}"}

    # -- Record resources --

    async def _read_record_resource(self, parsed: OdooUri) -> dict[str, Any]:
        model_name = parsed.model_name
        if model_name is None:
            return {"error": True, "message": "No model name in URI"}

        protocol = self._ctx.protocol
        if protocol is None:
            return {"error": True, "message": "No Odoo connection available"}

        # Determine fields to read
        read_fields = self._get_read_fields(model_name)

        record_id = parsed.record_id
        if record_id is not None:
            # Single record read
            try:
                records = await protocol.search_read(
                    model_name,
                    [("id", "=", record_id)],
                    read_fields,
                    limit=1,
                )
            except Exception as exc:
                return {
                    "error": True,
                    "code": "ACCESS_ERROR",
                    "message": f"Cannot read {model_name}/{record_id}: {exc}",
                }
            if not records:
                return {"error": True, "message": f"Record {model_name}/{record_id} not found"}
            return {"model": model_name, "record": records[0]}
        else:
            # Record listing with domain
            domain = parsed.domain or []
            limit = parsed.limit
            try:
                records = await protocol.search_read(
                    model_name,
                    domain,
                    read_fields,
                    limit=limit,
                )
            except Exception as exc:
                return {
                    "error": True,
                    "code": "ACCESS_ERROR",
                    "message": f"Cannot search {model_name}: {exc}",
                }
            return {
                "model": model_name,
                "records": records,
                "count": len(records),
                "limit": limit,
            }

    def _get_read_fields(self, model_name: str) -> list[str]:
        """Determine which fields to read, excluding binary and blocked fields."""
        reg = self._ctx.registry
        if reg is None:
            return []  # Let Odoo return default fields

        model = reg.get_model(model_name)
        if model is None:
            return []

        fields = []
        for fname, finfo in model.fields.items():
            if finfo.type == "binary":
                continue
            fq = f"{model_name}.{fname}"
            if fq in self._ctx.field_blocklist or fname in self._ctx.field_blocklist:
                continue
            fields.append(fname)
        return fields

    # -- Subscriptions (REQ-06-13 through REQ-06-16) --

    async def subscribe(self, uri: str) -> dict[str, Any]:
        """Subscribe to resource changes."""
        if len(self._subscriptions) >= MAX_SUBSCRIPTIONS:
            return {
                "error": True,
                "code": "SUBSCRIPTION_LIMIT",
                "message": f"Maximum {MAX_SUBSCRIPTIONS} subscriptions reached",
            }

        try:
            parsed = parse_odoo_uri(uri)
        except OdooUriError as exc:
            return {"error": True, "message": str(exc)}

        # Only certain resources support subscriptions (REQ-06-15)
        supported = False
        model = None
        record_id = None
        if parsed.category == "record" and parsed.record_id is not None:
            supported = True
            model = parsed.model_name
            record_id = parsed.record_id
        elif parsed.category == "system" and parsed.resource_type == "info":
            supported = True

        if not supported:
            return {"error": True, "message": f"Subscriptions not supported for {uri}"}

        self._subscriptions[uri] = SubscriptionEntry(
            uri=uri, model=model, record_id=record_id,
        )

        # Start polling if not already running
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = asyncio.create_task(self._poll_loop())

        return {"subscribed": True, "uri": uri}

    async def unsubscribe(self, uri: str) -> dict[str, Any]:
        """Unsubscribe from a resource."""
        if uri in self._subscriptions:
            del self._subscriptions[uri]
        if not self._subscriptions and self._poll_task:
            self._poll_task.cancel()
            self._poll_task = None
        return {"unsubscribed": True, "uri": uri}

    async def _poll_loop(self) -> None:
        """Poll subscribed resources for changes (REQ-06-14)."""
        while self._subscriptions:
            await asyncio.sleep(self._poll_interval)
            for uri, entry in list(self._subscriptions.items()):
                if entry.model and entry.record_id and self._ctx.protocol:
                    try:
                        records = await self._ctx.protocol.search_read(
                            entry.model,
                            [("id", "=", entry.record_id)],
                            ["write_date"],
                            limit=1,
                        )
                        if records:
                            new_wd = str(records[0].get("write_date", ""))
                            if entry.last_write_date and new_wd != entry.last_write_date:
                                if self._notification_callback:
                                    await self._notification_callback(uri)
                            entry.last_write_date = new_wd
                    except Exception as exc:
                        logger.debug("Poll error for %s: %s", uri, exc)

    @property
    def subscription_count(self) -> int:
        return len(self._subscriptions)
