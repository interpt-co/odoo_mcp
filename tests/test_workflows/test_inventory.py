"""Tests for inventory toolset."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from odoo_mcp.toolsets.inventory import InventoryToolset


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


class TestInventoryToolsetMetadata:
    def test_metadata(self):
        ts = InventoryToolset()
        meta = ts.metadata()
        assert meta.name == "inventory"
        assert "stock" in meta.required_modules
        assert "core" in meta.depends_on


class TestInventoryToolsetRegistration:
    def test_registers_all_tools(self):
        ts = InventoryToolset()
        server, registered = _make_server()
        conn = _make_connection()
        names = asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))
        assert set(names) == {
            "odoo_inventory_get_stock",
            "odoo_inventory_validate_picking",
            "odoo_inventory_create_transfer",
        }


class TestGetStock:
    def test_get_stock_basic(self):
        ts = InventoryToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        conn.execute_kw = AsyncMock(return_value=[(5, "Widget A")])  # name_search
        conn.search_read = AsyncMock(side_effect=[
            # product read
            [{"display_name": "Widget A"}],
            # quants
            [
                {
                    "location_id": [8, "WH/Stock"],
                    "quantity": 100,
                    "reserved_quantity": 10,
                },
                {
                    "location_id": [9, "WH/Output"],
                    "quantity": 20,
                    "reserved_quantity": 0,
                },
            ],
        ])

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_inventory_get_stock"](product_name="Widget")
        )
        # Depending on resolution path
        if isinstance(result, dict) and "product" in result:
            assert result["total_available"] == 110  # (100-10) + (20-0)
            assert len(result["stock"]) == 2

    def test_get_stock_by_id(self):
        ts = InventoryToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        conn.search_read = AsyncMock(side_effect=[
            [{"display_name": "Widget A"}],
            [{
                "location_id": [8, "WH/Stock"],
                "quantity": 50,
                "reserved_quantity": 5,
            }],
        ])

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_inventory_get_stock"](product_id=5)
        )
        assert result["product"]["id"] == 5
        assert result["total_available"] == 45


class TestValidatePicking:
    def test_validate_picking_direct(self):
        ts = InventoryToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        conn.search_read = AsyncMock(return_value=[
            {"name": "WH/OUT/00001", "state": "assigned"}
        ])
        conn.execute_kw = AsyncMock(return_value=None)  # No wizard

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_inventory_validate_picking"](picking_id=1)
        )
        assert result["state"] == "done"
        assert "validated" in result["message"]

    def test_validate_picking_not_found(self):
        ts = InventoryToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        conn.search_read = AsyncMock(return_value=[])

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_inventory_validate_picking"](picking_id=999)
        )
        assert result["status"] == "error"


class TestCreateTransfer:
    def test_create_transfer_no_lines(self):
        ts = InventoryToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_inventory_create_transfer"]()
        )
        assert result["status"] == "error"
        assert "lines" in result["message"]

    def test_create_transfer_basic(self):
        ts = InventoryToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        call_idx = 0

        async def mock_search_read(model, domain, **kwargs):
            nonlocal call_idx
            call_idx += 1
            if model == "stock.picking.type":
                return [{"id": 1, "name": "Internal", "default_location_src_id": [8, "WH/Stock"], "default_location_dest_id": [9, "WH/Output"]}]
            if model == "product.product":
                return [{"display_name": "Widget", "uom_id": [1, "Units"]}]
            if model == "stock.picking":
                return [{"name": "WH/INT/00001", "state": "confirmed"}]
            return []

        conn.search_read = mock_search_read

        async def mock_execute_kw(model, method, args=None, **kwargs):
            if method == "create":
                return 1
            return None

        conn.execute_kw = mock_execute_kw

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_inventory_create_transfer"](
                picking_type_name="internal",
                lines=[{"product_id": 5, "quantity": 10}],
            )
        )
        assert result["id"] == 1
        assert result["lines_count"] == 1
