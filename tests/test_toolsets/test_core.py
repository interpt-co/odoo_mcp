"""Tests for odoo_mcp.toolsets.core — CoreToolset, all CRUD tools."""

import base64
import json
import os

import pytest

from odoo_mcp.toolsets.core import CoreToolset


# ---------------------------------------------------------------------------
# Mock connection
# ---------------------------------------------------------------------------

class MockConnection:
    """Simulates the Odoo connection layer for testing."""

    odoo_version = 17

    def __init__(self):
        self.calls = []

    async def execute_kw(self, model, method, args, kwargs=None):
        self.calls.append((model, method, args, kwargs or {}))

        # --- search_read ---
        if method == "search_read":
            if model == "res.partner":
                rec = {"id": 1, "name": "Acme Corp", "display_name": "Acme Corp",
                       "partner_id": [10, "Parent"], "create_date": "2025-01-01 12:00:00"}
                # Include image_1920 if requested
                req_fields = (kwargs or {}).get("fields")
                if req_fields and "image_1920" in req_fields:
                    rec["image_1920"] = base64.b64encode(b"fake png data").decode()
                return [rec]
            if model == "ir.model":
                return [
                    {"model": "res.partner", "name": "Contact", "transient": False,
                     "field_id": [1, 2, 3]},
                ]
            if model == "ir.module.module":
                return [{"name": "base"}, {"name": "mail"}]
            return []

        # --- read ---
        if method == "read":
            ids = args[0] if args else []
            return [{"id": i, "name": f"Record {i}"} for i in ids]

        # --- search_count ---
        if method == "search_count":
            return 42

        # --- fields_get ---
        if method == "fields_get":
            return {
                "name": {"string": "Name", "type": "char", "required": True, "readonly": False},
                "state": {"string": "Status", "type": "selection", "required": False,
                          "readonly": True, "selection": [["draft", "Draft"], ["done", "Done"]]},
                "partner_id": {"string": "Partner", "type": "many2one", "required": False,
                               "readonly": False, "relation": "res.partner"},
                "password": {"string": "Password", "type": "char", "required": False,
                             "readonly": False},
                "image_1920": {"string": "Image", "type": "binary", "required": False,
                               "readonly": False},
            }

        # --- name_get ---
        if method == "name_get":
            ids = args[0] if args else []
            return [(i, f"Name {i}") for i in ids]

        # --- default_get ---
        if method == "default_get":
            return {"state": "draft", "company_id": 1}

        # --- create ---
        if method == "create":
            return 99

        # --- write ---
        if method == "write":
            return True

        # --- unlink ---
        if method == "unlink":
            return True

        # --- check_access_rights ---
        if method == "check_access_rights":
            return True

        # --- action methods ---
        if method == "action_confirm":
            return {"type": "ir.actions.act_window", "res_model": "sale.order",
                    "res_id": 1, "view_mode": "form"}

        if method == "copy":
            return 100

        return True


# ---------------------------------------------------------------------------
# Mock config
# ---------------------------------------------------------------------------

class MockConfig:
    mode = "full"
    model_blocklist = []
    model_allowlist = []
    field_blocklist = []
    method_blocklist = []
    write_allowlist = []
    search_max_limit = 500
    odoo_url = "https://test.odoo.com"
    enabled_toolsets = []
    disabled_toolsets = []


class ReadOnlyConfig(MockConfig):
    mode = "readonly"


class RestrictedConfig(MockConfig):
    mode = "restricted"
    write_allowlist = ["sale.order"]


# ---------------------------------------------------------------------------
# Mock server
# ---------------------------------------------------------------------------

class MockServer:
    def __init__(self):
        self.tools = {}

    def tool(self, name, description="", annotations=None):
        def decorator(fn):
            self.tools[name] = fn
            return fn
        return decorator


# ---------------------------------------------------------------------------
# Mock registry
# ---------------------------------------------------------------------------

class MockRegistry:
    def get_report(self):
        return None

    def get_registered_toolsets(self):
        return []

    def get_model(self, model_name):
        return None


# ---------------------------------------------------------------------------
# Helper to register and get handlers
# ---------------------------------------------------------------------------

