"""Tests for reports toolset."""

from __future__ import annotations

import asyncio
import base64
from unittest.mock import AsyncMock, MagicMock

import pytest

from odoo_mcp.toolsets.reports import ReportsToolset


def _make_connection(odoo_version: int = 17) -> MagicMock:
    conn = MagicMock()
    conn.execute_kw = AsyncMock(return_value=None)
    conn.search_read = AsyncMock(return_value=[])
    conn.odoo_version = odoo_version
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


class TestReportsToolsetMetadata:
    def test_metadata(self):
        ts = ReportsToolset()
        meta = ts.metadata()
        assert meta.name == "reports"
        assert meta.required_modules == []
        assert "core" in meta.depends_on


class TestReportsToolsetRegistration:
    def test_registers_all_tools(self):
        ts = ReportsToolset()
        server, registered = _make_server()
        conn = _make_connection()
        names = asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))
        assert set(names) == {
            "odoo_reports_generate",
            "odoo_reports_list",
        }


class TestReportsGenerate:
    def test_generate_missing_report_name(self):
        ts = ReportsToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_reports_generate"]()
        )
        assert result["status"] == "error"

    def test_generate_missing_record_ids(self):
        ts = ReportsToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_reports_generate"](report_name="sale.report_saleorder")
        )
        assert result["status"] == "error"

    def test_generate_too_many_records(self):
        ts = ReportsToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_reports_generate"](
                report_name="sale.report_saleorder",
                record_ids=list(range(1, 25)),
            )
        )
        assert result["status"] == "error"
        assert "20" in result["message"]

    def test_generate_success_json2(self):
        ts = ReportsToolset()
        server, registered = _make_server()
        conn = _make_connection(odoo_version=17)
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        pdf_bytes = b"%PDF-1.4 test content"
        conn.execute_kw = AsyncMock(return_value=(pdf_bytes, "pdf"))

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_reports_generate"](
                report_name="sale.report_saleorder",
                record_ids=[42],
            )
        )
        assert result["format"] == "pdf"
        assert result["content_base64"]
        assert result["file_name"] == "report_saleorder_42.pdf"
        assert result["size"] > 0

    def test_generate_success_xmlrpc(self):
        ts = ReportsToolset()
        server, registered = _make_server()
        conn = _make_connection(odoo_version=15)
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        pdf_bytes = b"%PDF-1.4 test"
        conn.execute_kw = AsyncMock(return_value=(pdf_bytes, "pdf"))

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_reports_generate"](
                report_name="sale.report_saleorder",
                record_ids=[1],
            )
        )
        assert result["format"] == "pdf"
        # For XML-RPC (v < 17), uses render_qweb_pdf
        call_args = conn.execute_kw.call_args
        assert call_args[0][1] == "render_qweb_pdf"

    def test_generate_error(self):
        ts = ReportsToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        conn.execute_kw = AsyncMock(side_effect=Exception("Report not found"))

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_reports_generate"](
                report_name="nonexistent.report",
                record_ids=[1],
            )
        )
        assert result["status"] == "error"


class TestReportsList:
    def test_list_missing_model(self):
        ts = ReportsToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_reports_list"]()
        )
        assert result["status"] == "error"

    def test_list_reports(self):
        ts = ReportsToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        conn.search_read = AsyncMock(return_value=[
            {
                "name": "Quotation / Order",
                "report_name": "sale.report_saleorder",
                "report_type": "qweb-pdf",
                "print_report_name": "SO",
            },
            {
                "name": "PRO-FORMA Invoice",
                "report_name": "sale.report_saleorder_pro_forma",
                "report_type": "qweb-pdf",
                "print_report_name": "PRO-FORMA",
            },
        ])

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_reports_list"](model="sale.order")
        )
        assert result["model"] == "sale.order"
        assert len(result["reports"]) == 2
        assert result["reports"][0]["report_name"] == "sale.report_saleorder"
