"""Core toolset — foundational CRUD tools that work on any Odoo model.

Implements REQ-04-01 through REQ-04-38, REQ-03-19.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .base import (
    ANNOTATIONS_DESTRUCTIVE,
    ANNOTATIONS_READ_ONLY,
    ANNOTATIONS_WRITE,
    ANNOTATIONS_WRITE_IDEMPOTENT,
    BaseToolset,
    ToolsetMetadata,
    make_annotations,
    tool_name,
)
from .formatting import normalize_records

logger = logging.getLogger("odoo_mcp.toolsets.core")

# ---------------------------------------------------------------------------
# Safety constants (mirror from Group 2 — these will be imported after merge)
# ---------------------------------------------------------------------------

DEFAULT_MODEL_BLOCKLIST: set[str] = {
    "ir.config_parameter",
    "ir.cron",
    "base.automation",
    "ir.rule",
    "ir.model.access",
    "ir.mail_server",
    "fetchmail.server",
    "payment.provider",
}

DEFAULT_FIELD_BLOCKLIST: set[str] = {
    "password",
    "password_crypt",
    "oauth_access_token",
    "oauth_provider_id",
    "api_key",
    "api_key_ids",
    "totp_secret",
    "totp_enabled",
    "signature",
}

DEFAULT_METHOD_BLOCKLIST: set[str] = {
    "sudo",
    "with_user",
    "with_env",
    "with_context",
    "invalidate_cache",
    "clear_caches",
    "init",
    "uninstall",
    "module_uninstall",
}

NO_KWARGS_METHODS: set[str] = {
    "action_cancel", "action_confirm", "action_draft", "action_done",
    "action_lock", "action_unlock", "button_validate", "button_draft",
    "button_cancel", "button_confirm", "action_post", "action_open",
    "action_set_draft", "action_quotation_send", "action_view_invoice",
    "copy", "name_get", "name_search", "read", "search", "search_read",
    "search_count", "fields_get", "default_get", "onchange",
}

DOMAIN_SYNTAX_HELP = """\
Domain syntax: List of conditions in Odoo domain format.
Each condition is a tuple: [field, operator, value]
Operators: =, !=, >, >=, <, <=, like, ilike, in, not in, child_of, parent_of
Logical: Use '|' for OR, '&' for AND (default), '!' for NOT — in prefix notation.
Examples:
  [] → all records
  [['state', '=', 'draft']] → records where state is draft
  [['name', 'ilike', 'acme']] → records where name contains 'acme' (case-insensitive)
  [['amount', '>=', 1000], ['state', '=', 'posted']] → AND (both conditions)
  ['|', ['state', '=', 'draft'], ['state', '=', 'sent']] → OR (either condition)
  [['partner_id.country_id.code', '=', 'PT']] → related field traversal\
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_mode(config: Any) -> str:
    return getattr(config, "mode", "readonly")


def _get_model_blocklist(config: Any) -> set[str]:
    custom = set(getattr(config, "model_blocklist", []))
    return DEFAULT_MODEL_BLOCKLIST | custom


def _get_model_allowlist(config: Any) -> list[str]:
    return getattr(config, "model_allowlist", [])


def _get_field_blocklist(config: Any) -> set[str]:
    custom = set(getattr(config, "field_blocklist", []))
    return DEFAULT_FIELD_BLOCKLIST | custom


def _get_method_blocklist(config: Any) -> set[str]:
    custom = set(getattr(config, "method_blocklist", []))
    return DEFAULT_METHOD_BLOCKLIST | custom


def _get_write_allowlist(config: Any) -> list[str]:
    return getattr(config, "write_allowlist", [])


def _check_model_access(model: str, config: Any) -> str | None:
    """Return an error message if *model* is blocked, else None."""
    blocklist = _get_model_blocklist(config)
    if model in blocklist:
        return f"Access to model '{model}' is blocked by safety configuration."
    allowlist = _get_model_allowlist(config)
    if allowlist and model not in allowlist:
        return f"Model '{model}' is not in the model allowlist."
    return None