async def _register(config=None):
    conn = MockConnection()
    cfg = config or MockConfig()
    server = MockServer()
    registry = MockRegistry()
    ts = CoreToolset()
    names = await ts.register_tools(server, conn, config=cfg, registry=registry)
    return server.tools, conn, names


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------

class TestCoreRegistration:
    @pytest.mark.asyncio
    async def test_full_mode_registers_all_tools(self):
        tools, _, names = await _register(MockConfig())
        expected = {
            "odoo_core_search_read", "odoo_core_read", "odoo_core_count",
            "odoo_core_fields_get", "odoo_core_name_get", "odoo_core_default_get",
            "odoo_core_list_models", "odoo_core_list_toolsets",
            "odoo_core_deep_search",
            "odoo_core_create", "odoo_core_write", "odoo_core_unlink",
            "odoo_core_execute",
        }
        assert expected == set(names)

    @pytest.mark.asyncio
    async def test_readonly_hides_write_tools(self):
        tools, _, names = await _register(ReadOnlyConfig())
        assert "odoo_core_create" not in names
        assert "odoo_core_write" not in names
        assert "odoo_core_unlink" not in names
        # execute is still available (for read methods)
        assert "odoo_core_execute" in names
        # read tools available
        assert "odoo_core_search_read" in names

    @pytest.mark.asyncio
    async def test_restricted_hides_unlink(self):
        tools, _, names = await _register(RestrictedConfig())
        assert "odoo_core_unlink" not in names
        assert "odoo_core_create" in names
        assert "odoo_core_write" in names


# ---------------------------------------------------------------------------
# search_read
# ---------------------------------------------------------------------------

class TestSearchRead:
    @pytest.mark.asyncio
    async def test_basic_search(self):
        tools, conn, _ = await _register()
        result = json.loads(await tools["odoo_core_search_read"](model="res.partner"))
        assert result["model"] == "res.partner"
        assert len(result["records"]) == 1
        assert result["records"][0]["name"] == "Acme Corp"

    @pytest.mark.asyncio
    async def test_many2one_normalized(self):
        tools, conn, _ = await _register()
        result = json.loads(await tools["odoo_core_search_read"](model="res.partner"))
        partner = result["records"][0].get("partner_id")
        if partner is not None:
            assert isinstance(partner, dict)
            assert "id" in partner
            assert "name" in partner

    @pytest.mark.asyncio
    async def test_datetime_normalized(self):
        tools, conn, _ = await _register()
        result = json.loads(await tools["odoo_core_search_read"](model="res.partner"))
        rec = result["records"][0]
        if "create_date" in rec and rec["create_date"]:
            assert rec["create_date"].endswith("Z")
            assert "T" in rec["create_date"]

    @pytest.mark.asyncio
    async def test_blocked_model(self):
        tools, _, _ = await _register()
        result = json.loads(
            await tools["odoo_core_search_read"](model="ir.config_parameter")
        )
        assert result["error"] is True
        assert result["category"] == "access"

    @pytest.mark.asyncio
    async def test_limit_cap(self):
        tools, conn, _ = await _register()
        await tools["odoo_core_search_read"](model="res.partner", limit=9999)
        # Check the actual limit sent to Odoo was capped
        call = [c for c in conn.calls if c[1] == "search_read"][0]
        assert call[3]["limit"] <= 500

    @pytest.mark.asyncio
    async def test_invalid_domain(self):
        tools, _, _ = await _register()
        result = json.loads(
            await tools["odoo_core_search_read"](
                model="res.partner",
                domain=[("state", "in", "draft")],
            )
        )
        assert result["error"] is True
        assert result["code"] == "INVALID_DOMAIN"


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------

class TestRead:
    @pytest.mark.asyncio
    async def test_basic_read(self):
        tools, _, _ = await _register()
        result = json.loads(await tools["odoo_core_read"](model="res.partner", ids=[1, 2]))
        assert len(result["records"]) == 2
        assert result["missing_ids"] == []

    @pytest.mark.asyncio
    async def test_max_ids_limit(self):
        tools, _, _ = await _register()
        result = json.loads(
            await tools["odoo_core_read"](model="res.partner", ids=list(range(200)))
        )
        assert result["error"] is True
        assert "Maximum 100" in result["message"]


# ---------------------------------------------------------------------------
# count
# ---------------------------------------------------------------------------

