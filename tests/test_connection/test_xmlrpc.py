"""Tests for XML-RPC adapter (Task 1.5)."""

from __future__ import annotations

import xmlrpc.client
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from odoo_mcp.connection.protocol import (
    AuthenticationError,
    ConnectionError,
    OdooRpcError,
)
from odoo_mcp.connection.xmlrpc_adapter import XmlRpcAdapter


@pytest.fixture
def adapter():
    return XmlRpcAdapter(url="https://test.odoo.com", timeout=10)


class TestXmlRpcAdapter:

    def test_protocol_name(self, adapter):
        assert adapter.protocol_name == "xmlrpc"

    def test_not_connected_initially(self, adapter):
        assert not adapter.is_connected()

    @pytest.mark.asyncio
    async def test_authenticate_success(self, adapter):
        with patch.object(adapter, "_get_common") as mock_common:
            proxy = MagicMock()
            proxy.authenticate.return_value = 2
            mock_common.return_value = proxy

            uid = await adapter.authenticate("testdb", "admin", "admin")
            assert uid == 2
            assert adapter.is_connected()

    @pytest.mark.asyncio
    async def test_authenticate_failure(self, adapter):
        with patch.object(adapter, "_get_common") as mock_common:
            proxy = MagicMock()
            proxy.authenticate.return_value = False
            mock_common.return_value = proxy

            with pytest.raises(AuthenticationError, match="invalid credentials"):
                await adapter.authenticate("testdb", "admin", "wrong")

    @pytest.mark.asyncio
    async def test_authenticate_fault(self, adapter):
        with patch.object(adapter, "_get_common") as mock_common:
            proxy = MagicMock()
            proxy.authenticate.side_effect = xmlrpc.client.Fault(1, "Access Denied")
            mock_common.return_value = proxy

            with pytest.raises(AuthenticationError):
                await adapter.authenticate("testdb", "admin", "wrong")

    @pytest.mark.asyncio
    async def test_execute_kw_success(self, adapter):
        # First authenticate
        with patch.object(adapter, "_get_common") as mock_common:
            proxy = MagicMock()
            proxy.authenticate.return_value = 2
            mock_common.return_value = proxy
            await adapter.authenticate("testdb", "admin", "admin")

        # Then execute
        with patch.object(adapter, "_get_object") as mock_object:
            proxy = MagicMock()
            proxy.execute_kw.return_value = [{"id": 1, "name": "Test"}]
            mock_object.return_value = proxy

            result = await adapter.execute_kw(
                "res.partner", "search_read", [[]], {"fields": ["name"], "limit": 1}
            )
            assert result == [{"id": 1, "name": "Test"}]

    @pytest.mark.asyncio
    async def test_execute_kw_not_authenticated(self, adapter):
        with pytest.raises(ConnectionError, match="Not authenticated"):
            await adapter.execute_kw("res.partner", "search_read", [[]])

    @pytest.mark.asyncio
    async def test_execute_kw_fault_translated(self, adapter):
        with patch.object(adapter, "_get_common") as mock_common:
            proxy = MagicMock()
            proxy.authenticate.return_value = 2
            mock_common.return_value = proxy
            await adapter.authenticate("testdb", "admin", "admin")

        with patch.object(adapter, "_get_object") as mock_object:
            proxy = MagicMock()
            proxy.execute_kw.side_effect = xmlrpc.client.Fault(
                1, "odoo.exceptions.ValidationError: Name is required"
            )
            mock_object.return_value = proxy

            with pytest.raises(OdooRpcError) as exc_info:
                await adapter.execute_kw("res.partner", "create", [{}])
            assert exc_info.value.error_class == "odoo.exceptions.ValidationError"
            assert "Name is required" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_execute_kw_protocol_error(self, adapter):
        with patch.object(adapter, "_get_common") as mock_common:
            proxy = MagicMock()
            proxy.authenticate.return_value = 2
            mock_common.return_value = proxy
            await adapter.authenticate("testdb", "admin", "admin")

        with patch.object(adapter, "_get_object") as mock_object:
            proxy = MagicMock()
            proxy.execute_kw.side_effect = xmlrpc.client.ProtocolError(
                "https://test.odoo.com/xmlrpc/2/object",
                500,
                "Internal Server Error",
                {},
            )
            mock_object.return_value = proxy

            with pytest.raises(ConnectionError, match="XML-RPC protocol error"):
                await adapter.execute_kw("res.partner", "read", [[1]])

    @pytest.mark.asyncio
    async def test_execute_kw_os_error(self, adapter):
        with patch.object(adapter, "_get_common") as mock_common:
            proxy = MagicMock()
            proxy.authenticate.return_value = 2
            mock_common.return_value = proxy
            await adapter.authenticate("testdb", "admin", "admin")

        with patch.object(adapter, "_get_object") as mock_object:
            proxy = MagicMock()
            proxy.execute_kw.side_effect = OSError("Connection refused")
            mock_object.return_value = proxy

            with pytest.raises(ConnectionError, match="Network error"):
                await adapter.execute_kw("res.partner", "read", [[1]])

    @pytest.mark.asyncio
    async def test_context_merging(self, adapter):
        with patch.object(adapter, "_get_common") as mock_common:
            proxy = MagicMock()
            proxy.authenticate.return_value = 2
            mock_common.return_value = proxy
            await adapter.authenticate("testdb", "admin", "admin")

        adapter.set_base_context({"lang": "en_US"})

        with patch.object(adapter, "_get_object") as mock_object:
            proxy = MagicMock()
            proxy.execute_kw.return_value = []
            mock_object.return_value = proxy

            await adapter.execute_kw(
                "res.partner", "search_read", [[]],
                context={"tz": "Europe/Lisbon"},
            )

            call_args = proxy.execute_kw.call_args
            kwargs = call_args[0][6]  # 7th positional arg is kwargs dict
            assert kwargs["context"]["lang"] == "en_US"
            assert kwargs["context"]["tz"] == "Europe/Lisbon"

    @pytest.mark.asyncio
    async def test_close(self, adapter):
        with patch.object(adapter, "_get_common") as mock_common:
            proxy = MagicMock()
            proxy.authenticate.return_value = 2
            mock_common.return_value = proxy
            await adapter.authenticate("testdb", "admin", "admin")

        assert adapter.is_connected()
        await adapter.close()
        assert not adapter.is_connected()

    @pytest.mark.asyncio
    async def test_version_info(self, adapter):
        with patch.object(adapter, "_get_common") as mock_common:
            proxy = MagicMock()
            proxy.version.return_value = {
                "server_version": "17.0",
                "server_version_info": [17, 0, 0, "final", 0],
            }
            mock_common.return_value = proxy

            result = await adapter.version_info()
            assert result["server_version"] == "17.0"
