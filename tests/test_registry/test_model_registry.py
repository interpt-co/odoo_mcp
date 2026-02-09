"""Tests for registry data models and ModelRegistry access API."""

from __future__ import annotations

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_field(**kwargs) -> FieldInfo:
    defaults = {"name": "test", "label": "Test", "type": "char"}
    defaults.update(kwargs)
    return FieldInfo(**defaults)


def make_method(**kwargs) -> MethodInfo:
    defaults = {"name": "action_test"}
    defaults.update(kwargs)
    return MethodInfo(**defaults)


def make_model(**kwargs) -> ModelInfo:
    defaults = {
        "model": "test.model",
        "name": "Test Model",
    }
    defaults.update(kwargs)
    return ModelInfo(**defaults)


def make_registry_with_sale_order() -> ModelRegistry:
    reg = ModelRegistry()
    sale = ModelInfo(
        model="sale.order",
        name="Sales Order",
        description="Sales Order",
        fields={
            "name": FieldInfo(name="name", label="Order Reference", type="char", required=True, readonly=True, store=True),
            "state": FieldInfo(
                name="state", label="Status", type="selection",
                selection=[("draft", "Quotation"), ("sale", "Sales Order"), ("cancel", "Cancelled")],
            ),
            "partner_id": FieldInfo(name="partner_id", label="Customer", type="many2one", required=True, relation="res.partner"),
            "order_line": FieldInfo(name="order_line", label="Order Lines", type="one2many", relation="sale.order.line"),
            "amount_total": FieldInfo(name="amount_total", label="Total", type="monetary", readonly=True, compute=True),
            "message_ids": FieldInfo(name="message_ids", label="Messages", type="one2many", relation="mail.message"),
        },
        methods={
            "action_confirm": MethodInfo(name="action_confirm", description="Confirm the quotation", accepts_kwargs=False),
            "action_cancel": MethodInfo(name="action_cancel", description="Cancel the order", accepts_kwargs=False),
        },
        states=[("draft", "Quotation"), ("sale", "Sales Order"), ("cancel", "Cancelled")],
        parent_models=["mail.thread", "mail.activity.mixin"],
        has_chatter=True,
    )
    partner = ModelInfo(
        model="res.partner",
        name="Contact",
        fields={
            "name": FieldInfo(name="name", label="Name", type="char", required=True),
            "email": FieldInfo(name="email", label="Email", type="char"),
        },
    )
    registry = Registry(models={"sale.order": sale, "res.partner": partner}, version="17.0", build_mode="static")
    registry.update_counts()
    reg.load_static(registry)
    return reg


# ---------------------------------------------------------------------------
# Data Model Tests (Task 3.1)
# ---------------------------------------------------------------------------


class TestFieldInfo:
    def test_basic_creation(self):
        f = FieldInfo(name="name", label="Name", type="char")
        assert f.name == "name"
        assert f.label == "Name"
        assert f.type == "char"
        assert f.required is False
        assert f.readonly is False
        assert f.store is True

    def test_relational_field(self):
        f = FieldInfo(name="partner_id", label="Partner", type="many2one", relation="res.partner", required=True)
        assert f.relation == "res.partner"
        assert f.required is True

    def test_selection_field(self):
        f = FieldInfo(name="state", label="Status", type="selection", selection=[("draft", "Draft"), ("done", "Done")])
        assert f.selection == [("draft", "Draft"), ("done", "Done")]

    def test_to_dict(self):
        f = FieldInfo(name="state", label="Status", type="selection", selection=[("a", "A")])
        d = f.to_dict()
        assert d["selection"] == [["a", "A"]]
        assert d["name"] == "state"

    def test_from_dict(self):
        data = {"name": "x", "label": "X", "type": "char", "required": True}
        f = FieldInfo.from_dict(data)
        assert f.name == "x"
        assert f.required is True

    def test_roundtrip(self):
        f = FieldInfo(name="s", label="S", type="selection", selection=[("a", "A")], depends=["x", "y"])
        d = f.to_dict()
        f2 = FieldInfo.from_dict(d)
        assert f2.selection == [("a", "A")]
        assert f2.depends == ["x", "y"]


class TestMethodInfo:
    def test_basic(self):
        m = MethodInfo(name="action_confirm", description="Confirm", accepts_kwargs=False)
        assert m.name == "action_confirm"
        assert m.accepts_kwargs is False

    def test_to_from_dict(self):
        m = MethodInfo(name="action_test", decorator="api.model")
        d = m.to_dict()
        m2 = MethodInfo.from_dict(d)
        assert m2.decorator == "api.model"


