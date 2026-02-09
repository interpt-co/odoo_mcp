"""Tests for odoo_mcp.toolsets.registry — ToolsetRegistry, topological sort, prerequisites."""

import pytest

from odoo_mcp.toolsets.base import BaseToolset, ToolsetMetadata
from odoo_mcp.toolsets.registry import (
    CircularDependencyError,
    RegistrationReport,
    ToolsetRegistry,
    _topological_sort,
)


# ---------------------------------------------------------------------------
# Mock toolsets for testing
# ---------------------------------------------------------------------------

class MockCoreToolset(BaseToolset):
    def metadata(self):
        return ToolsetMetadata(
            name="core", description="Core", version="1.0.0",
            min_odoo_version=14,
        )

    async def register_tools(self, server, connection, **kwargs):
        return ["odoo_core_search_read", "odoo_core_create"]


class MockSalesToolset(BaseToolset):
    def metadata(self):
        return ToolsetMetadata(
            name="sales", description="Sales", version="1.0.0",
            required_modules=["sale"], depends_on=["core"],
        )

    async def register_tools(self, server, connection, **kwargs):
        return ["odoo_sales_create_order"]


class MockCrmToolset(BaseToolset):
    def metadata(self):
        return ToolsetMetadata(
            name="crm", description="CRM", version="1.0.0",
            required_modules=["crm"], depends_on=["core"],
        )

    async def register_tools(self, server, connection, **kwargs):
        return ["odoo_crm_create_lead"]


class MockCircularA(BaseToolset):
    def metadata(self):
        return ToolsetMetadata(name="a", description="A", version="1.0.0", depends_on=["b"])

    async def register_tools(self, server, connection, **kwargs):
        return []


class MockCircularB(BaseToolset):
    def metadata(self):
        return ToolsetMetadata(name="b", description="B", version="1.0.0", depends_on=["a"])

    async def register_tools(self, server, connection, **kwargs):
        return []


class MockFailingToolset(BaseToolset):
    def metadata(self):
        return ToolsetMetadata(name="failing", description="Fails", version="1.0.0")

    async def register_tools(self, server, connection, **kwargs):
        raise RuntimeError("Registration exploded")


class MockDuplicateToolset(BaseToolset):
    def metadata(self):
        return ToolsetMetadata(name="dupe", description="Dupe", version="1.0.0")

    async def register_tools(self, server, connection, **kwargs):
        return ["odoo_core_search_read"]  # duplicate name


class MockVersionToolset(BaseToolset):
    def metadata(self):
        return ToolsetMetadata(
            name="versioned", description="V", version="1.0.0",
            min_odoo_version=16, max_odoo_version=18,
        )

    async def register_tools(self, server, connection, **kwargs):
        return ["odoo_versioned_tool"]


# ---------------------------------------------------------------------------
# Mock connection & config & server
# ---------------------------------------------------------------------------

class MockConnection:
    odoo_version = 17

    async def execute_kw(self, model, method, args, kwargs=None):
        if model == "ir.module.module" and method == "search_read":
            return [
                {"name": "sale"},
                {"name": "account"},
                {"name": "mail"},
            ]
        return []


class MockConfig:
    enabled_toolsets = []
    disabled_toolsets = []


class MockServer:
    """Fake MCP server that just records tool registrations."""

    def __init__(self):
        self.tools = {}

    def tool(self, name, description="", annotations=None):
        def decorator(fn):
            self.tools[name] = fn
            return fn
        return decorator


# ---------------------------------------------------------------------------
# Topological sort
# ---------------------------------------------------------------------------

class TestTopologicalSort:
    def test_no_dependencies(self):
        ts = [MockCoreToolset()]
        result = _topological_sort(ts)
        assert len(result) == 1
        assert result[0].metadata().name == "core"

    def test_dependency_ordering(self):
        ts = [MockSalesToolset(), MockCoreToolset()]
        result = _topological_sort(ts)
        names = [t.metadata().name for t in result]
        assert names.index("core") < names.index("sales")

    def test_multiple_dependants(self):
        ts = [MockCrmToolset(), MockSalesToolset(), MockCoreToolset()]
        result = _topological_sort(ts)
        names = [t.metadata().name for t in result]
        assert names.index("core") < names.index("sales")
        assert names.index("core") < names.index("crm")

    def test_circular_dependency(self):
        ts = [MockCircularA(), MockCircularB()]
        with pytest.raises(CircularDependencyError, match="Circular"):
            _topological_sort(ts)


# ---------------------------------------------------------------------------
# ToolsetRegistry
# ---------------------------------------------------------------------------

