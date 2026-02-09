"""Tests for the odoo:// URI scheme parser (Task 3.6)."""

from __future__ import annotations

import pytest

from odoo_mcp.resources.uri import (
    OdooUri,
    OdooUriError,
    parse_odoo_uri,
    MAX_LIMIT,
    DEFAULT_LIMIT,
)


class TestParseBasicUris:
    def test_system_info(self):
        uri = parse_odoo_uri("odoo://system/info")
        assert uri.category == "system"
        assert uri.resource_type == "info"
        assert uri.path_segments == ["info"]

    def test_system_modules(self):
        uri = parse_odoo_uri("odoo://system/modules")
        assert uri.category == "system"
        assert uri.resource_type == "modules"

    def test_system_toolsets(self):
        uri = parse_odoo_uri("odoo://system/toolsets")
        assert uri.category == "system"
        assert uri.resource_type == "toolsets"

    def test_config_safety(self):
        uri = parse_odoo_uri("odoo://config/safety")
        assert uri.category == "config"
        assert uri.resource_type == "safety"


class TestModelUris:
    def test_model_fields(self):
        uri = parse_odoo_uri("odoo://model/sale.order/fields")
        assert uri.category == "model"
        assert uri.model_name == "sale.order"
        assert uri.resource_type == "fields"

    def test_model_methods(self):
        uri = parse_odoo_uri("odoo://model/sale.order/methods")
        assert uri.model_name == "sale.order"
        assert uri.resource_type == "methods"

    def test_model_states(self):
        uri = parse_odoo_uri("odoo://model/account.move/states")
        assert uri.model_name == "account.move"
        assert uri.resource_type == "states"


class TestRecordUris:
    def test_single_record(self):
        uri = parse_odoo_uri("odoo://record/sale.order/42")
        assert uri.category == "record"
        assert uri.model_name == "sale.order"
        assert uri.record_id == 42

    def test_record_listing_with_domain(self):
        uri = parse_odoo_uri('odoo://record/sale.order?domain=[["state","=","draft"]]&limit=10')
        assert uri.model_name == "sale.order"
        assert uri.domain == [["state", "=", "draft"]]
        assert uri.limit == 10

    def test_record_listing_default_limit(self):
        uri = parse_odoo_uri("odoo://record/sale.order")
        assert uri.limit == DEFAULT_LIMIT

    def test_record_listing_max_limit(self):
        uri = parse_odoo_uri("odoo://record/sale.order?limit=500")
        assert uri.limit == MAX_LIMIT

    def test_record_listing_min_limit(self):
        uri = parse_odoo_uri("odoo://record/sale.order?limit=0")
        assert uri.limit == 1


class TestInvalidUris:
    def test_wrong_scheme(self):
        with pytest.raises(OdooUriError, match="must start with 'odoo://'"):
            parse_odoo_uri("http://example.com")

    def test_empty_path(self):
        with pytest.raises(OdooUriError, match="no category"):
            parse_odoo_uri("odoo://")

    def test_invalid_category(self):
        with pytest.raises(OdooUriError, match="Invalid category"):
            parse_odoo_uri("odoo://invalid/path")

    def test_system_no_type(self):
        with pytest.raises(OdooUriError, match="resource type"):
            parse_odoo_uri("odoo://system")

    def test_config_no_type(self):
        with pytest.raises(OdooUriError, match="resource type"):
            parse_odoo_uri("odoo://config")

    def test_model_no_resource_type(self):
        with pytest.raises(OdooUriError, match="model_name and resource type"):
            parse_odoo_uri("odoo://model/sale.order")

    def test_record_no_model(self):
        with pytest.raises(OdooUriError, match="model name"):
            parse_odoo_uri("odoo://record")

    def test_invalid_domain_json(self):
        with pytest.raises(OdooUriError, match="Invalid JSON"):
            parse_odoo_uri("odoo://record/sale.order?domain=not_json")

    def test_invalid_limit(self):
        with pytest.raises(OdooUriError, match="Invalid limit"):
            parse_odoo_uri("odoo://record/sale.order?limit=abc")


class TestOdooUriProperties:
    def test_model_name_for_model(self):
        uri = parse_odoo_uri("odoo://model/res.partner/fields")
        assert uri.model_name == "res.partner"

    def test_model_name_for_record(self):
        uri = parse_odoo_uri("odoo://record/res.partner/5")
        assert uri.model_name == "res.partner"

    def test_model_name_for_system(self):
        uri = parse_odoo_uri("odoo://system/info")
        assert uri.model_name is None

    def test_record_id_present(self):
        uri = parse_odoo_uri("odoo://record/sale.order/123")
        assert uri.record_id == 123

    def test_record_id_absent(self):
        uri = parse_odoo_uri("odoo://record/sale.order")
        assert uri.record_id is None

    def test_raw_preserved(self):
        raw = "odoo://system/info"
        uri = parse_odoo_uri(raw)
        assert uri.raw == raw
