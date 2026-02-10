"""Tests for JSON-2 adapter (Task 1.7)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from odoo_mcp.connection.protocol import (
    AccessDeniedError,
    AuthenticationError,
    ConnectionError,
    Json2EndpointNotFoundError,
    OdooRpcError,
)
from odoo_mcp.connection.json2_adapter import Json2Adapter


@pytest.fixture
def adapter():
    return Json2Adapter(
        url="https://test.odoo.com",
        api_key="test-api-key",
        timeout=10,
    )


class TestJson2Adapter:

    def test_protocol_name(self, adapter):
        assert adapter.protocol_name == "json2"

    def test_not_connected_initially(self, adapter):
        assert not adapter.is_connected()

    @pytest.mark.asyncio
    async def test_authenticate_success(self, adapter):
        exec_response = httpx.Response(
            status_code=200,
            json={"result": [{"id": 2}]},
            request=httpx.Request("POST", "https://test.odoo.com/json/2/res.users/search_read"),
        )

        with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=exec_response):
            uid = await adapter.authenticate("testdb", "admin", "admin")
            assert uid == 2
            assert adapter.is_connected()

    @pytest.mark.asyncio
    async def test_authenticate_user_not_found(self, adapter):
        exec_response = httpx.Response(
            status_code=200,
            json={"result": []},
            request=httpx.Request("POST", "https://test.odoo.com/json/2/res.users/search_read"),
        )

        with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=exec_response):
            with pytest.raises(AuthenticationError, match="User not found"):
                await adapter.authenticate("testdb", "admin", "admin")

    @pytest.mark.asyncio
    async def test_execute_kw_success(self, adapter):
        adapter._uid = 2

        exec_response = httpx.Response(
            status_code=200,
            json={"result": [{"id": 1, "name": "Test Partner"}]},
            request=httpx.Request("POST", "https://test.odoo.com/json/2/res.partner/search_read"),
        )

        with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=exec_response):
            result = await adapter.execute_kw(
                "res.partner", "search_read", [[]], {"fields": ["name"], "limit": 1}
            )
            assert result == [{"id": 1, "name": "Test Partner"}]

    @pytest.mark.asyncio
    async def test_execute_kw_401_auth_error(self, adapter):
        adapter._uid = 2

        response = httpx.Response(
            status_code=401,
            json={},
            request=httpx.Request("POST", "https://test.odoo.com/json/2/res.partner/search_read"),
        )

        with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=response):
            with pytest.raises(AuthenticationError, match="Invalid API key"):
                await adapter.execute_kw("res.partner", "search_read", [[]])

    @pytest.mark.asyncio
    async def test_execute_kw_403_access_denied(self, adapter):
        adapter._uid = 2

        response = httpx.Response(
            status_code=403,
            json={},
            request=httpx.Request("POST", "https://test.odoo.com/json/2/res.partner/search_read"),
        )

        with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=response):
            with pytest.raises(AccessDeniedError):
                await adapter.execute_kw("res.partner", "search_read", [[]])

    @pytest.mark.asyncio
    async def test_execute_kw_404_not_found(self, adapter):
        adapter._uid = 2

        response = httpx.Response(
            status_code=404,
            json={},
            request=httpx.Request("POST", "https://test.odoo.com/json/2/bad.model/search_read"),
        )

        with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=response):
            with pytest.raises(Json2EndpointNotFoundError, match="not found"):
                await adapter.execute_kw("bad.model", "search_read", [[]])

    @pytest.mark.asyncio
    async def test_execute_kw_json_error(self, adapter):
        adapter._uid = 2

        response = httpx.Response(
            status_code=200,
            json={
                "error": {
                    "message": "Server Error",
                    "data": {
                        "name": "odoo.exceptions.UserError",
                        "message": "Something went wrong",
                        "debug": "Traceback...",
                    },
                },
            },
            request=httpx.Request("POST", "https://test.odoo.com/json/2/res.partner/create"),
        )

        with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=response):
            with pytest.raises(OdooRpcError) as exc_info:
                await adapter.execute_kw("res.partner", "create", [{}])
            assert exc_info.value.error_class == "odoo.exceptions.UserError"

    @pytest.mark.asyncio
    async def test_execute_kw_timeout(self, adapter):
        adapter._uid = 2

        with patch.object(adapter._client, "post", new_callable=AsyncMock, side_effect=httpx.TimeoutException("timeout")):
            with pytest.raises(ConnectionError, match="timed out"):
                await adapter.execute_kw("res.partner", "search_read", [[]])

    @pytest.mark.asyncio
    async def test_execute_kw_connect_error(self, adapter):
        adapter._uid = 2

        with patch.object(adapter._client, "post", new_callable=AsyncMock, side_effect=httpx.ConnectError("refused")):
            with pytest.raises(ConnectionError, match="Connection failed"):
                await adapter.execute_kw("res.partner", "search_read", [[]])

    @pytest.mark.asyncio
    async def test_context_merging(self, adapter):
        adapter._uid = 2
        adapter.set_base_context({"lang": "en_US"})

        exec_response = httpx.Response(
            status_code=200,
            json={"result": []},
            request=httpx.Request("POST", "https://test.odoo.com/json/2/res.partner/search_read"),
        )

        with patch.object(adapter._client, "post", new_callable=AsyncMock, return_value=exec_response) as mock_post:
            await adapter.execute_kw(
                "res.partner", "search_read", [[]],
                context={"tz": "Europe/Lisbon"},
            )

            call_kwargs = mock_post.call_args
            sent_json = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
            assert sent_json["context"]["lang"] == "en_US"
            assert sent_json["context"]["tz"] == "Europe/Lisbon"

    @pytest.mark.asyncio
    async def test_close(self, adapter):
        adapter._uid = 2
        with patch.object(adapter._client, "aclose", new_callable=AsyncMock):
            await adapter.close()
            assert not adapter.is_connected()
