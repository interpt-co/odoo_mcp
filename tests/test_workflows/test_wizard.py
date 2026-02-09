"""Tests for wizard execution protocol."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from odoo_mcp.toolsets.wizard import (
    WizardField,
    KnownWizard,
    KNOWN_WIZARDS,
    is_wizard_action,
    get_wizard_model,
    is_known_wizard,
    get_known_wizard,
    execute_wizard,
    classify_wizard_result,
    handle_wizard_result,
    build_unknown_wizard_response,
    handle_wizard_encounter,
    MAX_WIZARD_CHAIN_DEPTH,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_connection(**overrides) -> MagicMock:
    conn = MagicMock()
    conn.execute_kw = AsyncMock(return_value=None)
    conn.search_read = AsyncMock(return_value=[])
    conn.odoo_version = 17
    conn.uid = 2
    for k, v in overrides.items():
        setattr(conn, k, v)
    return conn


# ---------------------------------------------------------------------------
# WizardField / KnownWizard dataclasses
# ---------------------------------------------------------------------------

class TestDataClasses:
    def test_wizard_field_defaults(self):
        wf = WizardField(type="char")
        assert wf.type == "char"
        assert wf.required is False
        assert wf.description == ""
        assert wf.relation is None
        assert wf.selection is None
        assert wf.default is None

    def test_wizard_field_full(self):
        wf = WizardField(
            type="selection",
            required=True,
            description="Choose one",
            selection=[("a", "A"), ("b", "B")],
            default="a",
        )
        assert wf.required is True
        assert len(wf.selection) == 2

    def test_known_wizard_defaults(self):
        kw = KnownWizard(
            model="test.wizard",
            description="Test",
            source_model="test.model",
            action_method="action_test",
            fields={},
            context_keys=["active_ids"],
        )
        assert kw.min_odoo_version == 14
        assert kw.max_odoo_version is None
        assert kw.alternative_actions is None

    def test_catalog_has_six_wizards(self):
        expected = {
            "account.payment.register",
            "stock.immediate.transfer",
            "stock.backorder.confirmation",
            "sale.advance.payment.inv",
            "crm.lead2opportunity.partner",
            "account.move.reversal",
        }
        assert set(KNOWN_WIZARDS.keys()) == expected


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

class TestWizardDetection:
    def test_is_wizard_action_true(self):
        action = {
            "type": "ir.actions.act_window",
            "target": "new",
            "res_model": "some.wizard",
        }
        assert is_wizard_action(action) is True

    def test_is_wizard_action_not_dict(self):
        assert is_wizard_action(None) is False
        assert is_wizard_action(True) is False
        assert is_wizard_action(42) is False

    def test_is_wizard_action_wrong_type(self):
        assert is_wizard_action({"type": "ir.actions.report", "target": "new"}) is False

    def test_is_wizard_action_wrong_target(self):
        assert is_wizard_action({"type": "ir.actions.act_window", "target": "current"}) is False

    def test_get_wizard_model(self):
        action = {"type": "ir.actions.act_window", "target": "new", "res_model": "test.wiz"}
        assert get_wizard_model(action) == "test.wiz"

    def test_get_wizard_model_not_wizard(self):
        assert get_wizard_model({"type": "ir.actions.report"}) is None

    def test_is_known_wizard(self):
        assert is_known_wizard("account.payment.register") is True
        assert is_known_wizard("unknown.wizard") is False

    def test_get_known_wizard(self):
        kw = get_known_wizard("stock.immediate.transfer")
        assert kw is not None
        assert kw.action_method == "process"
        assert get_known_wizard("nonexistent") is None


# ---------------------------------------------------------------------------
# Wizard Execution
# ---------------------------------------------------------------------------

class TestExecuteWizard:
    def test_execute_wizard_basic(self):
        conn = _make_connection()
        # default_get returns some defaults
        conn.execute_kw = AsyncMock(side_effect=[
            {"field_a": "default_a"},  # default_get
            42,                         # create
            None,                       # action method
        ])

        result = asyncio.get_event_loop().run_until_complete(
            execute_wizard(
                connection=conn,
                wizard_model="test.wizard",
                wizard_values={"field_b": "val_b"},
                action_method="action_do",
                source_model="source.model",
                source_ids=[1, 2],
            )
        )

        assert result is None  # action returned None -> complete
        # Verify context was built correctly
        calls = conn.execute_kw.call_args_list
        # default_get call
        assert calls[0][0][0] == "test.wizard"
        assert calls[0][0][1] == "default_get"
        # create call - merged values
        create_vals = calls[1][0][2][0]
        assert create_vals["field_a"] == "default_a"
        assert create_vals["field_b"] == "val_b"
        # action call
        assert calls[2][0][1] == "action_do"

    def test_execute_wizard_with_context_extra(self):
        conn = _make_connection()
        conn.execute_kw = AsyncMock(side_effect=[{}, 1, True])

        asyncio.get_event_loop().run_until_complete(
            execute_wizard(
                connection=conn,
                wizard_model="test.wizard",
                wizard_values={},
                action_method="process",
                source_model="stock.picking",
                source_ids=[5],
                context_extra={"button_validate_picking_ids": [5]},
            )
        )

        # Check that context_extra was passed
        first_call_context = conn.execute_kw.call_args_list[0].kwargs.get("context", {})
        assert first_call_context.get("button_validate_picking_ids") == [5]
        assert first_call_context.get("active_model") == "stock.picking"


# ---------------------------------------------------------------------------
# Result Classification
# ---------------------------------------------------------------------------

class TestClassifyResult:
    def test_none_is_complete(self):
        assert classify_wizard_result(None) == "complete"

    def test_bool_is_complete(self):
        assert classify_wizard_result(True) == "complete"
        assert classify_wizard_result(False) == "complete"

    def test_close_action(self):
        assert classify_wizard_result({"type": "ir.actions.act_window_close"}) == "close"

    def test_wizard_chain(self):
        action = {"type": "ir.actions.act_window", "target": "new"}
        assert classify_wizard_result(action) == "wizard_chain"

    def test_report_action(self):
        assert classify_wizard_result({"type": "ir.actions.report"}) == "report"

    def test_url_action(self):
        assert classify_wizard_result({"type": "ir.actions.act_url"}) == "url"

    def test_other_action_complete(self):
        action = {"type": "ir.actions.act_window", "target": "current"}
        assert classify_wizard_result(action) == "complete"


# ---------------------------------------------------------------------------
# Handle Wizard Result
# ---------------------------------------------------------------------------

class TestHandleWizardResult:
    def test_handle_complete(self):
        conn = _make_connection()
        result = asyncio.get_event_loop().run_until_complete(
            handle_wizard_result(conn, None)
        )
        assert result["status"] == "success"
        assert result["result_type"] == "complete"

    def test_handle_close(self):
        conn = _make_connection()
        result = asyncio.get_event_loop().run_until_complete(
            handle_wizard_result(conn, {"type": "ir.actions.act_window_close"})
        )
        assert result["status"] == "success"
        assert result["result_type"] == "close"

    def test_handle_report(self):
        conn = _make_connection()
        action = {"type": "ir.actions.report", "report_name": "test"}
        result = asyncio.get_event_loop().run_until_complete(
            handle_wizard_result(conn, action)
        )
        assert result["result_type"] == "report"

    def test_handle_url(self):
        conn = _make_connection()
        action = {"type": "ir.actions.act_url", "url": "https://example.com"}
        result = asyncio.get_event_loop().run_until_complete(
            handle_wizard_result(conn, action)
        )
        assert result["result_type"] == "url"
        assert result["url"] == "https://example.com"

    def test_wizard_chain_max_depth(self):
        conn = _make_connection()
        action = {
            "type": "ir.actions.act_window",
            "target": "new",
            "res_model": "unknown.wizard",
        }
        result = asyncio.get_event_loop().run_until_complete(
            handle_wizard_result(conn, action, depth=MAX_WIZARD_CHAIN_DEPTH)
        )
        assert result["status"] == "error"
        assert "maximum depth" in result["message"]


# ---------------------------------------------------------------------------
# Unknown Wizard Response
# ---------------------------------------------------------------------------

class TestUnknownWizard:
    def test_build_unknown_wizard_response(self):
        conn = _make_connection()
        conn.execute_kw = AsyncMock(return_value={
            "field_x": {"type": "char", "required": True, "string": "Field X"},
            "id": {"type": "integer", "required": False, "string": "ID"},
        })

        action = {"type": "ir.actions.act_window", "target": "new", "view_mode": "form"}
        result = asyncio.get_event_loop().run_until_complete(
            build_unknown_wizard_response(
                conn, "custom.wizard", action, "source.model", [1]
            )
        )

        assert result["wizard_required"] is True
        assert result["wizard_model"] == "custom.wizard"
        assert "field_x" in result["wizard_fields"]
        assert "id" not in result["wizard_fields"]  # filtered out
        assert result["context_hint"]["active_model"] == "source.model"
        assert "instructions" in result


# ---------------------------------------------------------------------------
# Wizard Encounter Handler
# ---------------------------------------------------------------------------

class TestHandleWizardEncounter:
    def test_not_wizard_returns_none(self):
        conn = _make_connection()
        result = asyncio.get_event_loop().run_until_complete(
            handle_wizard_encounter(conn, True)
        )
        assert result is None

    def test_known_wizard_auto_handled(self):
        conn = _make_connection()
        conn.execute_kw = AsyncMock(side_effect=[
            {},    # default_get
            1,     # create
            None,  # action method result -> complete
        ])

        action = {
            "type": "ir.actions.act_window",
            "target": "new",
            "res_model": "stock.immediate.transfer",
        }
        result = asyncio.get_event_loop().run_until_complete(
            handle_wizard_encounter(
                conn, action, "stock.picking", [1]
            )
        )

        assert result is not None
        assert result["status"] == "success"

    def test_unknown_wizard_returns_guidance(self):
        conn = _make_connection()
        conn.execute_kw = AsyncMock(return_value={})

        action = {
            "type": "ir.actions.act_window",
            "target": "new",
            "res_model": "custom.unknown.wizard",
        }
        result = asyncio.get_event_loop().run_until_complete(
            handle_wizard_encounter(conn, action, "some.model", [1])
        )

        assert result is not None
        assert result["wizard_required"] is True
        assert result["wizard_model"] == "custom.unknown.wizard"