class TestModelInfo:
    def test_basic(self):
        m = make_model()
        assert m.model == "test.model"
        assert m.fields == {}
        assert m.methods == {}

    def test_to_dict(self):
        m = make_model(
            fields={"name": make_field(name="name")},
            methods={"action_do": make_method(name="action_do")},
            states=[("draft", "Draft")],
        )
        d = m.to_dict()
        assert "name" in d["fields"]
        assert "action_do" in d["methods"]
        assert d["states"] == [["draft", "Draft"]]

    def test_from_dict(self):
        data = {
            "model": "sale.order",
            "name": "Sales Order",
            "transient": False,
            "fields": {"name": {"label": "Name", "type": "char"}},
            "methods": {"action_confirm": {"description": "Confirm", "accepts_kwargs": False}},
            "states": [["draft", "Draft"]],
            "parent_models": ["mail.thread"],
            "has_chatter": True,
        }
        m = ModelInfo.from_dict(data)
        assert m.model == "sale.order"
        assert "name" in m.fields
        assert m.fields["name"].type == "char"
        assert m.states == [("draft", "Draft")]
        assert m.has_chatter is True


class TestRegistry:
    def test_update_counts(self):
        r = Registry(models={
            "a": make_model(model="a", fields={"f1": make_field(), "f2": make_field()}),
            "b": make_model(model="b", fields={"f3": make_field()}),
        })
        r.update_counts()
        assert r.model_count == 2
        assert r.field_count == 3

    def test_to_from_dict(self):
        r = Registry(
            models={"test.model": make_model()},
            version="17.0",
            build_mode="static",
        )
        r.update_counts()
        d = r.to_dict()
        r2 = Registry.from_dict(d)
        assert r2.version == "17.0"
        assert "test.model" in r2.models


class TestConstants:
    def test_no_kwargs_methods(self):
        assert "action_confirm" in NO_KWARGS_METHODS
        assert "search_read" in NO_KWARGS_METHODS
        assert "fields_get" in NO_KWARGS_METHODS
        assert "custom_method" not in NO_KWARGS_METHODS

    def test_field_type_map_complete(self):
        expected_types = {
            "char", "text", "html", "integer", "float", "monetary",
            "boolean", "date", "datetime", "binary", "selection",
            "many2one", "one2many", "many2many", "reference", "properties",
        }
        assert set(FIELD_TYPE_MAP.keys()) == expected_types

    def test_default_models(self):
        assert "sale.order" in DEFAULT_INTROSPECTION_MODELS
        assert "res.partner" in DEFAULT_INTROSPECTION_MODELS
        assert "ir.attachment" in DEFAULT_INTROSPECTION_MODELS


# ---------------------------------------------------------------------------
# ModelRegistry Query Tests (Task 3.2)
# ---------------------------------------------------------------------------


class TestModelRegistryQueries:
    def test_get_model(self):
        reg = make_registry_with_sale_order()
        m = reg.get_model("sale.order")
        assert m is not None
        assert m.model == "sale.order"

    def test_get_model_not_found(self):
        reg = make_registry_with_sale_order()
        assert reg.get_model("nonexistent.model") is None

    def test_get_field(self):
        reg = make_registry_with_sale_order()
        f = reg.get_field("sale.order", "name")
        assert f is not None
        assert f.type == "char"

    def test_get_field_not_found(self):
        reg = make_registry_with_sale_order()
        assert reg.get_field("sale.order", "nonexistent") is None
        assert reg.get_field("nonexistent", "name") is None

    def test_get_method(self):
        reg = make_registry_with_sale_order()
        m = reg.get_method("sale.order", "action_confirm")
        assert m is not None
        assert m.accepts_kwargs is False

    def test_get_method_not_found(self):
        reg = make_registry_with_sale_order()
        assert reg.get_method("sale.order", "nonexistent") is None

    def test_list_models_all(self):
        reg = make_registry_with_sale_order()
        models = reg.list_models()
        assert len(models) == 2

    def test_list_models_filter(self):
        reg = make_registry_with_sale_order()
        models = reg.list_models(filter="sale")
        assert len(models) == 1
        assert models[0].model == "sale.order"

    def test_list_models_filter_no_match(self):
        reg = make_registry_with_sale_order()
        models = reg.list_models(filter="zzz_nonexistent")
        assert len(models) == 0

    def test_get_required_fields(self):
        reg = make_registry_with_sale_order()
        required = reg.get_required_fields("sale.order")
        names = {f.name for f in required}
        assert "name" in names
        assert "partner_id" in names

    def test_get_required_fields_nonexistent(self):
        reg = make_registry_with_sale_order()
        assert reg.get_required_fields("nonexistent") == []

    def test_get_state_field(self):
        reg = make_registry_with_sale_order()
        sf = reg.get_state_field("sale.order")
        assert sf is not None
        assert sf.type == "selection"

    def test_get_state_field_none(self):
        reg = make_registry_with_sale_order()
        assert reg.get_state_field("res.partner") is None

    def test_get_relational_fields(self):
        reg = make_registry_with_sale_order()
        rels = reg.get_relational_fields("sale.order")
        names = {f.name for f in rels}
        assert "partner_id" in names
        assert "order_line" in names
        assert "message_ids" in names
        assert "name" not in names

    def test_method_accepts_kwargs(self):
        reg = make_registry_with_sale_order()
        assert reg.method_accepts_kwargs("custom_method") is True
        assert reg.method_accepts_kwargs("action_confirm") is False
        assert reg.method_accepts_kwargs("search_read") is False

    def test_model_exists_in_registry(self):
        reg = make_registry_with_sale_order()
        result = asyncio.get_event_loop().run_until_complete(reg.model_exists("sale.order"))
        assert result is True

    def test_model_exists_not_found_no_protocol(self):
        reg = make_registry_with_sale_order()
        result = asyncio.get_event_loop().run_until_complete(reg.model_exists("nonexistent"))
        assert result is False

    def test_model_exists_live_check(self):
        reg = make_registry_with_sale_order()
        protocol = AsyncMock()
        protocol.execute_kw = AsyncMock(return_value=5)
        reg.set_protocol(protocol)
        result = asyncio.get_event_loop().run_until_complete(reg.model_exists("new.model"))
        assert result is True

    def test_model_exists_live_check_fails(self):
        reg = make_registry_with_sale_order()
        protocol = AsyncMock()
        protocol.execute_kw = AsyncMock(side_effect=Exception("access denied"))
        reg.set_protocol(protocol)
        result = asyncio.get_event_loop().run_until_complete(reg.model_exists("blocked.model"))
        assert result is False

    def test_model_exists_caching(self):
        reg = make_registry_with_sale_order()
        protocol = AsyncMock()
        protocol.execute_kw = AsyncMock(return_value=5)
        reg.set_protocol(protocol)

        loop = asyncio.get_event_loop()
        loop.run_until_complete(reg.model_exists("new.model"))
        loop.run_until_complete(reg.model_exists("new.model"))
        # Should only call once due to caching
        assert protocol.execute_kw.call_count == 1


