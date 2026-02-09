"""Registry data models and ModelRegistry access API.

Implements SPEC-07: Model/Field/Method Registry.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# REQ-07-07: Default target models for introspection
# ---------------------------------------------------------------------------

DEFAULT_INTROSPECTION_MODELS: list[str] = [
    "res.partner", "res.users", "res.company",
    "sale.order", "sale.order.line",
    "purchase.order", "purchase.order.line",
    "account.move", "account.move.line",
    "stock.picking", "stock.move", "stock.move.line",
    "stock.quant", "stock.warehouse", "stock.location",
    "product.template", "product.product", "product.category",
    "crm.lead", "crm.stage",
    "helpdesk.ticket", "helpdesk.stage", "helpdesk.team",
    "project.project", "project.task", "project.milestone",
    "hr.employee", "hr.department", "hr.leave",
    "calendar.event",
    "mail.message", "mail.activity",
    "ir.attachment",
]

# ---------------------------------------------------------------------------
# REQ-07-17: Methods known to NOT accept keyword arguments
# ---------------------------------------------------------------------------

NO_KWARGS_METHODS: set[str] = {
    "action_cancel", "action_confirm", "action_draft", "action_done",
    "action_lock", "action_unlock", "button_validate", "button_draft",
    "button_cancel", "button_confirm", "action_post", "action_open",
    "action_set_draft", "action_quotation_send", "action_view_invoice",
    "copy", "name_get", "name_search", "read", "search", "search_read",
    "search_count", "fields_get", "default_get", "onchange",
}

# ---------------------------------------------------------------------------
# REQ-07-19: Field type reference mapping
# ---------------------------------------------------------------------------

FIELD_TYPE_MAP: dict[str, dict[str, str]] = {
    "char":       {"python": "str",       "json": "string",  "notes": ""},
    "text":       {"python": "str",       "json": "string",  "notes": "Multi-line"},
    "html":       {"python": "str",       "json": "string",  "notes": "HTML content"},
    "integer":    {"python": "int",       "json": "integer", "notes": ""},
    "float":      {"python": "float",     "json": "number",  "notes": ""},
    "monetary":   {"python": "float",     "json": "number",  "notes": "Has currency_field"},
    "boolean":    {"python": "bool",      "json": "boolean", "notes": ""},
    "date":       {"python": "str",       "json": "string",  "notes": "Format: YYYY-MM-DD"},
    "datetime":   {"python": "str",       "json": "string",  "notes": "Format: YYYY-MM-DD HH:MM:SS (UTC)"},
    "binary":     {"python": "str",       "json": "string",  "notes": "Base64 encoded"},
    "selection":  {"python": "str",       "json": "string",  "notes": "Value from selection list"},
    "many2one":   {"python": "int/list",  "json": "integer", "notes": "Returns [id, name] or id"},
    "one2many":   {"python": "list[int]", "json": "array",   "notes": "List of IDs"},
    "many2many":  {"python": "list[int]", "json": "array",   "notes": "List of IDs"},
    "reference":  {"python": "str",       "json": "string",  "notes": 'Format: "model,id"'},
    "properties": {"python": "dict",      "json": "object",  "notes": "Dynamic properties (Odoo 17+)"},
}

# ---------------------------------------------------------------------------
# REQ-07-01: Registry data model
# ---------------------------------------------------------------------------


@dataclass
class FieldInfo:
    """Metadata for a single Odoo model field."""

    name: str
    label: str
    type: str
    required: bool = False
    readonly: bool = False
    store: bool = True
    help: str | None = None
    relation: str | None = None
    selection: list[tuple[str, str]] | None = None
    default: Any | None = None
    groups: str | None = None
    compute: bool = False
    depends: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if d["selection"] is not None:
            d["selection"] = [list(s) for s in d["selection"]]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FieldInfo:
        d = dict(data)
        if d.get("selection") is not None:
            d["selection"] = [tuple(s) for s in d["selection"]]
        if d.get("depends") is not None:
            d["depends"] = list(d["depends"])
        return cls(**d)


@dataclass
class MethodInfo:
    """Metadata for a model method (action_* / button_*)."""

    name: str
    description: str = ""
    accepts_kwargs: bool = True
    decorator: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MethodInfo:
        return cls(**data)


@dataclass
class ModelInfo:
    """Metadata for an Odoo model."""

    model: str
    name: str
    description: str | None = None
    transient: bool = False
    fields: dict[str, FieldInfo] = field(default_factory=dict)
    methods: dict[str, MethodInfo] = field(default_factory=dict)
    states: list[tuple[str, str]] | None = None
    parent_models: list[str] = field(default_factory=list)
    has_chatter: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "name": self.name,
            "description": self.description,
            "transient": self.transient,
            "fields": {k: v.to_dict() for k, v in self.fields.items()},
            "methods": {k: v.to_dict() for k, v in self.methods.items()},
            "states": [list(s) for s in self.states] if self.states else None,
            "parent_models": self.parent_models,
            "has_chatter": self.has_chatter,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelInfo:
        fields_data = {
            k: FieldInfo.from_dict({**v, "name": v.get("name", k)})
            for k, v in data.get("fields", {}).items()
        }
        methods_data = {
            k: MethodInfo.from_dict({**v, "name": v.get("name", k)})
            for k, v in data.get("methods", {}).items()
        }
        states = None
        if data.get("states") is not None:
            states = [tuple(s) for s in data["states"]]
        return cls(
            model=data["model"],
            name=data.get("name", data["model"]),
            description=data.get("description"),
            transient=data.get("transient", False),
            fields=fields_data,
            methods=methods_data,
            states=states,
            parent_models=data.get("parent_models", []),
            has_chatter=data.get("has_chatter", False),
        )


@dataclass
class Registry:
    """Complete model registry."""

    models: dict[str, ModelInfo] = field(default_factory=dict)
    version: str = ""
    build_mode: str = "dynamic"
    build_timestamp: str = ""
    model_count: int = 0
    field_count: int = 0

    def update_counts(self) -> None:
        self.model_count = len(self.models)
        self.field_count = sum(len(m.fields) for m in self.models.values())

    def to_dict(self) -> dict[str, Any]:
        self.update_counts()
        return {
            "version": self.version,
            "build_mode": self.build_mode,
            "build_timestamp": self.build_timestamp,
            "model_count": self.model_count,
            "field_count": self.field_count,
            "models": {k: v.to_dict() for k, v in self.models.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Registry:
        models = {
            k: ModelInfo.from_dict({**v, "model": v.get("model", k)})
            for k, v in data.get("models", {}).items()
        }
        reg = cls(
            models=models,
            version=data.get("version", ""),
            build_mode=data.get("build_mode", "static"),
            build_timestamp=data.get("build_timestamp", ""),
        )
        reg.update_counts()
        return reg


# ---------------------------------------------------------------------------
# Protocol interface for Odoo API calls
# ---------------------------------------------------------------------------


class OdooProtocolInterface(Protocol):
    """Minimal interface for making Odoo RPC calls."""

    async def search_read(
        self, model: str, domain: list, fields: list[str], **kwargs: Any
    ) -> list[dict[str, Any]]: ...

    async def fields_get(
        self, model: str, attributes: list[str] | None = None
    ) -> dict[str, Any]: ...

    async def execute_kw(
        self, model: str, method: str, args: list, kwargs: dict | None = None
    ) -> Any: ...


# ---------------------------------------------------------------------------
# REQ-07-16: Registry Access API
# ---------------------------------------------------------------------------


class ModelRegistry:
    """Central registry providing query access to model/field/method metadata."""

    def __init__(self) -> None:
        self._registry: Registry = Registry()
        self._lock = threading.RLock()
        self._existence_cache: dict[str, bool] = {}
        self._protocol: OdooProtocolInterface | None = None

    @property
    def registry(self) -> Registry:
        with self._lock:
            return self._registry

    def set_protocol(self, protocol: OdooProtocolInterface) -> None:
        self._protocol = protocol

    # -- Query methods (REQ-07-16) --

    def get_model(self, model_name: str) -> ModelInfo | None:
        with self._lock:
            return self._registry.models.get(model_name)

    def get_field(self, model_name: str, field_name: str) -> FieldInfo | None:
        with self._lock:
            model = self._registry.models.get(model_name)
            if model is None:
                return None
            return model.fields.get(field_name)

    def get_method(self, model_name: str, method_name: str) -> MethodInfo | None:
        with self._lock:
            model = self._registry.models.get(model_name)
            if model is None:
                return None
            return model.methods.get(method_name)

    def list_models(self, filter: str | None = None) -> list[ModelInfo]:
        with self._lock:
            models = list(self._registry.models.values())
        if filter:
            fl = filter.lower()
            models = [
                m for m in models
                if fl in m.model.lower()
                or fl in m.name.lower()
                or (m.description and fl in m.description.lower())
            ]
        return models

    def get_required_fields(self, model_name: str) -> list[FieldInfo]:
        with self._lock:
            model = self._registry.models.get(model_name)
            if model is None:
                return []
            return [f for f in model.fields.values() if f.required]

    def get_state_field(self, model_name: str) -> FieldInfo | None:
        with self._lock:
            model = self._registry.models.get(model_name)
            if model is None:
                return None
            return model.fields.get("state")

    def get_relational_fields(self, model_name: str) -> list[FieldInfo]:
        with self._lock:
            model = self._registry.models.get(model_name)
            if model is None:
                return []
            return [
                f for f in model.fields.values()
                if f.type in ("many2one", "one2many", "many2many")
            ]

    def method_accepts_kwargs(self, method_name: str) -> bool:
        """REQ-07-18: Check if a method accepts keyword arguments."""
        return method_name not in NO_KWARGS_METHODS

    async def model_exists(self, model_name: str) -> bool:
        """REQ-07-13: Fast model existence check with caching."""
        if model_name in self._existence_cache:
            return self._existence_cache[model_name]
        with self._lock:
            if model_name in self._registry.models:
                self._existence_cache[model_name] = True
                return True
        if self._protocol is not None:
            try:
                await self._protocol.execute_kw(
                    model_name, "search_count", [[]], {"limit": 0}
                )
                self._existence_cache[model_name] = True
                return True
            except Exception:
                self._existence_cache[model_name] = False
                return False
        self._existence_cache[model_name] = False
        return False

    # -- Registry population methods --

    def load_static(self, registry: Registry) -> None:
        """Load a pre-built static registry."""
        with self._lock:
            self._registry = registry
            self._existence_cache.clear()

    async def build_dynamic(
        self,
        protocol: OdooProtocolInterface,
        target_models: list[str] | None = None,
        timeout: float = 60.0,
    ) -> Registry:
        """REQ-07-09 through REQ-07-12: Build registry from live Odoo."""
        self._protocol = protocol
        models_to_introspect = target_models or DEFAULT_INTROSPECTION_MODELS
        semaphore = asyncio.Semaphore(5)
        registry = Registry(
            version="",
            build_mode="dynamic",
            build_timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # Step 1: Get installed modules
        try:
            modules = await protocol.search_read(
                "ir.module.module",
                [("state", "=", "installed")],
                ["name", "shortdesc"],
            )
            logger.info("Found %d installed modules", len(modules))
        except Exception as exc:
            logger.warning("Failed to get installed modules: %s", exc)

        # Step 2: Discover accessible models
        try:
            ir_models = await protocol.search_read(
                "ir.model",
                [("model", "in", models_to_introspect)],
                ["model", "name", "info", "transient"],
            )
            accessible = {m["model"]: m for m in ir_models}
        except Exception as exc:
            logger.warning("Failed to get model list: %s", exc)
            accessible = {}

        # Step 3: Introspect each model
        async def introspect_model(model_name: str) -> ModelInfo | None:
            meta = accessible.get(model_name, {})
            async with semaphore:
                try:
                    fields_data = await protocol.fields_get(
                        model_name,
                        attributes=[
                            "string", "type", "required", "readonly",
                            "store", "help", "relation", "selection",
                        ],
                    )
                except Exception as exc:
                    logger.warning("Failed to introspect %s: %s", model_name, exc)
                    return None

            fields: dict[str, FieldInfo] = {}
            for fname, fdata in fields_data.items():
                sel = None
                if fdata.get("selection"):
                    sel = [(str(s[0]), str(s[1])) for s in fdata["selection"]]
                fields[fname] = FieldInfo(
                    name=fname,
                    label=fdata.get("string", fname),
                    type=fdata.get("type", "char"),
                    required=fdata.get("required", False),
                    readonly=fdata.get("readonly", False),
                    store=fdata.get("store", True),
                    help=fdata.get("help") or None,
                    relation=fdata.get("relation") or None,
                    selection=sel,
                )

            states = None
            if "state" in fields and fields["state"].selection:
                states = fields["state"].selection

            has_chatter = "message_ids" in fields
            parent_models: list[str] = []
            if has_chatter:
                parent_models.append("mail.thread")
            if "activity_ids" in fields:
                parent_models.append("mail.activity.mixin")

            return ModelInfo(
                model=model_name,
                name=meta.get("name", model_name),
                description=meta.get("info") or None,
                transient=meta.get("transient", False),
                fields=fields,
                methods={},
                states=states,
                parent_models=parent_models,
                has_chatter=has_chatter,
            )

        tasks = [introspect_model(m) for m in models_to_introspect]
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("Introspection timed out after %.0fs", timeout)
            results = []

        for result in results:
            if isinstance(result, ModelInfo):
                registry.models[result.model] = result
            elif isinstance(result, Exception):
                logger.debug("Introspection error: %s", result)

        registry.update_counts()
        logger.info(
            "Dynamic registry: %d models, %d fields",
            registry.model_count, registry.field_count,
        )
        with self._lock:
            self._registry = registry
            self._existence_cache.clear()
        return registry

    def merge(self, static: Registry, dynamic: Registry) -> Registry:
        """REQ-07-14, REQ-07-15: Merge static and dynamic registries."""
        merged = Registry(
            version=dynamic.version or static.version,
            build_mode="merged",
            build_timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # Start with static as base
        for mn, sm in static.models.items():
            merged.models[mn] = ModelInfo(
                model=sm.model, name=sm.name, description=sm.description,
                transient=sm.transient,
                fields=dict(sm.fields), methods=dict(sm.methods),
                states=list(sm.states) if sm.states else None,
                parent_models=list(sm.parent_models),
                has_chatter=sm.has_chatter,
            )

        # Overlay dynamic data
        for mn, dm in dynamic.models.items():
            if mn in merged.models:
                mm = merged.models[mn]
                for fname, df in dm.fields.items():
                    if fname not in mm.fields:
                        logger.debug(
                            "Registry merge: %s.%s - added from dynamic (not in static)",
                            mn, fname,
                        )
                    mm.fields[fname] = df
                for mname, dmethod in dm.methods.items():
                    if mname not in mm.methods:
                        logger.debug(
                            "Registry merge: %s.%s - method added from dynamic",
                            mn, mname,
                        )
                        mm.methods[mname] = dmethod
                if dm.states is not None:
                    if mm.states != dm.states:
                        logger.debug(
                            "Registry merge: %s.state - selection values updated from dynamic",
                            mn,
                        )
                    mm.states = dm.states
                if dm.has_chatter:
                    mm.has_chatter = True
                for p in dm.parent_models:
                    if p not in mm.parent_models:
                        mm.parent_models.append(p)
            else:
                logger.debug("Registry merge: %s - new model from dynamic", mn)
                merged.models[mn] = dm

        merged.update_counts()
        with self._lock:
            self._registry = merged
            self._existence_cache.clear()
        return merged
