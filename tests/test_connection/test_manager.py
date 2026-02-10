"""Tests for connection manager (Task 1.8)."""

from __future__ import annotations

import base64
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from odoo_mcp.config import OdooMcpConfig
from odoo_mcp.connection.manager import ConnectionManager
from odoo_mcp.connection.protocol import (
    AuthenticationError,
    ConnectionError,
    ConnectionState,
    Json2EndpointNotFoundError,
    OdooVersion,
    SessionExpiredError,
)


@pytest.fixture
def config():
    return OdooMcpConfig(
        odoo_url="https://test.odoo.com",
        odoo_db="testdb",
        odoo_username="admin",
        odoo_password="admin",
        odoo_protocol="xmlrpc",
        health_check_interval=300,
        reconnect_max_attempts=2,
        reconnect_backoff_base=0,  # No delay in tests
    )


@pytest.fixture
def manager(config):
    return ConnectionManager(config)


class TestConnectionManager:

    def test_initial_state(self, manager):
        assert manager.state == ConnectionState.DISCONNECTED
        assert not manager.is_ready
        assert manager.protocol is None
        assert manager.uid is None
        assert manager.database == "testdb"
        assert manager.server_url == "https://test.odoo.com"

    @pytest.mark.asyncio
    async def test_connect_success(self, manager):
        with (
            patch(
                "odoo_mcp.connection.manager.detect_version",
                new_callable=AsyncMock,
                return_value=OdooVersion(
                    major=17, minor=0, full_string="17.0", edition="community"
                ),
            ),
            patch(
                "odoo_mcp.connection.manager.detect_edition",
                new_callable=AsyncMock,
                return_value="community",
            ),
            patch(
                "odoo_mcp.connection.manager.XmlRpcAdapter"
            ) as MockAdapter,
        ):
            mock_adapter = AsyncMock()
            mock_adapter.authenticate = AsyncMock(return_value=2)
            mock_adapter.set_base_context = MagicMock()
            mock_adapter.protocol_name = "xmlrpc"
            MockAdapter.return_value = mock_adapter

            await manager.connect()

            assert manager.state == ConnectionState.READY
            assert manager.is_ready
            assert manager.uid == 2

    @pytest.mark.asyncio
    async def test_connect_auth_failure(self, manager):
        with (
            patch(
                "odoo_mcp.connection.manager.detect_version",
                new_callable=AsyncMock,
                return_value=OdooVersion(major=17, minor=0, full_string="17.0"),
            ),
            patch(
                "odoo_mcp.connection.manager.XmlRpcAdapter"
            ) as MockAdapter,
        ):
            mock_adapter = AsyncMock()
            mock_adapter.authenticate = AsyncMock(
                side_effect=AuthenticationError("Bad credentials")
            )
            mock_adapter.set_base_context = MagicMock()
            MockAdapter.return_value = mock_adapter

            with pytest.raises(AuthenticationError):
                await manager.connect()
            assert manager.state == ConnectionState.ERROR

    @pytest.mark.asyncio
    async def test_health_check_skipped_when_recent(self, manager):
        """Health check should be skipped when activity is recent."""
        manager._state = ConnectionState.READY
        manager._uid = 2
        manager._last_activity = time.monotonic()

        mock_protocol = AsyncMock()
        manager._protocol = mock_protocol

        await manager.ensure_healthy()
        # search_count should NOT have been called
        mock_protocol.search_count.assert_not_called()

    @pytest.mark.asyncio
    async def test_health_check_triggered_after_inactivity(self, manager):
        """Health check triggers after health_check_interval seconds of inactivity."""
        manager._state = ConnectionState.READY
        manager._uid = 2
        manager._last_activity = time.monotonic() - 400  # > 300s default

        mock_protocol = AsyncMock()
        mock_protocol.search_count = AsyncMock(return_value=1)
        manager._protocol = mock_protocol

        await manager.ensure_healthy()
        mock_protocol.search_count.assert_called_once_with(
            "res.users", [("id", "=", 2)]
        )

    @pytest.mark.asyncio
    async def test_disconnect(self, manager):
        mock_protocol = AsyncMock()
        manager._protocol = mock_protocol
        manager._uid = 2
        manager._state = ConnectionState.READY

        await manager.disconnect()
        assert manager.state == ConnectionState.DISCONNECTED
        assert manager.uid is None
        mock_protocol.close.assert_called_once()

    def test_get_connection_info(self, manager):
        manager._uid = 2
        manager._username = "admin"
        manager._odoo_version = OdooVersion(
            major=17, minor=0, full_string="17.0", edition="enterprise"
        )
        manager._state = ConnectionState.READY

        mock_protocol = MagicMock()
        mock_protocol.protocol_name = "xmlrpc"
        manager._protocol = mock_protocol

        info = manager.get_connection_info()
        assert info["url"] == "https://test.odoo.com"
        assert info["database"] == "testdb"
        assert info["uid"] == 2
        assert info["username"] == "admin"
        assert info["odoo_version"] == "17.0"
        assert info["protocol"] == "xmlrpc"
        assert info["edition"] == "enterprise"
        assert info["state"] == "ready"

    @pytest.mark.asyncio
    async def test_execute_with_retry_success(self, manager):
        """Successful execute_with_retry should update last_activity."""
        manager._state = ConnectionState.READY
        manager._uid = 2
        manager._last_activity = time.monotonic()

        mock_protocol = AsyncMock()
        mock_protocol.execute_kw = AsyncMock(return_value=[{"id": 1}])
        manager._protocol = mock_protocol

        result = await manager.execute_with_retry("res.partner", "search_read", [[]])
        assert result == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_execute_with_retry_session_expired(self, manager):
        """Session expiry should trigger reconnection and retry."""
        manager._state = ConnectionState.READY
        manager._uid = 2
        manager._last_activity = time.monotonic()

        mock_protocol = AsyncMock()
        mock_protocol.execute_kw = AsyncMock(
            side_effect=SessionExpiredError("expired")
        )
        manager._protocol = mock_protocol

        with patch.object(manager, "_reconnect", new_callable=AsyncMock) as mock_reconnect:
            # After reconnect, protocol should succeed
            async def set_new_protocol():
                new_proto = AsyncMock()
                new_proto.execute_kw = AsyncMock(return_value=[{"id": 1}])
                manager._protocol = new_proto
                manager._state = ConnectionState.READY

            mock_reconnect.side_effect = set_new_protocol

            result = await manager.execute_with_retry(
                "res.partner", "search_read", [[]]
            )
            assert result == [{"id": 1}]
            mock_reconnect.assert_called_once()


