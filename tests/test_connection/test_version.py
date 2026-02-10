"""Tests for version detection (Task 1.4)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from odoo_mcp.connection.protocol import OdooVersion
from odoo_mcp.connection.version import (
    detect_version,
    parse_version,
    recommended_protocol,
)


class TestOdooVersionComparison:
    """Test OdooVersion rich comparison operators."""

    def test_lt_int(self):
        assert OdooVersion(major=16) < 17
        assert not OdooVersion(major=17) < 17

    def test_le_int(self):
        assert OdooVersion(major=17) <= 17
        assert OdooVersion(major=16) <= 17

    def test_gt_int(self):
        assert OdooVersion(major=18) > 17
        assert not OdooVersion(major=17) > 17

    def test_ge_int(self):
        assert OdooVersion(major=17) >= 17
        assert OdooVersion(major=18) >= 17

    def test_eq_int(self):
        assert OdooVersion(major=17) == 17
        assert not OdooVersion(major=16) == 17

    def test_compare_two_versions(self):
        assert OdooVersion(major=16) < OdooVersion(major=17)
        assert OdooVersion(major=17, minor=1) > OdooVersion(major=17, minor=0)

    def test_compare_tuple(self):
        assert OdooVersion(major=17, minor=0, micro=1) > (17, 0, 0)

    def test_hash_consistency(self):
        v = OdooVersion(major=17)
        assert hash(v) == hash(OdooVersion(major=17))

    def test_unsupported_type_returns_not_implemented(self):
        assert OdooVersion(major=17).__eq__("17") is NotImplemented


class TestParseVersion:
    """Test version parsing for all documented formats (REQ-02a-05)."""

    def test_tuple_format(self):
        v = parse_version([17, 0, 0, "final", 0])
        assert v.major == 17
        assert v.minor == 0
        assert v.micro == 0
        assert v.level == "final"
        assert v.serial == 0

    def test_short_tuple(self):
        v = parse_version([16, 0])
        assert v.major == 16
        assert v.minor == 0
        assert v.micro == 0

    def test_string_simple(self):
        v = parse_version("17.0")
        assert v.major == 17
        assert v.minor == 0
        assert v.full_string == "17.0"

    def test_string_with_date(self):
        v = parse_version("17.0-20240101")
        assert v.major == 17
        assert v.minor == 0
        assert v.full_string == "17.0-20240101"

    def test_string_enterprise(self):
        v = parse_version("17.0e")
        assert v.major == 17
        assert v.minor == 0
        assert v.edition == "enterprise"

    def test_saas_dash(self):
        v = parse_version("saas-17.1")
        assert v.major == 17
        assert v.minor == 1
        assert v.level == "saas"

    def test_saas_tilde(self):
        v = parse_version("saas~17.1")
        assert v.major == 17
        assert v.minor == 1
        assert v.level == "saas"

    def test_version_14(self):
        v = parse_version([14, 0, 0, "final", 0])
        assert v.major == 14

    def test_version_19(self):
        v = parse_version("19.0")
        assert v.major == 19

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_version(12345)


class TestRecommendedProtocol:
    """Test version-to-protocol mapping (REQ-02a-07)."""

    def test_v14_xmlrpc(self):
        assert recommended_protocol(OdooVersion(major=14)) == "xmlrpc"

    def test_v15_xmlrpc(self):
        assert recommended_protocol(OdooVersion(major=15)) == "xmlrpc"

    def test_v16_xmlrpc(self):
        assert recommended_protocol(OdooVersion(major=16)) == "xmlrpc"

    def test_v17_jsonrpc(self):
        assert recommended_protocol(OdooVersion(major=17)) == "jsonrpc"

    def test_v18_jsonrpc(self):
        assert recommended_protocol(OdooVersion(major=18)) == "jsonrpc"

    def test_v19_json2(self):
        assert recommended_protocol(OdooVersion(major=19)) == "json2"

    def test_v20_json2(self):
        assert recommended_protocol(OdooVersion(major=20)) == "json2"

    def test_v13_fallback_xmlrpc(self):
        assert recommended_protocol(OdooVersion(major=13)) == "xmlrpc"


class TestDetectVersion:
    """Test the orchestrated version detection."""

    @pytest.mark.asyncio
    async def test_xmlrpc_probe_success(self):
        with patch(
            "odoo_mcp.connection.version.probe_xmlrpc_version",
            new_callable=AsyncMock,
            return_value={
                "server_version": "17.0-20240101",
                "server_version_info": [17, 0, 0, "final", 0],
            },
        ):
            v = await detect_version("https://test.odoo.com")
            assert v.major == 17
            assert v.minor == 0

    @pytest.mark.asyncio
    async def test_all_probes_fail_fallback(self):
        with (
            patch(
                "odoo_mcp.connection.version.probe_xmlrpc_version",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "odoo_mcp.connection.version.probe_jsonrpc_version",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "odoo_mcp.connection.version.probe_http_version",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            v = await detect_version("https://test.odoo.com", "db", "user", "pass")
            assert v.major == 14
            assert v.level == "unknown"

    @pytest.mark.asyncio
    async def test_jsonrpc_probe_fallback(self):
        with (
            patch(
                "odoo_mcp.connection.version.probe_xmlrpc_version",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "odoo_mcp.connection.version.probe_jsonrpc_version",
                new_callable=AsyncMock,
                return_value={
                    "server_version": "18.0",
                    "server_version_info": [18, 0, 0, "final", 0],
                },
            ),
        ):
            v = await detect_version("https://test.odoo.com", "db", "user", "pass")
            assert v.major == 18

    @pytest.mark.asyncio
    async def test_http_probe_fallback(self):
        with (
            patch(
                "odoo_mcp.connection.version.probe_xmlrpc_version",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "odoo_mcp.connection.version.probe_jsonrpc_version",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "odoo_mcp.connection.version.probe_http_version",
                new_callable=AsyncMock,
                return_value="16.0",
            ),
        ):
            v = await detect_version("https://test.odoo.com", "db", "user", "pass")
            assert v.major == 16