def _check_write_mode(operation: str, model: str, config: Any) -> str | None:
    """Enforce operation mode. Returns error message or None."""
    mode = _get_mode(config)
    if mode == "readonly" and operation not in ("read", "search"):
        return f"'{operation}' not allowed in readonly mode."
    if mode == "restricted":
        if operation in ("create", "write", "execute"):
            write_allowlist = _get_write_allowlist(config)
            if write_allowlist and model not in write_allowlist:
                return (
                    f"'{operation}' on '{model}' not allowed in restricted mode. "
                    f"Allowed models: {', '.join(write_allowlist)}"
                )
        if operation == "unlink":
            return "Delete not allowed in restricted mode."
    return None


def _filter_fields(fields: list[str], config: Any) -> list[str]:
    """Remove blocklisted fields from a field list."""
    blocked = _get_field_blocklist(config)
    return [f for f in fields if f not in blocked]


def _error_response(
    category: str, code: str, message: str, suggestion: str = "", **extra: Any
) -> str:
    resp: dict[str, Any] = {
        "error": True,
        "category": category,
        "code": code,
        "message": message,
        "suggestion": suggestion,
        "retry": category not in ("access", "configuration", "unknown"),
    }
    resp.update(extra)
    return json.dumps(resp)


def _is_hidden(operation: str, config: Any) -> bool:
    """Should the tool be hidden entirely for the current mode? (REQ-11-04/05)."""
    mode = _get_mode(config)
    if mode == "readonly" and operation in ("create", "write", "unlink"):
        return True
    if mode == "restricted" and operation == "unlink":
        return True
    return False


def _format_action_result(result: Any) -> dict[str, Any]:
    """Format method result — detect action dicts (REQ-04-27)."""
    if isinstance(result, dict) and result.get("type", "").startswith("ir.actions."):
        summary_parts = [f"Opens {result.get('res_model', '?')}"]
        if result.get("res_id"):
            summary_parts.append(f"form view for record {result['res_id']}")
        elif result.get("view_mode"):
            summary_parts.append(f"{result['view_mode']} view")
        return {
            "result_type": "action",
            "action": {
                "type": result.get("type", ""),
                "res_model": result.get("res_model", ""),
                "res_id": result.get("res_id"),
                "view_mode": result.get("view_mode", ""),
                "summary": " ".join(summary_parts),
            },
        }
    return {"result_type": "value", "result": result}


# ---------------------------------------------------------------------------
# CoreToolset
# ---------------------------------------------------------------------------

