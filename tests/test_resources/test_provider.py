"""Tests for the MCP Resource Provider (Task 3.7) and Prompt Provider (Task 3.8)."""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock

from odoo_mcp.registry.model_registry import (
    FieldInfo,
    MethodInfo,
    ModelInfo,
    Registry,
    ModelRegistry,
)
from odoo_mcp.resources.provider import (
    ResourceProvider,
    ResourceContext,
    MAX_SUBSCRIPTIONS,
)
from odoo_mcp.prompts.provider import PromptProvider, PromptContext


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_registry() -> ModelRegistry:
    reg = ModelRegistry()
    sale = ModelInfo(
        model="sale.order",
        name="Sales Order",
        fields={
            "name": FieldInfo(name="name", label="Order Ref", type="char", required=True),
            "state": FieldInfo(
                name="state", label="Status", type="selection",
                selection=[("draft", "Quotation"), ("sale", "Sales Order")],
            ),
            "partner_id": FieldInfo(name="partner_id", label="Customer", type="many2one", required=True, relation="res.partner"),
            "binary_field": FieldInfo(name="binary_field", label="File", type="binary"),
        },
        methods={
            "action_confirm": MethodInfo(name="action_confirm", description="Confirm", accepts_kwargs=False),
        },
        states=[("draft", "Quotation"), ("sale", "Sales Order")],
        parent_models=["mail.thread"],
        has_chatter=True,
    )
    registry = Registry(models={"sale.order": sale}, version="17.0")
    registry.update_counts()
    reg.load_static(registry)
    return reg


def _make_context(**kwargs) -> ResourceContext:
    defaults = {
        "registry": _make_registry(),
        "server_version": "17.0",
        "server_edition": "enterprise",
        "database": "testdb",
        "url": "https://test.odoo.com",
        "protocol_name": "json2",
        "user_uid": 2,
        "user_name": "Admin",
        "mcp_server_version": "0.1.0",
        "installed_modules": [
            {"name": "sale", "state": "installed", "shortdesc": "Sales"},
        ],
        "toolsets": [{"name": "core", "tools": ["search_read", "create"]}],
    }
    defaults.update(kwargs)
    return ResourceContext(**defaults)


# ---------------------------------------------------------------------------
# Resource Provider Tests
# ---------------------------------------------------------------------------


class TestStaticResources:
    def test_system_info(self):
        provider = ResourceProvider(_make_context())
        result = asyncio.get_event_loop().run_until_complete(
            provider.read_resource("odoo://system/info")
        )
        assert result["server_version"] == "17.0"
        assert result["database"] == "testdb"
        assert result["user"]["uid"] == 2

    def test_system_modules(self):
        provider = ResourceProvider(_make_context())
        result = asyncio.get_event_loop().run_until_complete(
            provider.read_resource("odoo://system/modules")
        )
        assert result["count"] == 1
        assert result["modules"][0]["name"] == "sale"

    def test_system_toolsets(self):
        provider = ResourceProvider(_make_context())
        result = asyncio.get_event_loop().run_until_complete(
            provider.read_resource("odoo://system/toolsets")
        )
        assert len(result["toolsets"]) == 1

    def test_config_safety(self):
        safety = {"operation_mode": "full", "model_allowlist": [], "model_blocklist": [], "rate_limit": {"calls_per_minute": 120}}
        provider = ResourceProvider(_make_context(safety_config=safety))
        result = asyncio.get_event_loop().run_until_complete(
            provider.read_resource("odoo://config/safety")
        )
        assert result["operation_mode"] == "full"


class TestModelResources:
    def test_model_fields(self):
        provider = ResourceProvider(_make_context())
        result = asyncio.get_event_loop().run_until_complete(
            provider.read_resource("odoo://model/sale.order/fields")
        )
        assert result["model"] == "sale.order"
        assert "name" in result["fields"]
        # Binary fields excluded
        assert "binary_field" not in result["fields"]

    def test_model_methods(self):
        provider = ResourceProvider(_make_context())
        result = asyncio.get_event_loop().run_until_complete(
            provider.read_resource("odoo://model/sale.order/methods")
        )
        assert result["model"] == "sale.order"
        assert len(result["methods"]) == 1
        assert result["methods"][0]["name"] == "action_confirm"

    def test_model_states(self):
        provider = ResourceProvider(_make_context())
        result = asyncio.get_event_loop().run_until_complete(
            provider.read_resource("odoo://model/sale.order/states")
        )
        assert result["state_field"] == "state"
        assert len(result["states"]) == 2

    def test_model_not_found(self):
        provider = ResourceProvider(_make_context())
        result = asyncio.get_event_loop().run_until_complete(
            provider.read_resource("odoo://model/nonexistent/fields")
        )
        assert result.get("error") is True

    def test_model_blocked(self):
        provider = ResourceProvider(_make_context(model_blocklist={"sale.order"}))
        result = asyncio.get_event_loop().run_until_complete(
            provider.read_resource("odoo://model/sale.order/fields")
        )
        assert result.get("error") is True
        assert result["code"] == "MODEL_BLOCKED"


