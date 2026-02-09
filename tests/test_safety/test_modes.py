"""Tests for safety mode enforcement, model/field/method filtering, and tool annotations."""

import pytest

from odoo_mcp.errors import (
    FieldBlockedError,
    MethodBlockedError,
    ModeViolationError,
    ModelAccessError,
)
from odoo_mcp.safety.modes import (
    DEFAULT_FIELD_BLOCKLIST,
    DEFAULT_METHOD_BLOCKLIST,
    DEFAULT_MODEL_BLOCKLIST,
    OperationMode,
    SafetyConfig,
    ToolAnnotation,
    enforce_mode,
    filter_fields,
    get_annotation,
    get_tool_visibility,
    validate_method,
    validate_model_access,
)


# ── Operation Mode Enum ──────────────────────────────────────────────

class TestOperationMode:
    def test_values(self):
        assert OperationMode.READONLY == "readonly"
        assert OperationMode.RESTRICTED == "restricted"
        assert OperationMode.FULL == "full"


# ── Mode Enforcement (REQ-11-03) ─────────────────────────────────────

class TestEnforceMode:
    @pytest.fixture
    def config(self):
        return SafetyConfig(
            mode=OperationMode.READONLY,
            write_allowlist=["sale.order", "crm.lead"],
        )

    # Readonly mode
    def test_readonly_allows_read(self, config):
        enforce_mode(OperationMode.READONLY, "read", "sale.order", config)

    def test_readonly_allows_search(self, config):
        enforce_mode(OperationMode.READONLY, "search", "sale.order", config)

    def test_readonly_blocks_create(self, config):
        with pytest.raises(ModeViolationError, match="not allowed in readonly"):
            enforce_mode(OperationMode.READONLY, "create", "sale.order", config)

    def test_readonly_blocks_write(self, config):
        with pytest.raises(ModeViolationError, match="not allowed in readonly"):
            enforce_mode(OperationMode.READONLY, "write", "sale.order", config)

    def test_readonly_blocks_unlink(self, config):
        with pytest.raises(ModeViolationError, match="not allowed in readonly"):
            enforce_mode(OperationMode.READONLY, "unlink", "sale.order", config)

    def test_readonly_blocks_execute(self, config):
        with pytest.raises(ModeViolationError, match="not allowed in readonly"):
            enforce_mode(OperationMode.READONLY, "execute", "sale.order", config)

    # Restricted mode
    def test_restricted_allows_read(self, config):
        enforce_mode(OperationMode.RESTRICTED, "read", "any.model", config)

    def test_restricted_allows_search(self, config):
        enforce_mode(OperationMode.RESTRICTED, "search", "any.model", config)

    def test_restricted_allows_create_on_allowlist(self, config):
        enforce_mode(OperationMode.RESTRICTED, "create", "sale.order", config)

    def test_restricted_allows_write_on_allowlist(self, config):
        enforce_mode(OperationMode.RESTRICTED, "write", "sale.order", config)

    def test_restricted_allows_execute_on_allowlist(self, config):
        enforce_mode(OperationMode.RESTRICTED, "execute", "crm.lead", config)

    def test_restricted_blocks_create_off_allowlist(self, config):
        with pytest.raises(ModeViolationError, match="not allowed in restricted"):
            enforce_mode(OperationMode.RESTRICTED, "create", "res.partner", config)

    def test_restricted_blocks_write_off_allowlist(self, config):
        with pytest.raises(ModeViolationError, match="not allowed in restricted"):
            enforce_mode(OperationMode.RESTRICTED, "write", "res.partner", config)

    def test_restricted_blocks_unlink_always(self, config):
        with pytest.raises(ModeViolationError, match="Delete not allowed"):
            enforce_mode(OperationMode.RESTRICTED, "unlink", "sale.order", config)

    # Full mode
    def test_full_allows_everything(self, config):
        for op in ("read", "search", "create", "write", "unlink", "execute"):
            enforce_mode(OperationMode.FULL, op, "any.model", config)

    # String mode values
    def test_string_mode_value(self, config):
        enforce_mode("readonly", "read", "sale.order", config)
        with pytest.raises(ModeViolationError):
            enforce_mode("readonly", "create", "sale.order", config)


