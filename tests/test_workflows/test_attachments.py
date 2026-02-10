"""Tests for attachments toolset."""

from __future__ import annotations

import asyncio
import base64
from unittest.mock import AsyncMock, MagicMock

import pytest

from odoo_mcp.toolsets.attachments import (
    AttachmentsToolset,
    TEXT_MIME_TYPES,
    MAX_ATTACHMENT_SIZE_BYTES,
)


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


class TestAttachmentsToolsetMetadata:
    def test_metadata(self):
        ts = AttachmentsToolset()
        meta = ts.metadata()
        assert meta.name == "attachments"
        assert meta.required_modules == []
        assert "core" in meta.depends_on


class TestAttachmentsToolsetRegistration:
    def test_registers_all_tools(self):
        ts = AttachmentsToolset()
        server, registered = _make_server()
        conn = _make_connection()
        names = asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))
        assert set(names) == {
            "odoo_attachments_list",
            "odoo_attachments_get_content",
            "odoo_attachments_upload",
            "odoo_attachments_delete",
        }


class TestAttachmentsList:
    def test_list_basic(self):
        ts = AttachmentsToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        conn.search_read = AsyncMock(return_value=[
            {
                "id": 1,
                "name": "test.pdf",
                "mimetype": "application/pdf",
                "file_size": 1024,
                "create_date": "2025-01-01",
                "create_uid": [2, "Admin"],
            }
        ])

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_attachments_list"](
                model="sale.order", record_id=42
            )
        )
        assert result["count"] == 1
        assert result["attachments"][0]["name"] == "test.pdf"
        assert result["attachments"][0]["file_size_human"] == "1.0 KB"

    def test_list_missing_params(self):
        ts = AttachmentsToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_attachments_list"]()
        )
        assert result["status"] == "error"


class TestAttachmentsGetContent:
    def test_get_content_text(self):
        ts = AttachmentsToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        text_content = base64.b64encode(b"id,name\n1,test").decode("ascii")
        conn.search_read = AsyncMock(side_effect=[
            # metadata
            [{"name": "data.csv", "mimetype": "text/csv", "file_size": 20}],
            # content
            [{"datas": text_content}],
        ])

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_attachments_get_content"](
                attachment_id=1, as_text=True
            )
        )
        assert result["encoding"] == "text"
        assert "id,name" in result["content"]

    def test_get_content_binary(self):
        ts = AttachmentsToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        b64_content = base64.b64encode(b"\x89PNG\r\n").decode("ascii")
        conn.search_read = AsyncMock(side_effect=[
            [{"name": "image.png", "mimetype": "image/png", "file_size": 100}],
            [{"datas": b64_content}],
        ])

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_attachments_get_content"](attachment_id=1)
        )
        assert result["encoding"] == "base64"
        assert result["content_base64"] == b64_content

    def test_get_content_oversized(self):
        ts = AttachmentsToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        conn.search_read = AsyncMock(return_value=[
            {
                "name": "huge.bin",
                "mimetype": "application/octet-stream",
                "file_size": MAX_ATTACHMENT_SIZE_BYTES + 1,
            }
        ])

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_attachments_get_content"](attachment_id=1)
        )
        assert "warning" in result
        assert result["encoding"] is None

    def test_get_content_not_found(self):
        ts = AttachmentsToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        conn.search_read = AsyncMock(return_value=[])

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_attachments_get_content"](attachment_id=999)
        )
        assert result["status"] == "error"


class TestAttachmentsUpload:
    def test_upload_basic(self):
        ts = AttachmentsToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        conn.execute_kw = AsyncMock(return_value=10)

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_attachments_upload"](
                model="sale.order",
                record_id=42,
                name="report.pdf",
                content_base64="JVBERi0=",
            )
        )
        assert result["id"] == 10
        assert result["mimetype"] == "application/pdf"  # auto-detected

    def test_upload_explicit_mimetype(self):
        ts = AttachmentsToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        conn.execute_kw = AsyncMock(return_value=11)

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_attachments_upload"](
                model="sale.order",
                record_id=42,
                name="data",
                content_base64="dGVzdA==",
                mimetype="text/plain",
            )
        )
        assert result["mimetype"] == "text/plain"

    def test_upload_missing_params(self):
        ts = AttachmentsToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_attachments_upload"](
                model="sale.order", record_id=42
            )
        )
        assert result["status"] == "error"


