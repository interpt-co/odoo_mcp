"""Shared test fixtures for odoo-mcp tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from typing import Any

import pytest

from odoo_mcp.config import OdooMcpConfig
from odoo_mcp.connection.protocol import BaseOdooProtocol, OdooVersion, ConnectionState


# ---------------------------------------------------------------------------
# Minimal valid config for tests
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_config() -> OdooMcpConfig:
    """Return a minimal valid config (no URL validation fires)."""
    return OdooMcpConfig(
        odoo_url="https://test.odoo.com",
        odoo_db="testdb",
        odoo_username="admin",
        odoo_password="admin",
    )


@pytest.fixture
def full_config() -> OdooMcpConfig:
    """Return a fully populated config."""
    return OdooMcpConfig(
        odoo_url="https://test.odoo.com",
        odoo_db="testdb",
        odoo_username="admin",
        odoo_password="admin",
        odoo_api_key="test-api-key",
        odoo_protocol="auto",
        odoo_timeout=30,
        transport="stdio",
        mode="readonly",
        log_level="info",
    )


# ---------------------------------------------------------------------------
# Mock protocol adapter
# ---------------------------------------------------------------------------

class MockProtocol(BaseOdooProtocol):
    """Mock Odoo protocol for unit tests."""

    def __init__(self) -> None:
        super().__init__()
        self._uid: int | None = None
        self._connected = False
        self.execute_kw_mock = AsyncMock()

    @property
    def protocol_name(self) -> str:
        return "mock"

    async def authenticate(self, db: str, login: str, password: str) -> int:
        self._uid = 2
        self._connected = True
        return 2

    async def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> Any:
        return await self.execute_kw_mock(model, method, args, kwargs, context)

    async def version_info(self) -> dict:
        return {
            "server_version": "17.0",
            "server_version_info": [17, 0, 0, "final", 0],
        }

    async def close(self) -> None:
        self._connected = False
        self._uid = None

    def is_connected(self) -> bool:
        return self._connected


@pytest.fixture
def mock_protocol() -> MockProtocol:
    return MockProtocol()


@pytest.fixture
def odoo_version_17() -> OdooVersion:
    return OdooVersion(
        major=17, minor=0, micro=0, level="final", serial=0,
        full_string="17.0", edition="community",
    )