# ── Tool Visibility (REQ-11-04, REQ-11-05) ──────────────────────────

class TestToolVisibility:
    def test_read_tools_visible_in_all_modes(self):
        read_tools = [
            "odoo_core_search_read", "odoo_core_read", "odoo_core_count",
            "odoo_core_fields_get", "odoo_core_name_get", "odoo_core_default_get",
            "odoo_core_deep_search",
        ]
        for tool in read_tools:
            for mode in OperationMode:
                assert get_tool_visibility(tool, mode) is True, f"{tool} should be visible in {mode}"

    def test_create_hidden_in_readonly(self):
        assert get_tool_visibility("odoo_core_create", OperationMode.READONLY) is False

    def test_create_visible_in_restricted(self):
        assert get_tool_visibility("odoo_core_create", OperationMode.RESTRICTED) is True

    def test_unlink_hidden_in_readonly_and_restricted(self):
        assert get_tool_visibility("odoo_core_unlink", OperationMode.READONLY) is False
        assert get_tool_visibility("odoo_core_unlink", OperationMode.RESTRICTED) is False

    def test_unlink_visible_in_full(self):
        assert get_tool_visibility("odoo_core_unlink", OperationMode.FULL) is True

    def test_chatter_hidden_in_readonly(self):
        assert get_tool_visibility("odoo_chatter_post_message", OperationMode.READONLY) is False

    def test_chatter_visible_in_restricted(self):
        assert get_tool_visibility("odoo_chatter_post_message", OperationMode.RESTRICTED) is True

    def test_attachments_delete_only_in_full(self):
        assert get_tool_visibility("odoo_attachments_delete", OperationMode.READONLY) is False
        assert get_tool_visibility("odoo_attachments_delete", OperationMode.RESTRICTED) is False
        assert get_tool_visibility("odoo_attachments_delete", OperationMode.FULL) is True

    def test_unknown_tool_defaults_visible(self):
        assert get_tool_visibility("unknown_tool_xyz", OperationMode.READONLY) is True

    def test_string_mode(self):
        assert get_tool_visibility("odoo_core_create", "readonly") is False
        assert get_tool_visibility("odoo_core_create", "full") is True


# ── Model Filtering (REQ-11-06 through REQ-11-09) ──────────────────

class TestModelFiltering:
    @pytest.fixture
    def config(self):
        return SafetyConfig()

    def test_default_blocklist_applied(self, config):
        for model in DEFAULT_MODEL_BLOCKLIST:
            if model == "res.users":
                continue  # special case
            with pytest.raises(ModelAccessError):
                validate_model_access(model, "read", config)

    def test_res_users_read_allowed(self, config):
        assert validate_model_access("res.users", "read", config) is True
        assert validate_model_access("res.users", "search", config) is True

    def test_res_users_write_blocked(self, config):
        with pytest.raises(ModelAccessError, match="Write access.*blocked"):
            validate_model_access("res.users", "write", config)

    def test_res_users_create_blocked(self, config):
        with pytest.raises(ModelAccessError, match="Write access.*blocked"):
            validate_model_access("res.users", "create", config)

    def test_allowlist_permits_listed_model(self):
        config = SafetyConfig(model_allowlist=["sale.order", "res.partner"])
        assert validate_model_access("sale.order", "read", config) is True

    def test_allowlist_blocks_unlisted_model(self):
        config = SafetyConfig(model_allowlist=["sale.order"])
        with pytest.raises(ModelAccessError, match="not in the model allowlist"):
            validate_model_access("res.partner", "read", config)

    def test_user_blocklist_applied(self):
        config = SafetyConfig(model_blocklist=["custom.secret"])
        with pytest.raises(ModelAccessError):
            validate_model_access("custom.secret", "read", config)

    def test_normal_model_accessible(self, config):
        assert validate_model_access("sale.order", "read", config) is True
        assert validate_model_access("res.partner", "write", config) is True


# ── Field Filtering (REQ-11-12 through REQ-11-14) ──────────────────