class TestAttachmentsDelete:
    def test_delete_basic(self):
        ts = AttachmentsToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        conn.search_read = AsyncMock(return_value=[{"name": "old.pdf"}])
        conn.execute_kw = AsyncMock(return_value=None)

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_attachments_delete"](attachment_id=1)
        )
        assert result["name"] == "old.pdf"
        assert "deleted" in result["message"].lower()

    def test_delete_not_found(self):
        ts = AttachmentsToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        conn.search_read = AsyncMock(return_value=[])

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_attachments_delete"](attachment_id=999)
        )
        assert result["status"] == "error"


class TestAttachmentsGetContentSavePath:
    def test_save_path_writes_file(self, tmp_path):
        ts = AttachmentsToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        zip_bytes = b"PK\x03\x04fake-zip-content-here"
        b64_content = base64.b64encode(zip_bytes).decode("ascii")
        conn.search_read = AsyncMock(side_effect=[
            [{"name": "project.zip", "mimetype": "application/zip", "file_size": len(zip_bytes)}],
            [{"datas": b64_content}],
        ])

        dest = tmp_path / "downloads" / "project.zip"
        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_attachments_get_content"](
                attachment_id=1, save_path=str(dest)
            )
        )
        assert dest.exists()
        assert dest.read_bytes() == zip_bytes
        assert result["saved_to"] == str(dest.resolve())
        assert "project.zip" in result["message"]
        assert "content_base64" not in result
        assert "encoding" not in result

    def test_save_path_creates_parent_dirs(self, tmp_path):
        ts = AttachmentsToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        content = b"hello"
        b64_content = base64.b64encode(content).decode("ascii")
        conn.search_read = AsyncMock(side_effect=[
            [{"name": "data.bin", "mimetype": "application/octet-stream", "file_size": len(content)}],
            [{"datas": b64_content}],
        ])

        dest = tmp_path / "a" / "b" / "c" / "data.bin"
        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_attachments_get_content"](
                attachment_id=1, save_path=str(dest)
            )
        )
        assert dest.exists()
        assert dest.read_bytes() == content

    def test_save_path_empty_content_returns_error(self):
        ts = AttachmentsToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        conn.search_read = AsyncMock(side_effect=[
            [{"name": "empty.bin", "mimetype": "application/octet-stream", "file_size": 0}],
            [{"datas": ""}],
        ])

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_attachments_get_content"](
                attachment_id=1, save_path="/tmp/empty.bin"
            )
        )
        assert result["status"] == "error"
        assert "no content" in result["message"].lower()

    def test_save_path_invalid_path_returns_error(self, tmp_path):
        ts = AttachmentsToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        b64_content = base64.b64encode(b"data").decode("ascii")
        conn.search_read = AsyncMock(side_effect=[
            [{"name": "file.bin", "mimetype": "application/octet-stream", "file_size": 4}],
            [{"datas": b64_content}],
        ])

        # Use /dev/null/impossible as an invalid path
        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_attachments_get_content"](
                attachment_id=1, save_path="/dev/null/impossible/file.bin"
            )
        )
        assert result["status"] == "error"
        assert "failed to save" in result["message"].lower()

    def test_save_path_skipped_for_oversized(self):
        ts = AttachmentsToolset()
        server, registered = _make_server()
        conn = _make_connection()
        asyncio.get_event_loop().run_until_complete(ts.register_tools(server, conn))

        conn.search_read = AsyncMock(return_value=[
            {
                "name": "huge.bin",
                "mimetype": "application/octet-stream",
                "file_size": MAX_ATTACHMENT_SIZE_BYTES + 1,
            }
        ])

        result = asyncio.get_event_loop().run_until_complete(
            registered["odoo_attachments_get_content"](
                attachment_id=1, save_path="/tmp/huge.bin"
            )
        )
        assert "warning" in result
        assert result["encoding"] is None


class TestTextMimeTypes:
    def test_text_mime_types_defined(self):
        assert "text/plain" in TEXT_MIME_TYPES
        assert "text/csv" in TEXT_MIME_TYPES
        assert "application/json" in TEXT_MIME_TYPES
        assert "image/png" not in TEXT_MIME_TYPES
