"""Tests for JSON-RPC adapter (Task 1.6)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from odoo_mcp.connection.protocol import (
    AccessDeniedError,
    AuthenticationError,
    ConnectionError,
    OdooRpcError,
    SessionExpiredError,
)
from odoo_mcp.connection.jsonrpc_adapter import JsonRpcAdapter


@pytest.fixture
def adapter():
    return JsonRpcAdapter(url="https://test.odoo.com", timeout=10)


def _make_response(
    json_data: dict,
    status_code: int = 200,
    cookies: dict | None = None,
) -> httpx.Response:
    """Helper to create a mock httpx.Response."""
    response = httpx.Response(
        status_code=status_code,
        json=json_data,
        request=httpx.Request("POST", "https://test.odoo.com/test"),
    )
    if cookies:
        for name, value in cookies.items():
            response.headers["set-cookie"] = f"{name}={value}"
    return response


class TestJsonRpcAdapter:

    def test_protocol_name(self, adapter):
        assert adapter.protocol_name == "jsonrpc"

    def test_not_connected_initially(self, adapter):
        assert not adapter.is_connected()

    @pytest.mark.asyncio
    async def test_authenticate_success(self, adapter):
        mock_response = httpx.Response(
            status_code=200,
            json={"jsonrpc": "2.0", "id": 1, "result": {
                "uid": 2,
                "name": "Admin",
                "username": "admin",
                "is_admin": True,
                "server_version": "17.0",
            }},
            request=httpx.Request("POST", "https://test.odoo.com/web/session/authenticate"),
        )
        mock_response.headers["set-cookie"] = "session_id=abc123"

        with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=mock_response):
            uid = await adapter.authenticate("testdb", "admin", "admin")
            assert uid == 2
            assert adapter.is_connected()

    @pytest.mark.asyncio
    async def test_authenticate_error_response(self, adapter):
        mock_response = httpx.Response(
            status_code=200,
            json={"jsonrpc": "2.0", "id": 1, "error": {"message": "Access Denied"}},
            request=httpx.Request("POST", "https://test.odoo.com/web/session/authenticate"),
        )

        with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(AuthenticationError, match="Access Denied"):
                await adapter.authenticate("testdb", "admin", "wrong")

    @pytest.mark.asyncio
    async def test_authenticate_no_uid(self, adapter):
        mock_response = httpx.Response(
            status_code=200,
            json={"jsonrpc": "2.0", "id": 1, "result": {"uid": False}},
            request=httpx.Request("POST", "https://test.odoo.com/web/session/authenticate"),
        )

        with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(AuthenticationError, match="no uid returned"):
                await adapter.authenticate("testdb", "admin", "wrong")

    @pytest.mark.asyncio
    async def test_execute_kw_success(self, adapter):
        # Authenticate first
        auth_response = httpx.Response(
            status_code=200,
            json={"jsonrpc": "2.0", "id": 1, "result": {"uid": 2, "server_version": "17.0"}},
            request=httpx.Request("POST", "https://test.odoo.com/web/session/authenticate"),
        )
        exec_response = httpx.Response(
            status_code=200,
            json={"jsonrpc": "2.0", "id": 2, "result": [{"id": 1, "name": "Test"}]},
            request=httpx.Request("POST", "https://test.odoo.com/web/dataset/call_kw/res.partner/search_read"),
        )

        with patch.object(adapter._client, "post", new_callable=AsyncMock, side_effect=[auth_response, exec_response]):
            await adapter.authenticate("testdb", "admin", "admin")
            result = await adapter.execute_kw(
                "res.partner", "search_read", [[]], {"fields": ["name"], "limit": 1}
            )
            assert result == [{"id": 1, "name": "Test"}]

    @pytest.mark.asyncio
    async def test_execute_kw_session_expired_401(self, adapter):
        adapter._uid = 2
        adapter._db = "testdb"

        expired_response = httpx.Response(
            status_code=401,
            json={},
            request=httpx.Request("POST", "https://test.odoo.com/web/dataset/call_kw/res.partner/search_read"),
        )

        with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=expired_response):
            with pytest.raises(SessionExpiredError):
                await adapter.execute_kw("res.partner", "search_read", [[]])

    @pytest.mark.asyncio
    async def test_execute_kw_access_denied_403(self, adapter):
        adapter._uid = 2
        adapter._db = "testdb"

        denied_response = httpx.Response(
            status_code=403,
            json={},
            request=httpx.Request("POST", "https://test.odoo.com/web/dataset/call_kw/res.partner/search_read"),
        )

        with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=denied_response):
            with pytest.raises(AccessDeniedError):
                await adapter.execute_kw("res.partner", "search_read", [[]])

    @pytest.mark.asyncio
    async def test_execute_kw_jsonrpc_error(self, adapter):
        adapter._uid = 2
        adapter._db = "testdb"

        error_response = httpx.Response(
            status_code=200,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "error": {
                    "message": "Odoo Server Error",
                    "code": 200,
                    "data": {
                        "name": "odoo.exceptions.ValidationError",
                        "message": "Name is required",
                        "debug": "Traceback...",
                    },
                },
            },
            request=httpx.Request("POST", "https://test.odoo.com/web/dataset/call_kw/res.partner/create"),
        )

        with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=error_response):
            with pytest.raises(OdooRpcError) as exc_info:
                await adapter.execute_kw("res.partner", "create", [{}])
            assert exc_info.value.error_class == "odoo.exceptions.ValidationError"

    @pytest.mark.asyncio
    async def test_execute_kw_session_expired_code_100(self, adapter):
        adapter._uid = 2
        adapter._db = "testdb"

        error_response = httpx.Response(
            status_code=200,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "error": {
                    "code": 100,
                    "message": "Odoo Session Expired",
                    "data": {},
                },
            },
            request=httpx.Request("POST", "https://test.odoo.com/web/dataset/call_kw/res.partner/search_read"),
        )

        with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=error_response):
            with pytest.raises(SessionExpiredError):
                await adapter.execute_kw("res.partner", "search_read", [[]])

    @pytest.mark.asyncio
    async def test_execute_kw_timeout(self, adapter):
        adapter._uid = 2
        adapter._db = "testdb"

        with patch.object(adapter._client, "post", new_callable=AsyncMock, side_effect=httpx.TimeoutException("timeout")):
            with pytest.raises(ConnectionError, match="timed out"):
                await adapter.execute_kw("res.partner", "search_read", [[]])

    @pytest.mark.asyncio
    async def test_execute_kw_connect_error(self, adapter):
        adapter._uid = 2
        adapter._db = "testdb"

        with patch.object(adapter._client, "post", new_callable=AsyncMock, side_effect=httpx.ConnectError("refused")):
            with pytest.raises(ConnectionError, match="Connection failed"):
                await adapter.execute_kw("res.partner", "search_read", [[]])

    @pytest.mark.asyncio
    async def test_close(self, adapter):
        adapter._uid = 2
        with patch.object(adapter._client, "aclose", new_callable=AsyncMock):
            await adapter.close()
            assert not adapter.is_connected()