# ---------------------------------------------------------------------------
# Dynamic Registry Tests (Task 3.3)
# ---------------------------------------------------------------------------


class TestDynamicRegistry:
    def _make_protocol(self):
        protocol = AsyncMock()
        protocol.search_read = AsyncMock(side_effect=self._mock_search_read)
        protocol.fields_get = AsyncMock(side_effect=self._mock_fields_get)
        protocol.execute_kw = AsyncMock(return_value=0)
        return protocol

    @staticmethod
    def _mock_search_read(model, domain, fields, **kwargs):
        if model == "ir.module.module":
            return [{"name": "sale", "shortdesc": "Sales", "state": "installed"}]
        if model == "ir.model":
            return [
                {"model": "res.partner", "name": "Contact", "info": "", "transient": False},
            ]
        return []

    @staticmethod
    def _mock_fields_get(model, attributes=None):
        if model == "res.partner":
            return {
                "name": {"string": "Name", "type": "char", "required": True, "readonly": False, "store": True, "help": "", "relation": None, "selection": None},
                "email": {"string": "Email", "type": "char", "required": False, "readonly": False, "store": True, "help": "", "relation": None, "selection": None},
                "message_ids": {"string": "Messages", "type": "one2many", "required": False, "readonly": False, "store": False, "help": "", "relation": "mail.message", "selection": None},
            }
        return {}

    def test_build_dynamic(self):
        reg = ModelRegistry()
        protocol = self._make_protocol()
        loop = asyncio.get_event_loop()
        registry = loop.run_until_complete(
            reg.build_dynamic(protocol, target_models=["res.partner"])
        )
        assert "res.partner" in registry.models
        model = registry.models["res.partner"]
        assert model.name == "Contact"
        assert "name" in model.fields
        assert model.has_chatter is True

    def test_build_dynamic_handles_missing_model(self):
        protocol = AsyncMock()
        protocol.search_read = AsyncMock(return_value=[])
        protocol.fields_get = AsyncMock(side_effect=Exception("Model not found"))
        protocol.execute_kw = AsyncMock()

        reg = ModelRegistry()
        loop = asyncio.get_event_loop()
        registry = loop.run_until_complete(
            reg.build_dynamic(protocol, target_models=["nonexistent.model"])
        )
        assert len(registry.models) == 0

    def test_build_dynamic_timeout(self):
        async def slow_fields_get(model, attributes=None):
            await asyncio.sleep(10)
            return {}

        protocol = AsyncMock()
        protocol.search_read = AsyncMock(return_value=[])
        protocol.fields_get = AsyncMock(side_effect=slow_fields_get)
        protocol.execute_kw = AsyncMock()

        reg = ModelRegistry()
        loop = asyncio.get_event_loop()
        registry = loop.run_until_complete(
            reg.build_dynamic(protocol, target_models=["res.partner"], timeout=0.1)
        )
        # Should return empty rather than hang
        assert registry.model_count == 0
