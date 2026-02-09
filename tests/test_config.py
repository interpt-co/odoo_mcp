"""Tests for configuration management (Task 1.2)."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from odoo_mcp.config import OdooMcpConfig, load_config


class TestOdooMcpConfig:
    """Test OdooMcpConfig validation and defaults."""

    def test_defaults(self):
        """Default config should be valid (no URL required for empty config)."""
        config = OdooMcpConfig()
        assert config.transport == "stdio"
        assert config.mode == "readonly"
        assert config.odoo_timeout == 30
        assert config.port == 8080
        assert config.log_level == "info"
        assert config.health_check_interval == 300
        assert config.search_default_limit == 80

    def test_minimal_valid(self):
        config = OdooMcpConfig(
            odoo_url="https://test.odoo.com",
            odoo_db="mydb",
            odoo_username="admin",
            odoo_password="secret",
        )
        assert config.odoo_url == "https://test.odoo.com"
        assert config.odoo_db == "mydb"

    def test_url_trailing_slash_stripped(self):
        config = OdooMcpConfig(
            odoo_url="https://test.odoo.com/",
            odoo_db="mydb",
            odoo_username="admin",
            odoo_password="secret",
        )
        assert config.odoo_url == "https://test.odoo.com"

    def test_invalid_url_scheme(self):
        with pytest.raises(ValueError, match="http:// or https://"):
            OdooMcpConfig(
                odoo_url="ftp://bad.com",
                odoo_db="mydb",
                odoo_username="admin",
                odoo_password="secret",
            )

    def test_no_auth_method(self):
        with pytest.raises(ValueError, match="At least one auth method"):
            OdooMcpConfig(
                odoo_url="https://test.odoo.com",
                odoo_db="mydb",
            )

    def test_api_key_auth_only(self):
        config = OdooMcpConfig(
            odoo_url="https://test.odoo.com",
            odoo_db="mydb",
            odoo_api_key="my-api-key",
        )
        assert config.odoo_api_key == "my-api-key"

    def test_allowlist_blocklist_mutual_exclusion(self):
        with pytest.raises(ValueError, match="mutually exclusive"):
            OdooMcpConfig(
                odoo_url="https://test.odoo.com",
                odoo_db="mydb",
                odoo_api_key="key",
                model_allowlist=["res.partner"],
                model_blocklist=["ir.cron"],
            )

    def test_write_allowlist_must_be_subset_of_model_allowlist(self):
        with pytest.raises(ValueError, match="not in model_allowlist"):
            OdooMcpConfig(
                odoo_url="https://test.odoo.com",
                odoo_db="mydb",
                odoo_api_key="key",
                model_allowlist=["res.partner"],
                write_allowlist=["sale.order"],
            )

    def test_write_allowlist_valid_subset(self):
        config = OdooMcpConfig(
            odoo_url="https://test.odoo.com",
            odoo_db="mydb",
            odoo_api_key="key",
            model_allowlist=["res.partner", "sale.order"],
            write_allowlist=["sale.order"],
        )
        assert config.write_allowlist == ["sale.order"]

    def test_invalid_port(self):
        with pytest.raises(ValueError, match="port must be 1-65535"):
            OdooMcpConfig(
                odoo_url="https://test.odoo.com",
                odoo_db="mydb",
                odoo_api_key="key",
                port=0,
            )

    def test_rate_limit_rpm_zero(self):
        with pytest.raises(ValueError, match="rate_limit_rpm must be > 0"):
            OdooMcpConfig(
                odoo_url="https://test.odoo.com",
                odoo_db="mydb",
                odoo_api_key="key",
                rate_limit_enabled=True,
                rate_limit_rpm=0,
            )

    def test_comma_separated_list_parsing(self):
        config = OdooMcpConfig(
            odoo_url="https://test.odoo.com",
            odoo_db="mydb",
            odoo_api_key="key",
            model_allowlist="res.partner,sale.order, product.product",
        )
        assert config.model_allowlist == [
            "res.partner",
            "sale.order",
            "product.product",
        ]

    def test_comma_separated_int_list_parsing(self):
        config = OdooMcpConfig(
            odoo_url="https://test.odoo.com",
            odoo_db="mydb",
            odoo_api_key="key",
            odoo_company_ids="1,2,3",
        )
        assert config.odoo_company_ids == [1, 2, 3]

    def test_empty_comma_list(self):
        config = OdooMcpConfig(
            odoo_url="https://test.odoo.com",
            odoo_db="mydb",
            odoo_api_key="key",
            model_allowlist="",
        )
        assert config.model_allowlist == []


class TestLoadConfig:
    """Test load_config with file and CLI overrides."""

    def test_load_from_json_file(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "odoo_url": "https://file.odoo.com",
            "odoo_db": "filedb",
            "odoo_api_key": "file-key",
            "mode": "full",
        }))

        config = load_config({"_config_path": str(config_file)})
        assert config.odoo_url == "https://file.odoo.com"
        assert config.mode == "full"

    def test_cli_overrides_file(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "odoo_url": "https://file.odoo.com",
            "odoo_db": "filedb",
            "odoo_api_key": "file-key",
            "mode": "readonly",
        }))

        config = load_config({
            "_config_path": str(config_file),
            "mode": "full",
        })
        assert config.mode == "full"

    def test_missing_config_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_config({"_config_path": "/nonexistent/config.json"})

    def test_cli_overrides_only(self):
        config = load_config({
            "odoo_url": "https://cli.odoo.com",
            "odoo_db": "clidb",
            "odoo_api_key": "cli-key",
        })
        assert config.odoo_url == "https://cli.odoo.com"