class TestFieldFiltering:
    @pytest.fixture
    def config(self):
        return SafetyConfig()

    def test_default_field_blocklist(self, config):
        assert "password" in config.effective_field_blocklist
        assert "api_key" in config.effective_field_blocklist
        assert "totp_secret" in config.effective_field_blocklist

    def test_filter_dict_read_removes_blocked(self, config):
        fields = {
            "name": {"type": "char"},
            "password": {"type": "char"},
            "email": {"type": "char"},
            "api_key": {"type": "char"},
        }
        filtered = filter_fields(fields, "res.users", "read", config)
        assert "name" in filtered
        assert "email" in filtered
        assert "password" not in filtered
        assert "api_key" not in filtered

    def test_filter_list_read_removes_blocked(self, config):
        fields = ["name", "password", "email", "totp_secret"]
        filtered = filter_fields(fields, "res.users", "read", config)
        assert "name" in filtered
        assert "email" in filtered
        assert "password" not in filtered
        assert "totp_secret" not in filtered

    def test_filter_write_raises_on_blocked(self, config):
        values = {"name": "Test", "password": "secret123"}
        with pytest.raises(FieldBlockedError, match="blocked field"):
            filter_fields(values, "res.users", "write", config)

    def test_filter_create_raises_on_blocked(self, config):
        values = {"name": "Test", "api_key": "xyz"}
        with pytest.raises(FieldBlockedError, match="blocked field"):
            filter_fields(values, "res.users", "create", config)

    def test_filter_write_allows_normal_fields(self, config):
        values = {"name": "Test", "email": "test@test.com"}
        result = filter_fields(values, "res.partner", "write", config)
        assert result == values

    def test_filter_none_returns_none(self, config):
        assert filter_fields(None, "any.model", "read", config) is None

    def test_user_field_blocklist_merged(self):
        config = SafetyConfig(field_blocklist=["custom_secret"])
        assert "custom_secret" in config.effective_field_blocklist
        assert "password" in config.effective_field_blocklist  # default still there


# ── Method Filtering (REQ-11-15, REQ-11-16) ──────────────────────────

class TestMethodFiltering:
    @pytest.fixture
    def config(self):
        return SafetyConfig()

    def test_default_method_blocklist(self, config):
        for method in DEFAULT_METHOD_BLOCKLIST:
            with pytest.raises(MethodBlockedError):
                validate_method(method, config)

    def test_normal_methods_allowed(self, config):
        assert validate_method("action_confirm", config) is True
        assert validate_method("action_draft", config) is True
        assert validate_method("read", config) is True
        assert validate_method("write", config) is True

    def test_sudo_blocked(self, config):
        with pytest.raises(MethodBlockedError, match="sudo"):
            validate_method("sudo", config)

    def test_with_user_blocked(self, config):
        with pytest.raises(MethodBlockedError, match="with_user"):
            validate_method("with_user", config)

    def test_uninstall_blocked(self, config):
        with pytest.raises(MethodBlockedError):
            validate_method("uninstall", config)

    def test_user_method_blocklist_merged(self):
        config = SafetyConfig(method_blocklist=["custom_danger"])
        with pytest.raises(MethodBlockedError):
            validate_method("custom_danger", config)
        with pytest.raises(MethodBlockedError):
            validate_method("sudo", config)  # default still blocked


# ── Tool Annotations (REQ-11-17, REQ-11-18) ─────────────────────────