class TestRecordResources:
    def test_single_record(self):
        protocol = AsyncMock()
        protocol.search_read = AsyncMock(return_value=[{"id": 42, "name": "SO001"}])
        provider = ResourceProvider(_make_context(protocol=protocol))
        result = asyncio.get_event_loop().run_until_complete(
            provider.read_resource("odoo://record/sale.order/42")
        )
        assert result["record"]["id"] == 42

    def test_record_not_found(self):
        protocol = AsyncMock()
        protocol.search_read = AsyncMock(return_value=[])
        provider = ResourceProvider(_make_context(protocol=protocol))
        result = asyncio.get_event_loop().run_until_complete(
            provider.read_resource("odoo://record/sale.order/999")
        )
        assert result.get("error") is True

    def test_record_listing(self):
        protocol = AsyncMock()
        protocol.search_read = AsyncMock(return_value=[
            {"id": 1, "name": "SO001"},
            {"id": 2, "name": "SO002"},
        ])
        provider = ResourceProvider(_make_context(protocol=protocol))
        result = asyncio.get_event_loop().run_until_complete(
            provider.read_resource('odoo://record/sale.order?domain=[["state","=","draft"]]&limit=10')
        )
        assert result["count"] == 2
        assert result["limit"] == 10

    def test_record_access_error(self):
        protocol = AsyncMock()
        protocol.search_read = AsyncMock(side_effect=Exception("Access Denied"))
        provider = ResourceProvider(_make_context(protocol=protocol))
        result = asyncio.get_event_loop().run_until_complete(
            provider.read_resource("odoo://record/sale.order/1")
        )
        assert result.get("error") is True
        assert result["code"] == "ACCESS_ERROR"

    def test_no_protocol(self):
        provider = ResourceProvider(_make_context(protocol=None))
        result = asyncio.get_event_loop().run_until_complete(
            provider.read_resource("odoo://record/sale.order/1")
        )
        assert result.get("error") is True


class TestSubscriptions:
    def test_subscribe_record(self):
        provider = ResourceProvider(_make_context())
        result = asyncio.get_event_loop().run_until_complete(
            provider.subscribe("odoo://record/sale.order/42")
        )
        assert result["subscribed"] is True
        assert provider.subscription_count == 1

    def test_subscribe_system_info(self):
        provider = ResourceProvider(_make_context())
        result = asyncio.get_event_loop().run_until_complete(
            provider.subscribe("odoo://system/info")
        )
        assert result["subscribed"] is True

    def test_subscribe_unsupported(self):
        provider = ResourceProvider(_make_context())
        result = asyncio.get_event_loop().run_until_complete(
            provider.subscribe("odoo://model/sale.order/fields")
        )
        assert result.get("error") is True

    def test_unsubscribe(self):
        provider = ResourceProvider(_make_context())
        loop = asyncio.get_event_loop()
        loop.run_until_complete(provider.subscribe("odoo://record/sale.order/42"))
        assert provider.subscription_count == 1
        loop.run_until_complete(provider.unsubscribe("odoo://record/sale.order/42"))
        assert provider.subscription_count == 0

    def test_subscription_limit(self):
        provider = ResourceProvider(_make_context())
        loop = asyncio.get_event_loop()
        for i in range(MAX_SUBSCRIPTIONS):
            loop.run_until_complete(
                provider.subscribe(f"odoo://record/sale.order/{i+1}")
            )
        result = loop.run_until_complete(
            provider.subscribe("odoo://record/sale.order/999")
        )
        assert result.get("error") is True
        assert "SUBSCRIPTION_LIMIT" in result["code"]