class CoreToolset(BaseToolset):
    """Core CRUD operations on any Odoo model."""

    def metadata(self) -> ToolsetMetadata:
        return ToolsetMetadata(
            name="core",
            description="Core CRUD operations on any Odoo model",
            version="1.0.0",
            required_modules=[],
            min_odoo_version=14,
            tags=["core", "crud"],
        )

    async def register_tools(
        self, server: Any, connection: Any, **kwargs: Any
    ) -> list[str]:
        config = kwargs.get("config")
        registry = kwargs.get("registry")
        registered: list[str] = []

        # Read-only tools — always available
        for name, handler, desc, annotations_kw in self._read_tools(connection, config, registry):
            server.tool(
                name=name,
                description=desc,
                annotations=make_annotations(title=name, **annotations_kw),
            )(handler)
            registered.append(name)

        # Write tools — may be hidden based on mode
        for name, handler, desc, annotations_kw, op in self._write_tools(connection, config):
            if _is_hidden(op, config):
                continue
            server.tool(
                name=name,
                description=desc,
                annotations=make_annotations(title=name, **annotations_kw),
            )(handler)
            registered.append(name)

        return registered

    # ======================================================================
    # Read-only tools
    # ======================================================================

    def _read_tools(self, connection: Any, config: Any, registry: Any):
        """Yield ``(name, handler, description, annotations_kw)`` for read-only tools."""
        yield (
            tool_name("core", "search_read"),
            self._make_search_read(connection, config),
            f"Search records and return field values.\n\n{DOMAIN_SYNTAX_HELP}",
            ANNOTATIONS_READ_ONLY,
        )
        yield (
            tool_name("core", "read"),
            self._make_read(connection, config),
            "Read specific records by ID.",
            ANNOTATIONS_READ_ONLY,
        )
        yield (
            tool_name("core", "count"),
            self._make_count(connection, config),
            f"Count records matching a domain.\n\n{DOMAIN_SYNTAX_HELP}",
            ANNOTATIONS_READ_ONLY,
        )
        yield (
            tool_name("core", "fields_get"),
            self._make_fields_get(connection, config),
            "Get field definitions for a model, formatted for LLM consumption.",
            ANNOTATIONS_READ_ONLY,
        )
        yield (
            tool_name("core", "name_get"),
            self._make_name_get(connection, config),
            "Get display names for record IDs.",
            ANNOTATIONS_READ_ONLY,
        )
        yield (
            tool_name("core", "default_get"),
            self._make_default_get(connection, config),
            "Get default values for a model's fields.",
            ANNOTATIONS_READ_ONLY,
        )
        yield (
            tool_name("core", "list_models"),
            self._make_list_models(connection, config),
            "List available Odoo models with basic metadata.",
            ANNOTATIONS_READ_ONLY,
        )
        yield (
            tool_name("core", "list_toolsets"),
            self._make_list_toolsets(connection, config, registry),
            "List all available toolsets and their tools. Use this to discover what operations are available.",
            ANNOTATIONS_READ_ONLY,
        )
        yield (
            tool_name("core", "deep_search"),
            self._make_deep_search(connection, config),
            "Progressive deep search across Odoo models. Automatically broadens search strategy when initial attempts fail.",
            ANNOTATIONS_READ_ONLY,
        )

    # ---- search_read (REQ-04-01 .. REQ-04-05) ---------------------------

    def _make_search_read(self, connection: Any, config: Any):
        from ..search.domain import DomainValidationError, validate_domain

        async def handler(
            model: str,
            domain: list | None = None,
            fields: list[str] | None = None,
            limit: int = 80,
            offset: int = 0,
            order: str | None = None,
            context: dict | None = None,
        ) -> str:
            # Validate model
            err = _check_model_access(model, config)
            if err:
                return _error_response("access", "ACCESS_DENIED", err)

            domain = domain or []
            try:
                validate_domain(domain)
            except DomainValidationError as exc:
                return _error_response(
                    "validation", "INVALID_DOMAIN", str(exc),
                    suggestion=exc.suggestion or "",
                )

            # Default fields
            if fields is None:
                fields = ["id", "name", "display_name"]

            # Wildcard (REQ-04-02)
            api_fields: list[str] | None = None
            if fields != ["*"]:
                api_fields = _filter_fields(fields, config)
            # else: None → Odoo returns all fields

            # Enforce limit cap (REQ-04-02)
            max_limit = getattr(config, "search_max_limit", 500)
            limit = max(1, min(limit, max_limit))

            kwargs: dict[str, Any] = {
                "fields": api_fields,
                "limit": limit,
                "offset": offset,
            }
            if order:
                kwargs["order"] = order
            if context:
                kwargs["context"] = context

            result = await connection.execute_kw(
                model, "search_read", [domain], kwargs,
            )
            records = result if result else []

            # Normalise (REQ-04-05)
            records = normalize_records(records)

            # Filter blocked fields from results
            blocked = _get_field_blocklist(config)
            for rec in records:
                for bf in blocked:
                    rec.pop(bf, None)

            return json.dumps({
                "records": records,
                "count": len(records),
                "model": model,
                "limit": limit,
                "offset": offset,
                "has_more": len(records) == limit,  # REQ-04-04
            })

        return handler

    # ---- read (REQ-04-06 / REQ-04-07) -----------------------------------

    def _make_read(self, connection: Any, config: Any):
        async def handler(
            model: str,
            ids: list[int],
            fields: list[str] | None = None,
            context: dict | None = None,
        ) -> str:
            err = _check_model_access(model, config)
            if err:
                return _error_response("access", "ACCESS_DENIED", err)

            if len(ids) > 100:
                return _error_response(
                    "validation", "VALIDATION_ERROR",
                    f"Maximum 100 IDs per call, got {len(ids)}.",
                )

            api_fields = _filter_fields(fields, config) if fields else []

            kwargs: dict[str, Any] = {}
            if api_fields:
                kwargs["fields"] = api_fields
            if context:
                kwargs["context"] = context

            try:
                result = await connection.execute_kw(
                    model, "read", [ids], kwargs,
                )
            except Exception as exc:
                # Handle MissingError (REQ-04-07)
                if "MissingError" in str(exc):
                    # Try reading one by one to find existing records
                    records = []
                    missing_ids = []
                    for rid in ids:
                        try:
                            r = await connection.execute_kw(
                                model, "read", [[rid]], kwargs,
                            )
                            if r:
                                records.extend(r)
                        except Exception:
                            missing_ids.append(rid)
                    records = normalize_records(records)
                    return json.dumps({"records": records, "missing_ids": missing_ids})
                raise

            records = normalize_records(result or [])

            # Filter blocked fields
            blocked = _get_field_blocklist(config)
            for rec in records:
                for bf in blocked:
                    rec.pop(bf, None)

            return json.dumps({"records": records, "missing_ids": []})

        return handler

    # ---- count (REQ-04-20 / REQ-04-21) ----------------------------------

    def _make_count(self, connection: Any, config: Any):
        from ..search.domain import DomainValidationError, validate_domain

        async def handler(
            model: str,
            domain: list | None = None,
            context: dict | None = None,
        ) -> str:
            err = _check_model_access(model, config)
            if err:
                return _error_response("access", "ACCESS_DENIED", err)

            domain = domain or []
            try:
                validate_domain(domain)
            except DomainValidationError as exc:
                return _error_response(
                    "validation", "INVALID_DOMAIN", str(exc),
                    suggestion=exc.suggestion or "",
                )

            kwargs: dict[str, Any] = {}
            if context:
                kwargs["context"] = context

            count = await connection.execute_kw(
                model, "search_count", [domain], kwargs,
            )
            return json.dumps({"model": model, "domain": domain, "count": count})

        return handler

    # ---- fields_get (REQ-04-22 .. REQ-04-24) ----------------------------

    def _make_fields_get(self, connection: Any, config: Any):
        async def handler(
            model: str,
            attributes: list[str] | None = None,
            context: dict | None = None,
        ) -> str:
            err = _check_model_access(model, config)
            if err:
                return _error_response("access", "ACCESS_DENIED", err)

            if attributes is None:
                attributes = [
                    "string", "type", "required", "readonly",
                    "help", "selection", "relation",
                ]

            kwargs: dict[str, Any] = {"attributes": attributes}
            if context:
                kwargs["context"] = context

            raw = await connection.execute_kw(
                model, "fields_get", [], kwargs,
            )
            raw = raw or {}

            # Format for LLM (REQ-04-23) and exclude blocklisted fields (REQ-04-24)
            blocked = _get_field_blocklist(config)
            fields_out: dict[str, Any] = {}
            for fname, finfo in raw.items():
                if fname in blocked:
                    continue
                formatted: dict[str, Any] = {}
                if "string" in finfo:
                    formatted["label"] = finfo["string"]
                if "type" in finfo:
                    formatted["type"] = finfo["type"]
                for attr in ("required", "readonly", "relation", "selection", "help"):
                    if attr in finfo and finfo[attr]:
                        formatted[attr] = finfo[attr]
                fields_out[fname] = formatted

            return json.dumps({
                "model": model,
                "fields": fields_out,
                "field_count": len(fields_out),
            })

        return handler

    # ---- name_get (REQ-04-28 / REQ-04-29) --------------------------------

    def _make_name_get(self, connection: Any, config: Any):
        async def handler(model: str, ids: list[int]) -> str:
            err = _check_model_access(model, config)
            if err:
                return _error_response("access", "ACCESS_DENIED", err)

            if len(ids) > 200:
                return _error_response(
                    "validation", "VALIDATION_ERROR",
                    f"Maximum 200 IDs per call, got {len(ids)}.",
                )

            result = await connection.execute_kw(
                model, "name_get", [ids], {},
            )
            names = [{"id": r[0], "name": r[1]} for r in (result or [])]
            return json.dumps({"model": model, "names": names})

        return handler

    # ---- default_get (REQ-04-30 / REQ-04-31) -----------------------------

    def _make_default_get(self, connection: Any, config: Any):
        async def handler(
            model: str,
            fields: list[str] | None = None,
            context: dict | None = None,
        ) -> str:
            err = _check_model_access(model, config)
            if err:
                return _error_response("access", "ACCESS_DENIED", err)

            api_fields = fields or []
            kwargs: dict[str, Any] = {}
            if context:
                kwargs["context"] = context

            result = await connection.execute_kw(
                model, "default_get", [api_fields], kwargs,
            )
            return json.dumps({"model": model, "defaults": result or {}})

        return handler

    # ---- list_models (REQ-04-32 .. REQ-04-34) ----------------------------

    def _make_list_models(self, connection: Any, config: Any):
        async def handler(
            filter: str | None = None,
            transient: bool = False,
        ) -> str:
            domain: list[Any] = []
            if filter:
                domain.append(("model", "ilike", filter))
            if not transient:
                domain.append(("transient", "=", False))

            result = await connection.execute_kw(
                "ir.model",
                "search_read",
                [domain],
                {"fields": ["model", "name", "transient", "field_id"]},
            )
            models_raw = result or []

            # Exclude blocklisted models (REQ-04-34)
            blocked = _get_model_blocklist(config)
            allowlist = _get_model_allowlist(config)

            models_out = []
            for m in models_raw:
                model_name = m.get("model", "")
                if model_name in blocked:
                    continue
                if allowlist and model_name not in allowlist:
                    continue

                # Check read access (REQ-04-34)
                try:
                    has_access = await connection.execute_kw(
                        model_name, "check_access_rights",
                        ["read"],
                        {"raise_exception": False},
                    )
                    if not has_access:
                        continue
                except Exception:
                    continue

                field_ids = m.get("field_id", [])
                field_count = len(field_ids) if isinstance(field_ids, list) else 0

                # Determine access string
                access_parts = ["read"]
                for right in ("write", "create", "unlink"):
                    try:
                        ok = await connection.execute_kw(
                            model_name, "check_access_rights",
                            [right],
                            {"raise_exception": False},
                        )
                        if ok:
                            access_parts.append(right)
                    except Exception:
                        pass

                models_out.append({
                    "model": model_name,
                    "name": m.get("name", ""),
                    "transient": m.get("transient", False),
                    "field_count": field_count,
                    "access": ",".join(access_parts),
                })

            return json.dumps({"models": models_out, "count": len(models_out)})

        return handler

    # ---- list_toolsets (REQ-03-19) ---------------------------------------

    def _make_list_toolsets(self, connection: Any, config: Any, registry: Any):
        async def handler() -> str:
            toolsets_out = []
            report = registry.get_report() if registry else None
            if report:
                for r in report.results:
                    if r.status == "registered":
                        toolsets_out.append({
                            "name": r.name,
                            "description": "",
                            "tools": r.tools_registered,
                            "odoo_modules": [],
                            "status": "active",
                        })
            else:
                # Fallback if no report available
                for meta in (registry.get_registered_toolsets() if registry else []):
                    toolsets_out.append({
                        "name": meta.name,
                        "description": meta.description,
                        "tools": [],
                        "odoo_modules": meta.required_modules,
                        "status": "active",
                    })

            odoo_version = getattr(connection, "odoo_version", "unknown")
            odoo_url = getattr(config, "odoo_url", "unknown") if config else "unknown"
            total = sum(len(t["tools"]) for t in toolsets_out)
            return json.dumps({
                "toolsets": toolsets_out,
                "total_tools": total,
                "odoo_version": str(odoo_version),
                "connection": odoo_url,
            })

        return handler

    # ---- deep_search (REQ-08-03) ----------------------------------------

    def _make_deep_search(self, connection: Any, config: Any):
        from ..search.progressive import ProgressiveSearch

        async def handler(
            query: str,
            model: str | None = None,
            max_depth: int = 3,
            limit: int = 20,
            fields: list[str] | None = None,
            exhaustive: bool = False,
        ) -> str:
            engine = ProgressiveSearch(connection, config)
            result = await engine.search(
                query=query,
                model=model,
                max_depth=max_depth,
                limit=limit,
                fields=fields,
                exhaustive=exhaustive,
            )
            return json.dumps(result)

        return handler

    # ======================================================================
    # Write tools
    # ======================================================================

    def _write_tools(self, connection: Any, config: Any):
        """Yield ``(name, handler, description, annotations_kw, operation)``."""
        yield (
            tool_name("core", "create"),
            self._make_create(connection, config),
            "Create a new record.",
            ANNOTATIONS_WRITE,
            "create",
        )
        yield (
            tool_name("core", "write"),
            self._make_write(connection, config),
            "Update existing record(s).",
            ANNOTATIONS_WRITE_IDEMPOTENT,
            "write",
        )
        yield (
            tool_name("core", "unlink"),
            self._make_unlink(connection, config),
            "Delete record(s). Only available in full mode.",
            ANNOTATIONS_DESTRUCTIVE,
            "unlink",
        )
        yield (
            tool_name("core", "execute"),
            self._make_execute(connection, config),
            "Execute any callable method on an Odoo model.",
            ANNOTATIONS_WRITE,
            "execute",
        )

    # ---- create (REQ-04-08 .. REQ-04-11) --------------------------------

    def _make_create(self, connection: Any, config: Any):
        async def handler(
            model: str,
            values: dict,
            context: dict | None = None,
        ) -> str:
            err = _check_model_access(model, config)
            if err:
                return _error_response("access", "ACCESS_DENIED", err)

            err = _check_write_mode("create", model, config)
            if err:
                return _error_response("access", "ACCESS_DENIED", err)

            # Validate fields not in blocklist
            blocked = _get_field_blocklist(config)
            bad = [f for f in values if f in blocked]
            if bad:
                return _error_response(
                    "validation", "VALIDATION_ERROR",
                    f"Blocked field(s) in values: {', '.join(bad)}",
                    suggestion="Remove blocked fields from the values.",
                )

            kwargs: dict[str, Any] = {}
            if context:
                kwargs["context"] = context

            try:
                new_id = await connection.execute_kw(
                    model, "create", [values], kwargs,
                )
            except Exception as exc:
                return _error_response(
                    "validation", "VALIDATION_ERROR",
                    str(exc),
                    suggestion="Use odoo_core_fields_get to see required fields and valid values.",
                    original_error=str(exc),
                )

            return json.dumps({
                "id": new_id,
                "model": model,
                "message": f"Created {model} record with ID {new_id}",
            })

        return handler

    # ---- write (REQ-04-12 .. REQ-04-15) ---------------------------------

    def _make_write(self, connection: Any, config: Any):
        async def handler(
            model: str,
            ids: list[int],
            values: dict,
            context: dict | None = None,
        ) -> str:
            err = _check_model_access(model, config)
            if err:
                return _error_response("access", "ACCESS_DENIED", err)

            if len(ids) > 100:
                return _error_response(
                    "validation", "VALIDATION_ERROR",
                    f"Maximum 100 IDs per call, got {len(ids)}.",
                )

            err = _check_write_mode("write", model, config)
            if err:
                return _error_response("access", "ACCESS_DENIED", err)

            # Validate fields (REQ-04-14)
            blocked = _get_field_blocklist(config)
            bad = [f for f in values if f in blocked]
            if bad:
                return _error_response(
                    "validation", "VALIDATION_ERROR",
                    f"Blocked field(s) in values: {', '.join(bad)}",
                    suggestion="Remove blocked fields from the values.",
                )

            kwargs: dict[str, Any] = {}
            if context:
                kwargs["context"] = context

            try:
                await connection.execute_kw(
                    model, "write", [ids, values], kwargs,
                )
            except Exception as exc:
                return _error_response(
                    "validation", "VALIDATION_ERROR",
                    str(exc),
                    suggestion="Use odoo_core_fields_get to check field types and constraints.",
                    original_error=str(exc),
                )

            return json.dumps({
                "success": True,
                "model": model,
                "ids": ids,
                "message": f"Updated {len(ids)} {model} record(s)",
            })

        return handler

    # ---- unlink (REQ-04-16 .. REQ-04-19) --------------------------------

    def _make_unlink(self, connection: Any, config: Any):
        async def handler(
            model: str,
            ids: list[int],
            context: dict | None = None,
        ) -> str:
            err = _check_model_access(model, config)
            if err:
                return _error_response("access", "ACCESS_DENIED", err)

            if len(ids) > 50:
                return _error_response(
                    "validation", "VALIDATION_ERROR",
                    f"Maximum 50 IDs per call, got {len(ids)}.",
                )

            # Only full mode (REQ-04-17)
            err = _check_write_mode("unlink", model, config)
            if err:
                return _error_response("access", "ACCESS_DENIED", err)

            kwargs: dict[str, Any] = {}
            if context:
                kwargs["context"] = context

            try:
                await connection.execute_kw(
                    model, "unlink", [ids], kwargs,
                )
            except Exception as exc:
                return _error_response(
                    "validation", "VALIDATION_ERROR",
                    str(exc),
                    original_error=str(exc),
                )

            # Audit logging (REQ-04-17) — delegate to Group 2's audit module after merge
            logger.info("AUDIT: unlink %s ids=%s", model, ids)

            return json.dumps({
                "success": True,
                "model": model,
                "deleted_ids": ids,
                "message": f"Deleted {len(ids)} {model} record(s)",
            })

        return handler

    # ---- execute (REQ-04-25 .. REQ-04-27) --------------------------------

    def _make_execute(self, connection: Any, config: Any):
        async def handler(
            model: str,
            method: str,
            args: list | None = None,
            kwargs: dict | None = None,
            context: dict | None = None,
        ) -> str:
            err = _check_model_access(model, config)
            if err:
                return _error_response("access", "ACCESS_DENIED", err)

            # Private methods rejected (REQ-04-26.1)
            if method.startswith("_"):
                return _error_response(
                    "access", "ACCESS_DENIED",
                    f"Private methods (starting with '_') cannot be called via RPC: '{method}'",
                )

            # Method blocklist (REQ-04-26.2)
            method_bl = _get_method_blocklist(config)
            if method in method_bl:
                return _error_response(
                    "access", "ACCESS_DENIED",
                    f"Method '{method}' is blocked by safety configuration.",
                )

            # Mode check (REQ-04-26.3)
            mode = _get_mode(config)
            read_methods = {
                "read", "search", "search_read", "search_count",
                "fields_get", "default_get", "name_get", "name_search",
                "check_access_rights", "check_access_rule",
            }
            if mode == "readonly" and method not in read_methods:
                return _error_response(
                    "access", "ACCESS_DENIED",
                    f"Method '{method}' not allowed in readonly mode.",
                )

            if mode == "restricted":
                err = _check_write_mode("execute", model, config)
                if err and method not in read_methods:
                    return _error_response("access", "ACCESS_DENIED", err)

            args = args or []
            kwargs = kwargs or {}

            # Strip kwargs for known methods (REQ-04-26.4)
            if method in NO_KWARGS_METHODS:
                kwargs = {}

            if context:
                kwargs["context"] = context

            try:
                result = await connection.execute_kw(
                    model, method, args, kwargs,
                )
            except Exception as exc:
                return _error_response(
                    "unknown", "UNKNOWN_ERROR",
                    str(exc),
                    suggestion="Check the method name, arguments, and model state.",
                    original_error=str(exc),
                )

            # Format result (REQ-04-27)
            formatted = _format_action_result(result)
            return json.dumps(formatted)

        return handler