class TestConnectionManagerProtocolSelection:
    """Test protocol auto-selection."""

    @pytest.mark.asyncio
    async def test_auto_selects_xmlrpc_for_v14(self):
        config = OdooMcpConfig(
            odoo_url="https://test.odoo.com",
            odoo_db="testdb",
            odoo_username="admin",
            odoo_password="admin",
            odoo_protocol="auto",
        )
        manager = ConnectionManager(config)

        with (
            patch(
                "odoo_mcp.connection.manager.detect_version",
                new_callable=AsyncMock,
                return_value=OdooVersion(major=14, minor=0, full_string="14.0"),
            ),
            patch(
                "odoo_mcp.connection.manager.detect_edition",
                new_callable=AsyncMock,
                return_value="community",
            ),
            patch(
                "odoo_mcp.connection.manager.XmlRpcAdapter"
            ) as MockAdapter,
        ):
            mock_adapter = AsyncMock()
            mock_adapter.authenticate = AsyncMock(return_value=2)
            mock_adapter.set_base_context = MagicMock()
            mock_adapter.protocol_name = "xmlrpc"
            MockAdapter.return_value = mock_adapter

            await manager.connect()
            MockAdapter.assert_called_once()

    @pytest.mark.asyncio
    async def test_auto_selects_jsonrpc_for_v17(self):
        config = OdooMcpConfig(
            odoo_url="https://test.odoo.com",
            odoo_db="testdb",
            odoo_username="admin",
            odoo_password="admin",
            odoo_protocol="auto",
        )
        manager = ConnectionManager(config)

        with (
            patch(
                "odoo_mcp.connection.manager.detect_version",
                new_callable=AsyncMock,
                return_value=OdooVersion(major=17, minor=0, full_string="17.0"),
            ),
            patch(
                "odoo_mcp.connection.manager.detect_edition",
                new_callable=AsyncMock,
                return_value="community",
            ),
            patch(
                "odoo_mcp.connection.manager.JsonRpcAdapter"
            ) as MockAdapter,
        ):
            mock_adapter = AsyncMock()
            mock_adapter.authenticate = AsyncMock(return_value=2)
            mock_adapter.set_base_context = MagicMock()
            mock_adapter.protocol_name = "jsonrpc"
            MockAdapter.return_value = mock_adapter

            await manager.connect()
            MockAdapter.assert_called_once()

    @pytest.mark.asyncio
    async def test_auto_selects_json2_for_v19(self):
        config = OdooMcpConfig(
            odoo_url="https://test.odoo.com",
            odoo_db="testdb",
            odoo_username="admin",
            odoo_password="admin",
            odoo_api_key="test-key",
            odoo_protocol="auto",
        )
        manager = ConnectionManager(config)

        with (
            patch(
                "odoo_mcp.connection.manager.detect_version",
                new_callable=AsyncMock,
                return_value=OdooVersion(major=19, minor=0, full_string="19.0"),
            ),
            patch(
                "odoo_mcp.connection.manager.detect_edition",
                new_callable=AsyncMock,
                return_value="community",
            ),
            patch(
                "odoo_mcp.connection.manager.Json2Adapter"
            ) as MockAdapter,
        ):
            mock_adapter = AsyncMock()
            mock_adapter.authenticate = AsyncMock(return_value=2)
            mock_adapter.set_base_context = MagicMock()
            mock_adapter.protocol_name = "json2"
            MockAdapter.return_value = mock_adapter

            await manager.connect()
            MockAdapter.assert_called_once()

    @pytest.mark.asyncio
    async def test_json2_requires_api_key(self):
        config = OdooMcpConfig(
            odoo_url="https://test.odoo.com",
            odoo_db="testdb",
            odoo_username="admin",
            odoo_password="admin",
            odoo_protocol="json2",
        )
        manager = ConnectionManager(config)

        with patch(
            "odoo_mcp.connection.manager.detect_version",
            new_callable=AsyncMock,
            return_value=OdooVersion(major=19, minor=0, full_string="19.0"),
        ):
            with pytest.raises(AuthenticationError, match="requires an API key"):
                await manager.connect()