class TestResourceDefinitions:
    def test_static_resources(self):
        provider = ResourceProvider(_make_context())
        defs = provider.get_resource_definitions()
        uris = [d["uri"] for d in defs]
        assert "odoo://system/info" in uris
        assert "odoo://system/modules" in uris
        assert "odoo://system/toolsets" in uris
        assert "odoo://config/safety" in uris

    def test_resource_templates(self):
        provider = ResourceProvider(_make_context())
        templates = provider.get_resource_templates()
        assert len(templates) == 5


# ---------------------------------------------------------------------------
# Prompt Provider Tests (Task 3.8)
# ---------------------------------------------------------------------------


def _make_prompt_context() -> PromptContext:
    return PromptContext(
        registry=_make_registry(),
        server_version="17.0",
        server_edition="enterprise",
        url="https://test.odoo.com",
        database="testdb",
        username="Admin",
        uid=2,
        toolsets=[{"name": "core", "tools": ["search_read", "create"]}],
    )


class TestPromptDefinitions:
    def test_all_prompts_defined(self):
        provider = PromptProvider(_make_prompt_context())
        defs = provider.get_prompt_definitions()
        names = [d["name"] for d in defs]
        assert "odoo_overview" in names
        assert "odoo_domain_help" in names
        assert "odoo_model_guide" in names
        assert "odoo_create_record" in names
        assert "odoo_search_help" in names
        assert len(defs) == 5


class TestPromptOverview:
    def test_overview_content(self):
        provider = PromptProvider(_make_prompt_context())
        messages = asyncio.get_event_loop().run_until_complete(
            provider.get_prompt("odoo_overview")
        )
        text = messages[0]["content"]["text"]
        assert "17.0" in text
        assert "enterprise" in text
        assert "testdb" in text
        assert "Admin" in text


class TestPromptDomainHelp:
    def test_domain_help_content(self):
        provider = PromptProvider(_make_prompt_context())
        messages = asyncio.get_event_loop().run_until_complete(
            provider.get_prompt("odoo_domain_help")
        )
        text = messages[0]["content"]["text"]
        assert "ilike" in text
        assert "Polish" in text
        assert "(0, 0, {values})" in text


class TestPromptModelGuide:
    def test_model_guide(self):
        provider = PromptProvider(_make_prompt_context())
        messages = asyncio.get_event_loop().run_until_complete(
            provider.get_prompt("odoo_model_guide", {"model_name": "sale.order"})
        )
        text = messages[0]["content"]["text"]
        assert "sale.order" in text
        assert "Sales Order" in text
        assert "partner_id" in text
        assert "action_confirm" in text
        assert "States" in text

    def test_model_guide_not_found(self):
        provider = PromptProvider(_make_prompt_context())
        messages = asyncio.get_event_loop().run_until_complete(
            provider.get_prompt("odoo_model_guide", {"model_name": "nonexistent"})
        )
        text = messages[0]["content"]["text"]
        assert "not found" in text


class TestPromptCreateRecord:
    def test_create_record(self):
        provider = PromptProvider(_make_prompt_context())
        messages = asyncio.get_event_loop().run_until_complete(
            provider.get_prompt("odoo_create_record", {"model_name": "sale.order"})
        )
        text = messages[0]["content"]["text"]
        assert "Required Fields" in text
        assert "name" in text
        assert "partner_id" in text
        assert "res.partner" in text


class TestPromptSearchHelp:
    def test_search_help(self):
        provider = PromptProvider(_make_prompt_context())
        messages = asyncio.get_event_loop().run_until_complete(
            provider.get_prompt("odoo_search_help", {"model_name": "sale.order", "query": "acme"})
        )
        text = messages[0]["content"]["text"]
        assert "sale.order" in text
        assert "acme" in text
        assert "odoo_core_search_read" in text

    def test_search_help_model_not_found(self):
        provider = PromptProvider(_make_prompt_context())
        messages = asyncio.get_event_loop().run_until_complete(
            provider.get_prompt("odoo_search_help", {"model_name": "nope", "query": "test"})
        )
        text = messages[0]["content"]["text"]
        assert "not found" in text


class TestUnknownPrompt:
    def test_unknown(self):
        provider = PromptProvider(_make_prompt_context())
        messages = asyncio.get_event_loop().run_until_complete(
            provider.get_prompt("nonexistent_prompt")
        )
        text = messages[0]["content"]["text"]
        assert "Unknown" in text
