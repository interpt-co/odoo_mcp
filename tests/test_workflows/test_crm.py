"""Tests for CRM toolset."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from odoo_mcp.toolsets.crm import CrmToolset


def _make_connection() -> MagicMock:
    conn = MagicMock()
    conn.execute_kw = AsyncMock(return_value=None)
    conn.search_read = AsyncMock(return_value=[])
    conn.odoo_version = 17
    return conn


def _make_server():
    server = MagicMock()
    registered = {}

    def tool_decorator():
        def wrapper(fn):
            registered[fn.__name__] = fn
            return fn
        return wrapper

    server.tool = tool_decorator
    return server, registered


class TestCrmToolsetMetadata:
    def test_metadata(self):
        ts = CrmToolset()
        meta = ts.metadata()
        assert meta.name == "crm"
        assert "crm" in meta.required_modules
        assert "core" in meta.depends_on


class TestCrmToolsetRegistration:
    def test_registers_all_tools(self):
        ts = CrmToolset()
        server, registered = _make_server()
        conn = _make_connection()
        names = ts.register_tools(server, conn)
        assert set(names) == {
            "odoo_crm_create_lead",
            "odoo_crm_move_stage",
            "odoo_crm_convert_to_opportunity",
        }


class TestCreateLead:
    def test_create_lead_minimal(self):
        ts = CrmToolset()
        server, registered = _make_server()
        conn = _make_connection()
        ts.register_tools(server, conn)

        conn.execute_kw = AsyncMock(return_value=1)
        conn.search_read = AsyncMock(return_value=[{
            "name": "New Lead",
            "type": "lead",
            "stage_id": [1, "New"],
            "partner_id": False,
            "expected_revenue": 0,
        }])

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_crm_create_lead"](name="New Lead")
        )
        assert result["id"] == 1
        assert result["type"] == "lead"

    def test_create_lead_no_name(self):
        ts = CrmToolset()
        server, registered = _make_server()
        conn = _make_connection()
        ts.register_tools(server, conn)

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_crm_create_lead"]()
        )
        assert result["status"] == "error"

    def test_create_lead_with_partner_name(self):
        ts = CrmToolset()
        server, registered = _make_server()
        conn = _make_connection()
        ts.register_tools(server, conn)

        call_idx = 0

        async def mock_execute(model, method, args=None, **kwargs):
            nonlocal call_idx
            call_idx += 1
            if method == "name_search":
                return [(10, "Test Partner")]
            if method == "create":
                return 1
            return None

        conn.execute_kw = mock_execute
        conn.search_read = AsyncMock(return_value=[{
            "name": "New Lead",
            "type": "lead",
            "stage_id": [1, "New"],
            "partner_id": [10, "Test Partner"],
            "expected_revenue": 5000,
        }])

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_crm_create_lead"](
                name="New Lead",
                partner_name="Test",
                expected_revenue=5000,
            )
        )
        assert result["id"] == 1


class TestMoveStage:
    def test_move_stage_by_id(self):
        ts = CrmToolset()
        server, registered = _make_server()
        conn = _make_connection()
        ts.register_tools(server, conn)

        conn.execute_kw = AsyncMock(return_value=None)
        conn.search_read = AsyncMock(return_value=[{
            "name": "My Lead",
            "stage_id": [2, "Qualified"],
        }])

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_crm_move_stage"](lead_id=1, stage_id=2)
        )
        assert result["id"] == 1

    def test_move_stage_no_lead_id(self):
        ts = CrmToolset()
        server, registered = _make_server()
        conn = _make_connection()
        ts.register_tools(server, conn)

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_crm_move_stage"]()
        )
        assert result["status"] == "error"


class TestConvertToOpportunity:
    def test_convert_no_lead_id(self):
        ts = CrmToolset()
        server, registered = _make_server()
        conn = _make_connection()
        ts.register_tools(server, conn)

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_crm_convert_to_opportunity"]()
        )
        assert result["status"] == "error"

    def test_convert_success(self):
        ts = CrmToolset()
        server, registered = _make_server()
        conn = _make_connection()
        ts.register_tools(server, conn)

        conn.execute_kw = AsyncMock(side_effect=[
            {},    # default_get
            1,     # create wizard
            None,  # action_apply
        ])
        conn.search_read = AsyncMock(return_value=[{
            "name": "My Opportunity",
            "type": "opportunity",
            "stage_id": [1, "New"],
            "partner_id": [10, "Test Partner"],
        }])

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_crm_convert_to_opportunity"](lead_id=5)
        )
        assert result["type"] == "opportunity"
