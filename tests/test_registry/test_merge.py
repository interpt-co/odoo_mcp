"""Tests for registry merge strategy (Task 3.5)."""

from __future__ import annotations

import pytest

from odoo_mcp.registry.model_registry import (
    FieldInfo,
    MethodInfo,
    ModelInfo,
    Registry,
    ModelRegistry,
)


def _make_static_registry() -> Registry:
    return Registry(
        version="17.0",
        build_mode="static",
        models={
            "sale.order": ModelInfo(
                model="sale.order",
                name="Sales Order",
                fields={
                    "name": FieldInfo(name="name", label="Order Ref", type="char", required=True),
                    "state": FieldInfo(
                        name="state", label="Status", type="selection",
                        selection=[("draft", "Draft"), ("sale", "SO")],
                    ),
                },
                methods={
                    "action_confirm": MethodInfo(
                        name="action_confirm",
                        description="Confirm the quotation into a sales order",
                        accepts_kwargs=False,
                        decorator="api.multi",
                    ),
                },
                states=[("draft", "Draft"), ("sale", "SO")],
                parent_models=["mail.thread"],
                has_chatter=True,
            ),
        },
    )


def _make_dynamic_registry() -> Registry:
    return Registry(
        version="17.0",
        build_mode="dynamic",
        models={
            "sale.order": ModelInfo(
                model="sale.order",
                name="Sales Order",
                fields={
                    "name": FieldInfo(name="name", label="Order Reference", type="char", required=True),
                    "new_field": FieldInfo(name="new_field", label="New Field", type="char"),
                    "state": FieldInfo(
                        name="state", label="Status", type="selection",
                        selection=[("draft", "Quotation"), ("sent", "Sent"), ("sale", "Sales Order"), ("cancel", "Cancelled")],
                    ),
                },
                methods={
                    "action_confirm": MethodInfo(name="action_confirm", description="Confirm", accepts_kwargs=False),
                    "action_new": MethodInfo(name="action_new", description="New method from dynamic"),
                },
                states=[("draft", "Quotation"), ("sent", "Sent"), ("sale", "Sales Order"), ("cancel", "Cancelled")],
                parent_models=["mail.thread", "mail.activity.mixin"],
                has_chatter=True,
            ),
            "res.partner": ModelInfo(
                model="res.partner",
                name="Contact",
                fields={
                    "name": FieldInfo(name="name", label="Name", type="char", required=True),
                },
            ),
        },
    )


class TestRegistryMerge:
    def test_merge_dynamic_fields_win(self):
        """Dynamic fields override static fields."""
        reg = ModelRegistry()
        static = _make_static_registry()
        dynamic = _make_dynamic_registry()
        merged = reg.merge(static, dynamic)

        # Dynamic label overrides static
        assert merged.models["sale.order"].fields["name"].label == "Order Reference"

    def test_merge_new_field_from_dynamic(self):
        """New fields from dynamic are added."""
        reg = ModelRegistry()
        merged = reg.merge(_make_static_registry(), _make_dynamic_registry())
        assert "new_field" in merged.models["sale.order"].fields

    def test_merge_static_methods_preserved(self):
        """Static methods are preserved (richer AST data)."""
        reg = ModelRegistry()
        merged = reg.merge(_make_static_registry(), _make_dynamic_registry())
        m = merged.models["sale.order"].methods["action_confirm"]
        # Static has richer description and decorator
        assert m.description == "Confirm the quotation into a sales order"
        assert m.decorator == "api.multi"

    def test_merge_new_method_from_dynamic(self):
        """New methods from dynamic are added."""
        reg = ModelRegistry()
        merged = reg.merge(_make_static_registry(), _make_dynamic_registry())
        assert "action_new" in merged.models["sale.order"].methods

    def test_merge_dynamic_states_win(self):
        """Dynamic states override static states."""
        reg = ModelRegistry()
        merged = reg.merge(_make_static_registry(), _make_dynamic_registry())
        states = merged.models["sale.order"].states
        assert len(states) == 4
        assert ("sent", "Sent") in states

    def test_merge_new_model_from_dynamic(self):
        """Models only in dynamic are added to merged."""
        reg = ModelRegistry()
        merged = reg.merge(_make_static_registry(), _make_dynamic_registry())
        assert "res.partner" in merged.models

    def test_merge_build_mode(self):
        """Merged registry has build_mode='merged'."""
        reg = ModelRegistry()
        merged = reg.merge(_make_static_registry(), _make_dynamic_registry())
        assert merged.build_mode == "merged"

    def test_merge_updates_counts(self):
        """Counts are updated after merge."""
        reg = ModelRegistry()
        merged = reg.merge(_make_static_registry(), _make_dynamic_registry())
        assert merged.model_count == 2
        assert merged.field_count > 0

    def test_merge_parent_models_combined(self):
        """Parent models from both sources are combined."""
        reg = ModelRegistry()
        merged = reg.merge(_make_static_registry(), _make_dynamic_registry())
        parents = merged.models["sale.order"].parent_models
        assert "mail.thread" in parents
        assert "mail.activity.mixin" in parents

    def test_merge_chatter_propagated(self):
        """has_chatter is True if either source has it."""
        reg = ModelRegistry()
        merged = reg.merge(_make_static_registry(), _make_dynamic_registry())
        assert merged.models["sale.order"].has_chatter is True

    def test_merge_empty_static(self):
        """Merging empty static with dynamic just copies dynamic."""
        reg = ModelRegistry()
        empty = Registry(version="17.0", build_mode="static")
        dynamic = _make_dynamic_registry()
        merged = reg.merge(empty, dynamic)
        assert "sale.order" in merged.models
        assert "res.partner" in merged.models

    def test_merge_empty_dynamic(self):
        """Merging static with empty dynamic preserves static."""
        reg = ModelRegistry()
        static = _make_static_registry()
        empty = Registry(version="17.0", build_mode="dynamic")
        merged = reg.merge(static, empty)
        assert "sale.order" in merged.models
        assert merged.models["sale.order"].fields["name"].label == "Order Ref"
