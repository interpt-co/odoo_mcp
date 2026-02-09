"""Tests for odoo_mcp.toolsets.base — BaseToolset, ToolsetMetadata, naming, annotations."""

import pytest

from odoo_mcp.toolsets.base import (
    ANNOTATIONS_DESTRUCTIVE,
    ANNOTATIONS_READ_ONLY,
    ANNOTATIONS_WRITE,
    ANNOTATIONS_WRITE_IDEMPOTENT,
    BaseToolset,
    ToolsetMetadata,
    make_annotations,
    tool_name,
)


# ---------------------------------------------------------------------------
# ToolsetMetadata
# ---------------------------------------------------------------------------

class TestToolsetMetadata:
    def test_required_fields(self):
        meta = ToolsetMetadata(name="test", description="A test", version="1.0.0")
        assert meta.name == "test"
        assert meta.description == "A test"
        assert meta.version == "1.0.0"

    def test_default_optional_fields(self):
        meta = ToolsetMetadata(name="t", description="d", version="0.1.0")
        assert meta.required_modules == []
        assert meta.min_odoo_version is None
        assert meta.max_odoo_version is None
        assert meta.depends_on == []
        assert meta.tags == []

    def test_full_metadata(self):
        meta = ToolsetMetadata(
            name="sales",
            description="Sales tools",
            version="2.0.0",
            required_modules=["sale"],
            min_odoo_version=14,
            max_odoo_version=18,
            depends_on=["core"],
            tags=["workflow"],
        )
        assert meta.required_modules == ["sale"]
        assert meta.min_odoo_version == 14
        assert meta.max_odoo_version == 18
        assert meta.depends_on == ["core"]
        assert meta.tags == ["workflow"]


# ---------------------------------------------------------------------------
# BaseToolset is abstract
# ---------------------------------------------------------------------------

class TestBaseToolset:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            BaseToolset()

    def test_subclass_must_implement(self):
        class Incomplete(BaseToolset):
            def metadata(self):
                return ToolsetMetadata(name="x", description="x", version="0")

        with pytest.raises(TypeError):
            Incomplete()

    def test_valid_subclass(self):
        class Valid(BaseToolset):
            def metadata(self):
                return ToolsetMetadata(name="x", description="x", version="0")

            async def register_tools(self, server, connection, **kwargs):
                return []

        instance = Valid()
        assert instance.metadata().name == "x"


# ---------------------------------------------------------------------------
# Tool naming convention
# ---------------------------------------------------------------------------

class TestToolName:
    def test_basic(self):
        assert tool_name("core", "search_read") == "odoo_core_search_read"

    def test_sales(self):
        assert tool_name("sales", "create_order") == "odoo_sales_create_order"

    def test_accounting(self):
        assert tool_name("accounting", "post_invoice") == "odoo_accounting_post_invoice"


# ---------------------------------------------------------------------------
# Annotations helper
# ---------------------------------------------------------------------------

class TestAnnotations:
    def test_make_annotations_readonly(self):
        ann = make_annotations(title="Search", **ANNOTATIONS_READ_ONLY)
        assert ann["title"] == "Search"
        assert ann["readOnlyHint"] is True
        assert ann["destructiveHint"] is False
        assert ann["idempotentHint"] is True
        assert ann["openWorldHint"] is True

    def test_make_annotations_write(self):
        ann = make_annotations(title="Create", **ANNOTATIONS_WRITE)
        assert ann["readOnlyHint"] is False
        assert ann["destructiveHint"] is False
        assert ann["idempotentHint"] is False
        assert ann["openWorldHint"] is True

    def test_make_annotations_destructive(self):
        ann = make_annotations(title="Delete", **ANNOTATIONS_DESTRUCTIVE)
        assert ann["destructiveHint"] is True

    def test_make_annotations_write_idempotent(self):
        ann = make_annotations(title="Update", **ANNOTATIONS_WRITE_IDEMPOTENT)
        assert ann["readOnlyHint"] is False
        assert ann["idempotentHint"] is True