class TestJson2XmlRpcFallback:
    """Tests for JSON-2 → XML-RPC transparent fallback."""

    @pytest.fixture
    def json2_config(self):
        return OdooMcpConfig(
            odoo_url="https://test.odoo.com",
            odoo_db="testdb",
            odoo_username="admin",
            odoo_password="admin",
            odoo_api_key="test-key",
            odoo_protocol="json2",
            health_check_interval=300,
            reconnect_max_attempts=2,
            reconnect_backoff_base=0,
        )

    @pytest.fixture
    def json2_manager(self, json2_config):
        mgr = ConnectionManager(json2_config)
        # Pre-configure as if already connected with JSON-2
        mgr._state = ConnectionState.READY
        mgr._uid = 2
        mgr._last_activity = time.monotonic()
        mock_protocol = AsyncMock()
        mock_protocol.protocol_name = "json2"
        mock_protocol._base_context = {"lang": "en_US"}
        mgr._protocol = mock_protocol
        return mgr

    @pytest.mark.asyncio
    async def test_404_triggers_fallback_and_succeeds(self, json2_manager):
        """A 404 from JSON-2 should transparently fall back to XML-RPC."""
        json2_manager._protocol.execute_kw = AsyncMock(
            side_effect=Json2EndpointNotFoundError(
                "Model 'project.task' or method 'write' not found",
                model="project.task",
                method="write",
            )
        )

        mock_xmlrpc = AsyncMock()
        mock_xmlrpc.execute_kw = AsyncMock(return_value=True)
        mock_xmlrpc.set_base_context = MagicMock()

        with patch(
            "odoo_mcp.connection.manager.XmlRpcAdapter",
            return_value=mock_xmlrpc,
        ):
            result = await json2_manager.execute_with_retry(
                "project.task", "write", [[1], {"name": "Updated"}]
            )

        assert result is True
        assert ("project.task", "write") in json2_manager._fallback_methods
        mock_xmlrpc.authenticate.assert_called_once()

    @pytest.mark.asyncio
    async def test_cached_method_skips_json2(self, json2_manager):
        """A cached model/method pair should go directly to XML-RPC."""
        json2_manager._fallback_methods.add(("project.task", "write"))

        mock_xmlrpc = AsyncMock()
        mock_xmlrpc.execute_kw = AsyncMock(return_value=True)
        mock_xmlrpc.set_base_context = MagicMock()

        with patch(
            "odoo_mcp.connection.manager.XmlRpcAdapter",
            return_value=mock_xmlrpc,
        ):
            result = await json2_manager.execute_with_retry(
                "project.task", "write", [[1], {"name": "Updated"}]
            )

        assert result is True
        # JSON-2 protocol should NOT have been called
        json2_manager._protocol.execute_kw.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_adapter_created_once(self, json2_manager):
        """The XML-RPC fallback adapter should be created only once."""
        json2_manager._protocol.execute_kw = AsyncMock(
            side_effect=Json2EndpointNotFoundError(
                "not found", model="project.task", method="write"
            )
        )

        mock_xmlrpc = AsyncMock()
        mock_xmlrpc.execute_kw = AsyncMock(return_value=True)
        mock_xmlrpc.set_base_context = MagicMock()

        with patch(
            "odoo_mcp.connection.manager.XmlRpcAdapter",
            return_value=mock_xmlrpc,
        ) as MockAdapter:
            await json2_manager.execute_with_retry(
                "project.task", "write", [[1], {"name": "A"}]
            )
            # Second call uses cache, but fallback adapter already exists
            await json2_manager.execute_with_retry(
                "project.task", "write", [[2], {"name": "B"}]
            )

        # XmlRpcAdapter constructor called only once
        MockAdapter.assert_called_once()
        mock_xmlrpc.authenticate.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_read_fallback(self, json2_manager):
        """search_read should also fall back on Json2EndpointNotFoundError."""
        json2_manager._protocol.search_read = AsyncMock(
            side_effect=Json2EndpointNotFoundError(
                "not found", model="project.task", method="search_read"
            )
        )

        mock_xmlrpc = AsyncMock()
        mock_xmlrpc.search_read = AsyncMock(
            return_value=[{"id": 1, "name": "Task 1"}]
        )
        mock_xmlrpc.set_base_context = MagicMock()

        with patch(
            "odoo_mcp.connection.manager.XmlRpcAdapter",
            return_value=mock_xmlrpc,
        ):
            result = await json2_manager.search_read(
                "project.task", [], fields=["name"], limit=10
            )

        assert result == [{"id": 1, "name": "Task 1"}]
        assert ("project.task", "search_read") in json2_manager._fallback_methods

    @pytest.mark.asyncio
    async def test_disconnect_cleans_up_fallback(self, json2_manager):
        """disconnect() should close the fallback adapter and clear the cache."""
        mock_xmlrpc = AsyncMock()
        json2_manager._xmlrpc_fallback = mock_xmlrpc
        json2_manager._fallback_methods.add(("project.task", "write"))

        await json2_manager.disconnect()

        mock_xmlrpc.close.assert_called_once()
        assert json2_manager._xmlrpc_fallback is None
        assert len(json2_manager._fallback_methods) == 0
        assert json2_manager.state == ConnectionState.DISCONNECTED