class TestToolAnnotations:
    def test_read_tools_annotations(self):
        read_tools = [
            "odoo_core_search_read", "odoo_core_read", "odoo_core_count",
            "odoo_core_fields_get", "odoo_core_name_get", "odoo_core_default_get",
            "odoo_core_deep_search",
        ]
        for tool in read_tools:
            ann = get_annotation(tool)
            assert ann is not None, f"Missing annotation for {tool}"
            assert ann.readOnlyHint is True, f"{tool} should be readOnly"
            assert ann.destructiveHint is False, f"{tool} should not be destructive"
            assert ann.idempotentHint is True, f"{tool} should be idempotent"
            assert ann.openWorldHint is True, f"{tool} should be openWorld"

    def test_create_annotation(self):
        ann = get_annotation("odoo_core_create")
        assert ann is not None
        assert ann.readOnlyHint is False
        assert ann.destructiveHint is False
        assert ann.idempotentHint is False

    def test_write_annotation(self):
        ann = get_annotation("odoo_core_write")
        assert ann is not None
        assert ann.readOnlyHint is False
        assert ann.destructiveHint is False
        assert ann.idempotentHint is True

    def test_unlink_annotation(self):
        ann = get_annotation("odoo_core_unlink")
        assert ann is not None
        assert ann.readOnlyHint is False
        assert ann.destructiveHint is True
        assert ann.idempotentHint is True

    def test_execute_annotation(self):
        ann = get_annotation("odoo_core_execute")
        assert ann is not None
        assert ann.readOnlyHint is False
        assert ann.idempotentHint is False

    def test_workflow_create_annotation(self):
        for tool in ["odoo_sales_create_quotation", "odoo_accounting_create_invoice"]:
            ann = get_annotation(tool)
            assert ann is not None, f"Missing annotation for {tool}"
            assert ann.readOnlyHint is False
            assert ann.destructiveHint is False
            assert ann.idempotentHint is False

    def test_workflow_confirm_annotation(self):
        for tool in ["odoo_sales_confirm_order", "odoo_accounting_confirm_invoice"]:
            ann = get_annotation(tool)
            assert ann is not None, f"Missing annotation for {tool}"
            assert ann.readOnlyHint is False
            assert ann.destructiveHint is False
            assert ann.idempotentHint is True

    def test_cancel_annotation(self):
        ann = get_annotation("odoo_sales_cancel_order")
        assert ann is not None
        assert ann.readOnlyHint is False
        assert ann.idempotentHint is True

    def test_chatter_annotation(self):
        ann = get_annotation("odoo_chatter_post_message")
        assert ann is not None
        assert ann.readOnlyHint is False
        assert ann.idempotentHint is False

    def test_attachment_upload_annotation(self):
        ann = get_annotation("odoo_attachments_upload")
        assert ann is not None
        assert ann.readOnlyHint is False
        assert ann.destructiveHint is False

    def test_attachment_delete_annotation(self):
        ann = get_annotation("odoo_attachments_delete")
        assert ann is not None
        assert ann.destructiveHint is True
        assert ann.idempotentHint is True

    def test_report_annotation(self):
        ann = get_annotation("odoo_reports_generate")
        assert ann is not None
        assert ann.readOnlyHint is True
        assert ann.idempotentHint is True

    def test_unknown_tool_returns_none(self):
        assert get_annotation("nonexistent_tool") is None

    def test_annotation_to_dict(self):
        ann = ToolAnnotation(
            title="Test",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        )
        d = ann.to_dict()
        assert d["title"] == "Test"
        assert d["readOnlyHint"] is True
        assert d["destructiveHint"] is False
        assert d["idempotentHint"] is True
        assert d["openWorldHint"] is True

    def test_all_annotated_tools_have_openworld_true(self):
        """REQ-11-18: All tools have openWorldHint=True."""
        for tool_name in [
            "odoo_core_search_read", "odoo_core_read", "odoo_core_count",
            "odoo_core_create", "odoo_core_write", "odoo_core_unlink",
            "odoo_core_execute", "odoo_chatter_post_message",
            "odoo_attachments_upload", "odoo_attachments_delete",
            "odoo_reports_generate",
        ]:
            ann = get_annotation(tool_name)
            assert ann is not None
            assert ann.openWorldHint is True, f"{tool_name} should have openWorldHint=True"


# ── SafetyConfig Properties ─────────────────────────────────────────

class TestSafetyConfig:
    def test_effective_model_blocklist_includes_defaults(self):
        config = SafetyConfig()
        for model in DEFAULT_MODEL_BLOCKLIST:
            assert model in config.effective_model_blocklist

    def test_effective_model_blocklist_includes_custom(self):
        config = SafetyConfig(model_blocklist=["custom.model"])
        assert "custom.model" in config.effective_model_blocklist
        assert "ir.cron" in config.effective_model_blocklist

    def test_effective_field_blocklist_includes_defaults(self):
        config = SafetyConfig()
        for field in DEFAULT_FIELD_BLOCKLIST:
            assert field in config.effective_field_blocklist

    def test_effective_method_blocklist_includes_defaults(self):
        config = SafetyConfig()
        for method in DEFAULT_METHOD_BLOCKLIST:
            assert method in config.effective_method_blocklist