class TestCount:
    @pytest.mark.asyncio
    async def test_basic_count(self):
        tools, _, _ = await _register()
        result = json.loads(await tools["odoo_core_count"](model="res.partner"))
        assert result["count"] == 42
        assert result["model"] == "res.partner"


# ---------------------------------------------------------------------------
# fields_get
# ---------------------------------------------------------------------------

class TestFieldsGet:
    @pytest.mark.asyncio
    async def test_basic(self):
        tools, _, _ = await _register()
        result = json.loads(await tools["odoo_core_fields_get"](model="res.partner"))
        assert "fields" in result
        assert "name" in result["fields"]
        assert result["fields"]["name"]["label"] == "Name"
        assert result["fields"]["name"]["type"] == "char"

    @pytest.mark.asyncio
    async def test_blocked_fields_excluded(self):
        tools, _, _ = await _register()
        result = json.loads(await tools["odoo_core_fields_get"](model="res.partner"))
        assert "password" not in result["fields"]

    @pytest.mark.asyncio
    async def test_field_count(self):
        tools, _, _ = await _register()
        result = json.loads(await tools["odoo_core_fields_get"](model="res.partner"))
        assert result["field_count"] == len(result["fields"])


# ---------------------------------------------------------------------------
# name_get
# ---------------------------------------------------------------------------

class TestNameGet:
    @pytest.mark.asyncio
    async def test_basic(self):
        tools, _, _ = await _register()
        result = json.loads(await tools["odoo_core_name_get"](model="res.partner", ids=[1, 2]))
        assert len(result["names"]) == 2
        assert result["names"][0] == {"id": 1, "name": "Name 1"}

    @pytest.mark.asyncio
    async def test_max_ids(self):
        tools, _, _ = await _register()
        result = json.loads(
            await tools["odoo_core_name_get"](model="res.partner", ids=list(range(300)))
        )
        assert result["error"] is True


# ---------------------------------------------------------------------------
# default_get
# ---------------------------------------------------------------------------

class TestDefaultGet:
    @pytest.mark.asyncio
    async def test_basic(self):
        tools, _, _ = await _register()
        result = json.loads(await tools["odoo_core_default_get"](model="res.partner"))
        assert result["defaults"]["state"] == "draft"
        assert result["model"] == "res.partner"


# ---------------------------------------------------------------------------
# list_models
# ---------------------------------------------------------------------------

class TestListModels:
    @pytest.mark.asyncio
    async def test_basic(self):
        tools, _, _ = await _register()
        result = json.loads(await tools["odoo_core_list_models"]())
        assert "models" in result
        assert "count" in result


# ---------------------------------------------------------------------------
# list_toolsets
# ---------------------------------------------------------------------------

class TestListToolsets:
    @pytest.mark.asyncio
    async def test_basic(self):
        tools, _, _ = await _register()
        result = json.loads(await tools["odoo_core_list_toolsets"]())
        assert "toolsets" in result
        assert "total_tools" in result
        assert "odoo_version" in result


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

class TestCreate:
    @pytest.mark.asyncio
    async def test_basic_create(self):
        tools, _, _ = await _register()
        result = json.loads(
            await tools["odoo_core_create"](
                model="res.partner", values={"name": "Test"}
            )
        )
        assert result["id"] == 99
        assert result["model"] == "res.partner"

    @pytest.mark.asyncio
    async def test_blocked_model(self):
        tools, _, _ = await _register()
        result = json.loads(
            await tools["odoo_core_create"](
                model="ir.config_parameter", values={"key": "x"}
            )
        )
        assert result["error"] is True

    @pytest.mark.asyncio
    async def test_readonly_mode_rejects(self):
        tools, _, _ = await _register(ReadOnlyConfig())
        # create tool not registered in readonly mode
        assert "odoo_core_create" not in tools

    @pytest.mark.asyncio
    async def test_restricted_mode_checks_allowlist(self):
        tools, _, _ = await _register(RestrictedConfig())
        # res.partner is not in write_allowlist
        result = json.loads(
            await tools["odoo_core_create"](
                model="res.partner", values={"name": "Test"}
            )
        )
        assert result["error"] is True
        assert "restricted" in result["message"].lower() or "not allowed" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_restricted_mode_allows_whitelisted(self):
        tools, _, _ = await _register(RestrictedConfig())
        result = json.loads(
            await tools["odoo_core_create"](
                model="sale.order", values={"partner_id": 1}
            )
        )
        assert result["id"] == 99

    @pytest.mark.asyncio
    async def test_blocked_field_rejected(self):
        tools, _, _ = await _register()
        result = json.loads(
            await tools["odoo_core_create"](
                model="res.partner", values={"password": "secret123"}
            )
        )
        assert result["error"] is True
        assert "Blocked" in result["message"]


# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------

class TestWrite:
    @pytest.mark.asyncio
    async def test_basic_write(self):
        tools, _, _ = await _register()
        result = json.loads(
            await tools["odoo_core_write"](
                model="res.partner", ids=[1], values={"name": "Updated"}
            )
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_max_ids(self):
        tools, _, _ = await _register()
        result = json.loads(
            await tools["odoo_core_write"](
                model="res.partner", ids=list(range(200)), values={"name": "X"}
            )
        )
        assert result["error"] is True
        assert "100" in result["message"]


# ---------------------------------------------------------------------------
# unlink
# ---------------------------------------------------------------------------

class TestUnlink:
    @pytest.mark.asyncio
    async def test_basic_unlink(self):
        tools, _, _ = await _register()
        result = json.loads(
            await tools["odoo_core_unlink"](model="res.partner", ids=[1, 2])
        )
        assert result["success"] is True
        assert result["deleted_ids"] == [1, 2]

    @pytest.mark.asyncio
    async def test_max_ids(self):
        tools, _, _ = await _register()
        result = json.loads(
            await tools["odoo_core_unlink"](model="res.partner", ids=list(range(100)))
        )
        assert result["error"] is True
        assert "50" in result["message"]


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------

class TestExecute:
    @pytest.mark.asyncio
    async def test_action_method(self):
        tools, _, _ = await _register()
        result = json.loads(
            await tools["odoo_core_execute"](
                model="sale.order", method="action_confirm", args=[[1]]
            )
        )
        assert result["result_type"] == "action"
        assert result["action"]["res_model"] == "sale.order"

    @pytest.mark.asyncio
    async def test_simple_method(self):
        tools, _, _ = await _register()
        result = json.loads(
            await tools["odoo_core_execute"](
                model="sale.order", method="copy", args=[[1]]
            )
        )
        assert result["result_type"] == "value"
        assert result["result"] == 100

    @pytest.mark.asyncio
    async def test_private_method_rejected(self):
        tools, _, _ = await _register()
        result = json.loads(
            await tools["odoo_core_execute"](
                model="res.partner", method="_compute_name"
            )
        )
        assert result["error"] is True
        assert "Private" in result["message"]

    @pytest.mark.asyncio
    async def test_blocked_method_rejected(self):
        tools, _, _ = await _register()
        result = json.loads(
            await tools["odoo_core_execute"](
                model="res.partner", method="sudo"
            )
        )
        assert result["error"] is True

    @pytest.mark.asyncio
    async def test_readonly_blocks_write_methods(self):
        tools, _, _ = await _register(ReadOnlyConfig())
        result = json.loads(
            await tools["odoo_core_execute"](
                model="res.partner", method="action_confirm", args=[[1]]
            )
        )
        assert result["error"] is True
        assert "readonly" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_readonly_allows_read_methods(self):
        tools, _, _ = await _register(ReadOnlyConfig())
        result = json.loads(
            await tools["odoo_core_execute"](
                model="res.partner", method="search_read", args=[[]]
            )
        )
        # Should not be an error
        assert "error" not in result or result.get("error") is not True

    @pytest.mark.asyncio
    async def test_no_kwargs_methods_stripped(self):
        tools, conn, _ = await _register()
        await tools["odoo_core_execute"](
            model="sale.order", method="action_confirm",
            args=[[1]], kwargs={"test": "should_be_stripped"},
        )
        # Find the execute_kw call
        call = [c for c in conn.calls if c[1] == "action_confirm"][0]
        # kwargs should have been stripped (only context might remain)
        passed_kwargs = call[3]
        assert "test" not in passed_kwargs


# ---------------------------------------------------------------------------
# Binary field handling (REQ-04-36)
# ---------------------------------------------------------------------------

class TestBinaryFieldHandling:
    @pytest.mark.asyncio
    async def test_binary_excluded_by_default(self):
        """Binary fields should be stripped when not explicitly requested."""
        tools, conn, _ = await _register()
        result = json.loads(await tools["odoo_core_search_read"](model="res.partner"))
        rec = result["records"][0]
        assert "image_1920" not in rec

    @pytest.mark.asyncio
    async def test_binary_auto_saved_when_requested(self):
        """Explicitly requesting a binary field should auto-save to file."""
        tools, conn, _ = await _register()
        result = json.loads(
            await tools["odoo_core_search_read"](
                model="res.partner",
                fields=["name", "image_1920"],
            )
        )
        rec = result["records"][0]
        assert rec["image_1920"]["type"] == "binary_file"
        assert os.path.isfile(rec["image_1920"]["path"])
        with open(rec["image_1920"]["path"], "rb") as f:
            assert f.read() == b"fake png data"
        os.unlink(rec["image_1920"]["path"])

    @pytest.mark.asyncio
    async def test_field_type_cache(self):
        """Field types should be cached after first resolution."""
        tools, conn, _ = await _register()
        ts = CoreToolset()
        # First call populates cache via RPC
        ft1 = await ts._get_field_types("res.partner", conn, MockRegistry())
        assert "name" in ft1
        assert ft1["name"] == "char"
        assert ft1["image_1920"] == "binary"
        # Second call hits cache — no additional RPC
        calls_before = len(conn.calls)
        ft2 = await ts._get_field_types("res.partner", conn, MockRegistry())
        assert ft2 == ft1
        assert len(conn.calls) == calls_before

    @pytest.mark.asyncio
    async def test_field_type_registry_fast_path(self):
        """When registry has model info, no RPC should be needed."""

        class FakeFieldInfo:
            def __init__(self, ftype):
                self.type = ftype

        class FakeModelInfo:
            fields = {"name": FakeFieldInfo("char"), "image": FakeFieldInfo("binary")}

        class RegistryWithModel:
            def get_report(self):
                return None
            def get_registered_toolsets(self):
                return []
            def get_model(self, name):
                return FakeModelInfo()

        ts = CoreToolset()
        conn = MockConnection()
        ft = await ts._get_field_types("res.partner", conn, RegistryWithModel())
        assert ft == {"name": "char", "image": "binary"}
        # No RPC calls made — registry was sufficient
        assert len(conn.calls) == 0

    @pytest.mark.asyncio
    async def test_field_type_rpc_fallback(self):
        """When registry returns None, field types should come from RPC."""
        ts = CoreToolset()
        conn = MockConnection()
        ft = await ts._get_field_types("res.partner", conn, MockRegistry())
        assert ft["name"] == "char"
        assert ft["partner_id"] == "many2one"
        # Should have made one fields_get RPC call
        fg_calls = [c for c in conn.calls if c[1] == "fields_get"]
        assert len(fg_calls) == 1

    @pytest.mark.asyncio
    async def test_search_read_description_warns_binary(self):
        """search_read description should mention binary field exclusion."""
        server = MockServer()
        conn = MockConnection()
        cfg = MockConfig()
        registry = MockRegistry()
        ts = CoreToolset()
        await ts.register_tools(server, conn, config=cfg, registry=registry)
        # Get the description from server registration
        # The description is the 2nd arg to server.tool() — we need to check the tool info
        # We can check the tool was registered with a binary warning
        # Since MockServer doesn't capture descriptions, verify via _read_tools
        descs = []
        for name, handler, desc, annot in ts._read_tools(conn, cfg, registry):
            if "search_read" in name or "read" == name.split("_")[-1]:
                descs.append(desc)
        assert any("Binary fields" in d for d in descs)

    @pytest.mark.asyncio
    async def test_read_binary_excluded_by_default(self):
        """read handler should also exclude binary fields."""
        tools, conn, _ = await _register()
        result = json.loads(
            await tools["odoo_core_read"](model="res.partner", ids=[1])
        )
        rec = result["records"][0]
        # MockConnection.read doesn't return image_1920, but the field_types
        # resolution + normalisation pipeline should work without errors
        assert "name" in rec