class TestRenderReportHttp:
    """Tests for HTTP-based report PDF download."""

    @pytest.fixture
    def xmlrpc_manager(self):
        config = OdooMcpConfig(
            odoo_url="https://test.odoo.com",
            odoo_db="testdb",
            odoo_username="admin",
            odoo_password="admin",
            odoo_protocol="xmlrpc",
            health_check_interval=300,
        )
        mgr = ConnectionManager(config)
        mgr._state = ConnectionState.READY
        mgr._uid = 2
        mgr._last_activity = time.monotonic()
        mock_protocol = AsyncMock()
        mock_protocol.protocol_name = "xmlrpc"
        mgr._protocol = mock_protocol
        return mgr

    @pytest.fixture
    def jsonrpc_manager(self):
        config = OdooMcpConfig(
            odoo_url="https://test.odoo.com",
            odoo_db="testdb",
            odoo_username="admin",
            odoo_password="admin",
            odoo_protocol="jsonrpc",
            health_check_interval=300,
        )
        mgr = ConnectionManager(config)
        mgr._state = ConnectionState.READY
        mgr._uid = 2
        mgr._last_activity = time.monotonic()

        mock_protocol = MagicMock()
        mock_protocol.protocol_name = "jsonrpc"
        mock_protocol._client = AsyncMock(spec=httpx.AsyncClient)
        mock_protocol.__class__ = type(
            "JsonRpcAdapter",
            (),
            {"__instancecheck__": classmethod(lambda cls, inst: True)},
        )
        mgr._protocol = mock_protocol
        return mgr

    @pytest.mark.asyncio
    async def test_http_report_success(self, xmlrpc_manager):
        """HTTP /report/pdf/ returns 200 with PDF content."""
        pdf_bytes = b"%PDF-1.4 test content"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/pdf"}
        mock_response.content = pdf_bytes

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        # Pre-set the HTTP client to skip session auth
        xmlrpc_manager._report_http_client = mock_client
        xmlrpc_manager._owns_report_client = True

        result = await xmlrpc_manager.render_report(
            "sale.report_saleorder", [42]
        )

        assert result["format"] == "pdf"
        expected_b64 = base64.b64encode(pdf_bytes).decode("ascii")
        assert result["result"] == expected_b64
        mock_client.get.assert_called_once_with(
            "/report/pdf/sale.report_saleorder/42"
        )

    @pytest.mark.asyncio
    async def test_http_report_multiple_ids(self, xmlrpc_manager):
        """Multiple record IDs are comma-separated in the URL."""
        pdf_bytes = b"%PDF-1.4 multi"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/pdf"}
        mock_response.content = pdf_bytes

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        xmlrpc_manager._report_http_client = mock_client
        xmlrpc_manager._owns_report_client = True

        result = await xmlrpc_manager.render_report(
            "sale.report_saleorder", [1, 2, 3]
        )

        assert result["format"] == "pdf"
        mock_client.get.assert_called_once_with(
            "/report/pdf/sale.report_saleorder/1,2,3"
        )

    @pytest.mark.asyncio
    async def test_http_report_fallback_to_xmlrpc_on_non_pdf(self, xmlrpc_manager):
        """Falls back to XML-RPC when HTTP returns non-PDF content (Odoo 14)."""
        # Set Odoo 14 so the XML-RPC /xmlrpc/2/report fallback is used
        xmlrpc_manager._odoo_version = OdooVersion(major=14, minor=0, full_string="14.0")

        # HTTP returns HTML (e.g. login page redirect)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_response.content = b"<html>login</html>"

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)
        xmlrpc_manager._report_http_client = mock_client
        xmlrpc_manager._owns_report_client = True

        # Set up XmlRpc fallback via protocol (it's XmlRpcAdapter mock)
        pdf_b64 = base64.b64encode(b"%PDF-1.4 fallback").decode("ascii")
        xmlrpc_manager._protocol.render_report = AsyncMock(
            return_value={"result": pdf_b64, "format": "pdf"}
        )
        # Make isinstance check work for XmlRpcAdapter
        from odoo_mcp.connection.xmlrpc_adapter import XmlRpcAdapter
        xmlrpc_manager._protocol.__class__ = XmlRpcAdapter

        result = await xmlrpc_manager.render_report(
            "sale.report_saleorder", [1]
        )

        assert result["format"] == "pdf"
        assert result["result"] == pdf_b64
        xmlrpc_manager._protocol.render_report.assert_called_once_with(
            "sale.report_saleorder", [1]
        )

    @pytest.mark.asyncio
    async def test_http_report_fallback_on_404(self, xmlrpc_manager):
        """Falls back to XML-RPC when HTTP returns 404 (Odoo 14)."""
        # Set Odoo 14 so the XML-RPC /xmlrpc/2/report fallback is used
        xmlrpc_manager._odoo_version = OdooVersion(major=14, minor=0, full_string="14.0")

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.headers = {"content-type": "text/html"}
        mock_response.content = b"Not Found"

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)
        xmlrpc_manager._report_http_client = mock_client
        xmlrpc_manager._owns_report_client = True

        pdf_b64 = base64.b64encode(b"%PDF-1.4").decode("ascii")
        xmlrpc_manager._protocol.render_report = AsyncMock(
            return_value={"result": pdf_b64, "format": "pdf"}
        )
        from odoo_mcp.connection.xmlrpc_adapter import XmlRpcAdapter
        xmlrpc_manager._protocol.__class__ = XmlRpcAdapter

        result = await xmlrpc_manager.render_report(
            "sale.report_saleorder", [1]
        )

        assert result["result"] == pdf_b64

    @pytest.mark.asyncio
    async def test_http_report_fallback_on_exception(self, xmlrpc_manager):
        """Falls back to XML-RPC when HTTP client raises an exception (Odoo 14)."""
        # Set Odoo 14 so the XML-RPC /xmlrpc/2/report fallback is used
        xmlrpc_manager._odoo_version = OdooVersion(major=14, minor=0, full_string="14.0")

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.ReadTimeout("timeout"))
        xmlrpc_manager._report_http_client = mock_client
        xmlrpc_manager._owns_report_client = True

        pdf_b64 = base64.b64encode(b"%PDF-1.4").decode("ascii")
        xmlrpc_manager._protocol.render_report = AsyncMock(
            return_value={"result": pdf_b64, "format": "pdf"}
        )
        from odoo_mcp.connection.xmlrpc_adapter import XmlRpcAdapter
        xmlrpc_manager._protocol.__class__ = XmlRpcAdapter

        result = await xmlrpc_manager.render_report(
            "sale.report_saleorder", [1]
        )

        assert result["result"] == pdf_b64

    @pytest.mark.asyncio
    async def test_get_report_client_creates_for_jsonrpc(self):
        """For JsonRpcAdapter, a new client is created with session cookie but no Content-Type."""
        from odoo_mcp.connection.jsonrpc_adapter import JsonRpcAdapter

        config = OdooMcpConfig(
            odoo_url="https://test.odoo.com",
            odoo_db="testdb",
            odoo_username="admin",
            odoo_password="admin",
            odoo_protocol="jsonrpc",
            health_check_interval=300,
        )
        mgr = ConnectionManager(config)
        mgr._state = ConnectionState.READY
        mgr._uid = 2
        mgr._last_activity = time.monotonic()

        mock_httpx_client = MagicMock(spec=httpx.AsyncClient)
        mock_httpx_client.cookies = httpx.Cookies()
        mock_httpx_client.cookies.set("session_id", "test-session-123")
        mock_protocol = MagicMock(spec=JsonRpcAdapter)
        mock_protocol.protocol_name = "jsonrpc"
        mock_protocol._client = mock_httpx_client
        mock_protocol._session_id = "test-session-123"
        mgr._protocol = mock_protocol

        client = await mgr._get_report_http_client()

        # Should NOT reuse the adapter's client (which has Content-Type: application/json)
        assert client is not mock_httpx_client
        assert mgr._owns_report_client is True
        # The new client should NOT have Content-Type: application/json
        assert client.headers.get("Content-Type", "") != "application/json"
        await client.aclose()

    @pytest.mark.asyncio
    async def test_get_report_client_creates_bearer_for_json2(self):
        """For Json2Adapter, a new client with Bearer auth (no Content-Type) is created."""
        from odoo_mcp.connection.json2_adapter import Json2Adapter

        config = OdooMcpConfig(
            odoo_url="https://test.odoo.com",
            odoo_db="testdb",
            odoo_username="admin",
            odoo_password="admin",
            odoo_api_key="test-key",
            odoo_protocol="json2",
            health_check_interval=300,
        )
        mgr = ConnectionManager(config)
        mgr._state = ConnectionState.READY
        mgr._uid = 2
        mgr._last_activity = time.monotonic()

        mock_protocol = MagicMock(spec=Json2Adapter)
        mock_protocol.protocol_name = "json2"
        mock_protocol._client = AsyncMock(spec=httpx.AsyncClient)
        mgr._protocol = mock_protocol

        client = await mgr._get_report_http_client()

        # Should NOT reuse the adapter's client (which has Content-Type: application/json)
        assert client is not mock_protocol._client
        assert mgr._owns_report_client is True
        # The new client should have Bearer auth but no Content-Type: application/json
        assert "Authorization" in client.headers
        assert client.headers["Authorization"] == "Bearer test-key"
        assert client.headers.get("Content-Type", "") != "application/json"
        await client.aclose()

    @pytest.mark.asyncio
    async def test_get_report_client_creates_for_xmlrpc(self):
        """For XmlRpcAdapter, a new httpx client is created and session-authenticated."""
        config = OdooMcpConfig(
            odoo_url="https://test.odoo.com",
            odoo_db="testdb",
            odoo_username="admin",
            odoo_password="admin",
            odoo_protocol="xmlrpc",
            health_check_interval=300,
        )
        mgr = ConnectionManager(config)
        mgr._state = ConnectionState.READY
        mgr._uid = 2
        mgr._last_activity = time.monotonic()

        mock_protocol = AsyncMock()
        mock_protocol.protocol_name = "xmlrpc"
        mgr._protocol = mock_protocol

        # Mock httpx.AsyncClient to capture creation and POST call
        mock_auth_response = MagicMock()
        mock_auth_response.json.return_value = {
            "result": {"uid": 2, "session_id": "abc123"}
        }
        mock_auth_response.cookies = {"session_id": "abc123"}

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=mock_auth_response)
        mock_client.cookies = MagicMock()

        with patch("odoo_mcp.connection.manager.httpx.AsyncClient", return_value=mock_client):
            client = await mgr._get_report_http_client()

        assert client is mock_client
        assert mgr._owns_report_client is True
        mock_client.post.assert_called_once()
        # Verify session cookie was set
        mock_client.cookies.set.assert_called_once_with("session_id", "abc123")

    @pytest.mark.asyncio
    async def test_disconnect_closes_owned_report_client(self):
        """disconnect() closes the report HTTP client only if we own it."""
        config = OdooMcpConfig(
            odoo_url="https://test.odoo.com",
            odoo_db="testdb",
            odoo_username="admin",
            odoo_password="admin",
            odoo_protocol="xmlrpc",
            health_check_interval=300,
        )
        mgr = ConnectionManager(config)
        mgr._state = ConnectionState.READY
        mgr._uid = 2

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mgr._report_http_client = mock_client
        mgr._owns_report_client = True

        mock_protocol = AsyncMock()
        mgr._protocol = mock_protocol

        await mgr.disconnect()

        mock_client.aclose.assert_called_once()
        assert mgr._report_http_client is None
        assert mgr._owns_report_client is False

    @pytest.mark.asyncio
    async def test_disconnect_skips_closing_unowned_client(self):
        """disconnect() does NOT close a report client it does not own."""
        config = OdooMcpConfig(
            odoo_url="https://test.odoo.com",
            odoo_db="testdb",
            odoo_username="admin",
            odoo_password="admin",
            odoo_protocol="jsonrpc",
            health_check_interval=300,
        )
        mgr = ConnectionManager(config)
        mgr._state = ConnectionState.READY
        mgr._uid = 2

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mgr._report_http_client = mock_client
        mgr._owns_report_client = False  # Not owned

        mock_protocol = AsyncMock()
        mgr._protocol = mock_protocol

        await mgr.disconnect()

        mock_client.aclose.assert_not_called()
        assert mgr._report_http_client is None
