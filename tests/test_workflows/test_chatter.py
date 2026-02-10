"""Tests for chatter toolset."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from odoo_mcp.toolsets.chatter import ChatterToolset, ACTIVITY_TYPE_MAP


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


class TestChatterToolsetMetadata:
    def test_metadata(self):
        ts = ChatterToolset()
        meta = ts.metadata()
        assert meta.name == "chatter"
        assert "mail" in meta.required_modules
        assert "core" in meta.depends_on


class TestChatterToolsetRegistration:
    def test_registers_all_tools(self):
        ts = ChatterToolset()
        server, registered = _make_server()
        conn = _make_connection()
        names = asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))
        assert set(names) == {
            "odoo_chatter_get_messages",
            "odoo_chatter_post_message",
            "odoo_chatter_get_activities",
            "odoo_chatter_schedule_activity",
        }


class TestGetMessages:
    def test_get_messages_basic(self):
        ts = ChatterToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        conn.search_read = AsyncMock(return_value=[
            {
                "id": 1,
                "body": "<p>Hello World</p>",
                "author_id": [2, "Admin"],
                "date": "2025-01-01 10:00:00",
                "message_type": "comment",
                "subtype_id": [1, "Discussions"],
                "email_from": "admin@example.com",
                "subject": None,
            }
        ])

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_chatter_get_messages"](
                model="sale.order", record_id=42
            )
        )
        assert result["model"] == "sale.order"
        assert result["record_id"] == 42
        assert result["count"] == 1
        assert result["messages"][0]["body"] == "Hello World"  # HTML stripped

    def test_get_messages_no_html_strip(self):
        ts = ChatterToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        conn.search_read = AsyncMock(return_value=[
            {
                "id": 1,
                "body": "<p>Hello <b>World</b></p>",
                "author_id": [2, "Admin"],
                "date": "2025-01-01",
                "message_type": "comment",
                "subtype_id": False,
                "email_from": "",
                "subject": None,
            }
        ])

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_chatter_get_messages"](
                model="sale.order", record_id=42, strip_html_content=False
            )
        )
        assert "<p>" in result["messages"][0]["body"]

    def test_get_messages_missing_params(self):
        ts = ChatterToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_chatter_get_messages"]()
        )
        assert result["status"] == "error"

    def test_get_messages_limit_capped(self):
        ts = ChatterToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        conn.search_read = AsyncMock(return_value=[])

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_chatter_get_messages"](
                model="sale.order", record_id=1, limit=200
            )
        )
        # Should have been capped to 100
        call_args = conn.search_read.call_args
        assert call_args.kwargs.get("limit", call_args[1].get("limit")) == 100


class TestPostMessage:
    def test_post_message_basic(self):
        ts = ChatterToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        conn.execute_kw = AsyncMock(return_value=101)

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_chatter_post_message"](
                model="sale.order", record_id=42, body="Test message"
            )
        )
        assert result["message_id"] == 101
        # Verify body was wrapped in <p>
        call_kwargs = conn.execute_kw.call_args.kwargs.get(
            "kwargs", conn.execute_kw.call_args[1].get("kwargs", {})
        )
        assert call_kwargs.get("body") == "<p>Test message</p>"

    def test_post_message_no_body(self):
        ts = ChatterToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_chatter_post_message"](
                model="sale.order", record_id=42
            )
        )
        assert result["status"] == "error"


class TestGetActivities:
    def test_get_activities(self):
        ts = ChatterToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        conn.search_read = AsyncMock(return_value=[
            {
                "id": 1,
                "activity_type_id": [1, "To Do"],
                "summary": "Follow up",
                "note": "Call back",
                "date_deadline": "2025-01-15",
                "user_id": [2, "Admin"],
                "state": "planned",
            }
        ])

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_chatter_get_activities"](
                model="crm.lead", record_id=5
            )
        )
        assert result["count"] == 1
        assert result["activities"][0]["summary"] == "Follow up"


class TestScheduleActivity:
    def test_schedule_activity_basic(self):
        ts = ChatterToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        call_idx = 0

        async def mock_execute(model, method, args=None, **kwargs):
            nonlocal call_idx
            call_idx += 1
            if method == "xmlid_to_res_id":
                return 1
            if method == "create":
                return 10
            return None

        async def mock_search_read(model, domain, **kwargs):
            if model == "ir.model":
                return [{"id": 42}]
            return []

        conn.execute_kw = mock_execute
        conn.search_read = mock_search_read

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_chatter_schedule_activity"](
                model="sale.order",
                record_id=1,
                activity_type="todo",
                summary="Review order",
            )
        )
        assert result["id"] == 10

    def test_schedule_activity_unknown_type(self):
        ts = ChatterToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_chatter_schedule_activity"](
                model="sale.order",
                record_id=1,
                activity_type="invalid_type",
                summary="Test",
            )
        )
        assert result["status"] == "error"

    def test_activity_type_map_completeness(self):
        expected = {"email", "call", "meeting", "todo", "upload_document"}
        assert set(ACTIVITY_TYPE_MAP.keys()) == expected