class TestToolsetRegistry:
    @pytest.mark.asyncio
    async def test_register_core_only(self):
        conn = MockConnection()
        config = MockConfig()
        server = MockServer()
        registry = ToolsetRegistry(conn, config)

        report = await registry.discover_and_register(
            server, toolset_classes=[MockCoreToolset],
        )

        assert report.registered_toolsets == 1
        assert report.total_tools == 2
        assert report.results[0].status == "registered"
        assert "odoo_core_search_read" in report.results[0].tools_registered

    @pytest.mark.asyncio
    async def test_register_with_dependencies(self):
        conn = MockConnection()
        config = MockConfig()
        server = MockServer()
        registry = ToolsetRegistry(conn, config)

        report = await registry.discover_and_register(
            server, toolset_classes=[MockCoreToolset, MockSalesToolset],
        )

        assert report.registered_toolsets == 2
        names = [r.name for r in report.results if r.status == "registered"]
        assert "core" in names
        assert "sales" in names

    @pytest.mark.asyncio
    async def test_missing_module_skips(self):
        conn = MockConnection()
        config = MockConfig()
        server = MockServer()
        registry = ToolsetRegistry(conn, config)

        class NeedsMissing(BaseToolset):
            def metadata(self):
                return ToolsetMetadata(
                    name="needs_missing", description="X", version="1.0.0",
                    required_modules=["nonexistent_module"],
                )
            async def register_tools(self, server, connection, **kwargs):
                return ["odoo_needs_missing_tool"]

        report = await registry.discover_and_register(
            server, toolset_classes=[NeedsMissing],
        )

        assert report.registered_toolsets == 0
        assert report.results[0].status == "skipped"
        assert "not installed" in report.results[0].skip_reason

    @pytest.mark.asyncio
    async def test_missing_dependency_skips(self):
        """Sales depends on core — if core isn't present, sales should be skipped."""
        conn = MockConnection()
        config = MockConfig()
        server = MockServer()
        registry = ToolsetRegistry(conn, config)

        report = await registry.discover_and_register(
            server, toolset_classes=[MockSalesToolset],
        )

        assert report.registered_toolsets == 0
        assert report.results[0].status == "skipped"
        assert "unregistered" in report.results[0].skip_reason

    @pytest.mark.asyncio
    async def test_failed_registration(self):
        conn = MockConnection()
        config = MockConfig()
        server = MockServer()
        registry = ToolsetRegistry(conn, config)

        report = await registry.discover_and_register(
            server, toolset_classes=[MockFailingToolset],
        )

        assert report.registered_toolsets == 0
        assert report.results[0].status == "failed"
        assert "exploded" in report.results[0].error

    @pytest.mark.asyncio
    async def test_duplicate_tool_name_rejected(self):
        conn = MockConnection()
        config = MockConfig()
        server = MockServer()
        registry = ToolsetRegistry(conn, config)

        report = await registry.discover_and_register(
            server, toolset_classes=[MockCoreToolset, MockDuplicateToolset],
        )

        # Core registers, dupe should fail
        dupe_result = [r for r in report.results if r.name == "dupe"][0]
        assert dupe_result.status == "failed"
        assert "Duplicate" in dupe_result.error

    @pytest.mark.asyncio
    async def test_version_check_skips(self):
        class OldConnection(MockConnection):
            odoo_version = 14  # too old for MockVersionToolset (min 16)

        conn = OldConnection()
        config = MockConfig()
        server = MockServer()
        registry = ToolsetRegistry(conn, config)

        report = await registry.discover_and_register(
            server, toolset_classes=[MockVersionToolset],
        )

        assert report.registered_toolsets == 0
        assert report.results[0].status == "skipped"
        assert ">=" in report.results[0].skip_reason

    @pytest.mark.asyncio
    async def test_disabled_toolset_skips(self):
        conn = MockConnection()
        config = MockConfig()
        config.disabled_toolsets = ["core"]
        server = MockServer()
        registry = ToolsetRegistry(conn, config)

        report = await registry.discover_and_register(
            server, toolset_classes=[MockCoreToolset],
        )

        assert report.registered_toolsets == 0
        assert report.results[0].status == "skipped"

    @pytest.mark.asyncio
    async def test_enabled_toolsets_filter(self):
        conn = MockConnection()
        config = MockConfig()
        config.enabled_toolsets = ["core"]  # only core
        server = MockServer()
        registry = ToolsetRegistry(conn, config)

        report = await registry.discover_and_register(
            server, toolset_classes=[MockCoreToolset, MockSalesToolset],
        )

        assert report.registered_toolsets == 1
        assert report.results[0].name == "core"
        assert report.results[0].status == "registered"

    @pytest.mark.asyncio
    async def test_get_toolset_for_tool(self):
        conn = MockConnection()
        config = MockConfig()
        server = MockServer()
        registry = ToolsetRegistry(conn, config)

        await registry.discover_and_register(
            server, toolset_classes=[MockCoreToolset],
        )

        meta = registry.get_toolset_for_tool("odoo_core_search_read")
        assert meta is not None
        assert meta.name == "core"

        assert registry.get_toolset_for_tool("nonexistent") is None

    @pytest.mark.asyncio
    async def test_get_registered_toolsets(self):
        conn = MockConnection()
        config = MockConfig()
        server = MockServer()
        registry = ToolsetRegistry(conn, config)

        await registry.discover_and_register(
            server, toolset_classes=[MockCoreToolset],
        )

        toolsets = registry.get_registered_toolsets()
        assert len(toolsets) == 1
        assert toolsets[0].name == "core"

    @pytest.mark.asyncio
    async def test_report_has_timestamp(self):
        conn = MockConnection()
        config = MockConfig()
        server = MockServer()
        registry = ToolsetRegistry(conn, config)

        report = await registry.discover_and_register(
            server, toolset_classes=[MockCoreToolset],
        )

        assert report.timestamp != ""
        assert "T" in report.timestamp  # ISO format
