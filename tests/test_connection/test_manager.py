"""Tests for connection manager (Task 1.8)."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from odoo_mcp.config import OdooMcpConfig
from odoo_mcp.connection.manager import ConnectionManager
from odoo_mcp.connection.protocol import (
    AuthenticationError,
    ConnectionError,
    ConnectionState,
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
