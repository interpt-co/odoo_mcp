"""Tests for accounting toolset."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from odoo_mcp.toolsets.accounting import AccountingToolset


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


class TestAccountingToolsetMetadata:
    def test_metadata(self):
        ts = AccountingToolset()
        meta = ts.metadata()
        assert meta.name == "accounting"
        assert "account" in meta.required_modules
        assert "core" in meta.depends_on


class TestAccountingToolsetRegistration:
    def test_registers_all_tools(self):
        ts = AccountingToolset()
        server, registered = _make_server()
        conn = _make_connection()
        names = asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))
        assert set(names) == {
            "odoo_accounting_create_invoice",
            "odoo_accounting_post_invoice",
            "odoo_accounting_register_payment",
        }


class TestCreateInvoice:
    def test_create_invoice_basic(self):
        ts = AccountingToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        conn.execute_kw = AsyncMock(return_value=1)
        conn.search_read = AsyncMock(return_value=[{
            "name": "INV/2025/0001",
            "state": "draft",
            "partner_id": [1, "Acme"],
            "amount_untaxed": 100,
            "amount_tax": 21,
            "amount_total": 121,
            "move_type": "out_invoice",
        }])

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_accounting_create_invoice"](partner_id=1)
        )
        assert result["id"] == 1
        assert result["name"] == "INV/2025/0001"
        assert result["posted"] is False

    def test_create_invoice_with_lines(self):
        ts = AccountingToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        call_count = 0
        async def mock_execute(model, method, args=None, **kwargs):
            nonlocal call_count
            call_count += 1
            if method == "name_search":
                return [(5, "Widget A")]
            if method == "create":
                return 1
            return None

        conn.execute_kw = mock_execute
        conn.search_read = AsyncMock(return_value=[{
            "name": "INV/2025/0001",
            "state": "draft",
            "partner_id": [1, "Acme"],
            "amount_untaxed": 50,
            "amount_tax": 10.5,
            "amount_total": 60.5,
            "move_type": "out_invoice",
        }])

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_accounting_create_invoice"](
                partner_id=1,
                lines=[{"product_name": "Widget", "quantity": 5, "price_unit": 10}],
            )
        )
        assert result["amount_total"] == 60.5


class TestPostInvoice:
    def test_post_draft_invoice(self):
        ts = AccountingToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        conn.search_read = AsyncMock(return_value=[
            {"name": "INV/2025/0001", "state": "draft"}
        ])
        conn.execute_kw = AsyncMock(return_value=None)

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_accounting_post_invoice"](invoice_id=1)
        )
        assert result["state"] == "posted"

    def test_post_non_draft_fails(self):
        ts = AccountingToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        conn.search_read = AsyncMock(return_value=[
            {"name": "INV/2025/0001", "state": "posted"}
        ])

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_accounting_post_invoice"](invoice_id=1)
        )
        assert result["status"] == "error"
        assert "posted" in result["message"]

    def test_post_validation_error_tax(self):
        ts = AccountingToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        conn.search_read = AsyncMock(return_value=[
            {"name": "INV/2025/0001", "state": "draft"}
        ])
        conn.execute_kw = AsyncMock(side_effect=Exception("Missing tax on line"))

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_accounting_post_invoice"](invoice_id=1)
        )
        assert result["status"] == "error"
        assert "tax" in result["message"].lower()


class TestRegisterPayment:
    def test_register_payment_no_ids(self):
        ts = AccountingToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_accounting_register_payment"]()
        )
        assert result["status"] == "error"

    def test_register_payment_success(self):
        ts = AccountingToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        conn.execute_kw = AsyncMock(side_effect=[
            {},    # default_get
            1,     # create wizard
            None,  # action_create_payments
        ])

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_accounting_register_payment"](invoice_ids=[1, 2])
        )
        assert result["status"] == "success"
        assert result["invoice_ids"] == [1, 2]
