"""Tests for name resolution and shared helpers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from odoo_mcp.toolsets.helpers import (
    resolve_name,
    resolve_partner,
    resolve_product,
    resolve_order,
)


def _make_connection(**overrides) -> MagicMock:
    conn = MagicMock()
    conn.execute_kw = AsyncMock(return_value=None)
    conn.search_read = AsyncMock(return_value=[])
    for k, v in overrides.items():
        setattr(conn, k, v)
    return conn


class TestResolveName:
    def test_id_provided_returns_directly(self):
        conn = _make_connection()
        result = asyncio.get_event_loop().run_until_complete(
            resolve_name(conn, "res.partner", 42, None, "partner")
        )
        assert result == 42
        conn.execute_kw.assert_not_called()

    def test_id_takes_precedence_over_name(self):
        conn = _make_connection()
        result = asyncio.get_event_loop().run_until_complete(
            resolve_name(conn, "res.partner", 42, "Acme", "partner")
        )
        assert result == 42

    def test_no_id_no_name_returns_error(self):
        conn = _make_connection()
        result = asyncio.get_event_loop().run_until_complete(
            resolve_name(conn, "res.partner", None, None, "partner")
        )
        assert isinstance(result, dict)
        assert result["status"] == "error"

    def test_empty_name_returns_error(self):
        conn = _make_connection()
        result = asyncio.get_event_loop().run_until_complete(
            resolve_name(conn, "res.partner", None, "", "partner")
        )
        assert isinstance(result, dict)
        assert result["status"] == "error"

    def test_single_match_returns_id(self):
        conn = _make_connection()
        conn.execute_kw = AsyncMock(return_value=[(10, "Acme Corp")])

        result = asyncio.get_event_loop().run_until_complete(
            resolve_name(conn, "res.partner", None, "Acme", "partner")
        )
        assert result == 10
        conn.execute_kw.assert_called_once_with(
            "res.partner", "name_search", ["Acme"], kwargs={"limit": 10}
        )

    def test_no_matches_returns_error(self):
        conn = _make_connection()
        conn.execute_kw = AsyncMock(return_value=[])

        result = asyncio.get_event_loop().run_until_complete(
            resolve_name(conn, "res.partner", None, "Nonexistent", "partner")
        )
        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert "Nonexistent" in result["message"]

    def test_multiple_matches_returns_disambiguation(self):
        conn = _make_connection()
        conn.execute_kw = AsyncMock(return_value=[
            (1, "Acme Corp"),
            (2, "Acme Industries"),
            (3, "Acme LLC"),
        ])

        result = asyncio.get_event_loop().run_until_complete(
            resolve_name(conn, "res.partner", None, "Acme", "partner")
        )
        assert isinstance(result, dict)
        assert result["status"] == "disambiguation_needed"
        assert result["field"] == "partner_id"
        assert len(result["matches"]) == 3
        assert result["matches"][0] == {"id": 1, "name": "Acme Corp"}

    def test_disambiguation_max_10(self):
        conn = _make_connection()
        many_results = [(i, f"Match {i}") for i in range(1, 12)]
        conn.execute_kw = AsyncMock(return_value=many_results)

        result = asyncio.get_event_loop().run_until_complete(
            resolve_name(conn, "res.partner", None, "Match", "partner")
        )
        assert isinstance(result, dict)
        assert result["status"] == "disambiguation_needed"
        # name_search limit=10 so max 10 returned, but we only show 10
        assert len(result["matches"]) <= 10


class TestResolvePartner:
    def test_resolve_partner_by_id(self):
        conn = _make_connection()
        result = asyncio.get_event_loop().run_until_complete(
            resolve_partner(conn, 5, None)
        )
        assert result == 5

    def test_resolve_partner_by_name(self):
        conn = _make_connection()
        conn.execute_kw = AsyncMock(return_value=[(7, "Test Partner")])

        result = asyncio.get_event_loop().run_until_complete(
            resolve_partner(conn, None, "Test Partner")
        )
        assert result == 7


class TestResolveProduct:
    def test_resolve_product_by_id(self):
        conn = _make_connection()
        result = asyncio.get_event_loop().run_until_complete(
            resolve_product(conn, 3, None)
        )
        assert result == 3

    def test_resolve_product_by_name(self):
        conn = _make_connection()
        conn.execute_kw = AsyncMock(return_value=[(15, "Widget A")])

        result = asyncio.get_event_loop().run_until_complete(
            resolve_product(conn, None, "Widget")
        )
        assert result == 15


class TestResolveOrder:
    def test_resolve_order_by_id(self):
        conn = _make_connection()
        result = asyncio.get_event_loop().run_until_complete(
            resolve_order(conn, "sale.order", 99, None)
        )
        assert result == 99

    def test_resolve_order_by_name(self):
        conn = _make_connection()
        conn.execute_kw = AsyncMock(return_value=[(42, "SO042")])

        result = asyncio.get_event_loop().run_until_complete(
            resolve_order(conn, "sale.order", None, "SO042")
        )
        assert result == 42
