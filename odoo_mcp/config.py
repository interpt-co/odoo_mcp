"""Configuration management using Pydantic Settings.

Priority: CLI args > env vars > config file > defaults (REQ-01-29).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


def _parse_comma_list(v: Any) -> list[str]:
    """Parse comma-separated string into list of strings."""
    if isinstance(v, str):
        return [item.strip() for item in v.split(",") if item.strip()]
    if isinstance(v, list):
        return v
    return []


def _parse_comma_int_list(v: Any) -> list[int]:
    """Parse comma-separated string into list of ints."""
    if isinstance(v, str):
        return [int(item.strip()) for item in v.split(",") if item.strip()]
    if isinstance(v, list):
        return [int(i) for i in v]
    return []


class OdooMcpConfig(BaseSettings):
    """Complete server configuration (REQ-11-25)."""

    # === Connection ===
    odoo_url: str = ""
    odoo_db: str = ""
    odoo_username: str | None = None
    odoo_password: str | None = None
    odoo_api_key: str | None = None
    odoo_protocol: Literal["auto", "xmlrpc", "jsonrpc", "json2"] = "auto"
    odoo_timeout: int = 30
    odoo_verify_ssl: bool = True
    odoo_ca_cert: str | None = None

    # === Transport ===
    transport: Literal["stdio", "sse", "http"] = "stdio"
    host: str = "127.0.0.1"
    port: int = 8080
    mcp_path: str = "/mcp"

    # === Safety ===
    mode: Literal["readonly", "restricted", "full"] = "readonly"
    model_allowlist: list[str] = []
    model_blocklist: list[str] = []
    write_allowlist: list[str] = []
    field_blocklist: list[str] = []
    method_blocklist: list[str] = []

    # === Toolsets ===
    enabled_toolsets: list[str] = []
    disabled_toolsets: list[str] = []

    # === Registry ===
    static_registry_path: str | None = None
    introspect_on_startup: bool = True
    introspect_models: list[str] = []

    # === Rate Limiting ===
    rate_limit_enabled: bool = False
    rate_limit_rpm: int = 60
    rate_limit_rph: int = 1000
    rate_limit_burst: int = 10

    # === Audit ===
    audit_enabled: bool = False
    audit_log_file: str | None = None
    audit_log_reads: bool = False
    audit_log_writes: bool = True
    audit_log_deletes: bool = True

    # === Context ===
    odoo_lang: str = "en_US"
    odoo_tz: str = "UTC"
    odoo_company_id: int | None = None
    odoo_company_ids: list[int] = []

    # === Search ===
    search_default_limit: int = 80
    search_max_limit: int = 500
    deep_search_max_depth: int = 3

    # === Display ===
    strip_html: bool = True
    normalize_many2one: bool = True

    # === Logging ===
    log_level: str = "info"

    # === Health ===
    health_check_interval: int = 300
    reconnect_max_attempts: int = 3
    reconnect_backoff_base: int = 1

    model_config = {
        "env_prefix": "",
        "case_sensitive": False,
        "extra": "ignore",
    }

    # --- Validators for comma-separated list env vars (REQ-11-30) ---

    @field_validator(
        "model_allowlist",
        "model_blocklist",
        "write_allowlist",
        "field_blocklist",
        "method_blocklist",
        "enabled_toolsets",
        "disabled_toolsets",
        "introspect_models",
        mode="before",
    )
    @classmethod
    def parse_comma_list(cls, v: Any) -> list[str]:
        return _parse_comma_list(v)

    @field_validator("odoo_company_ids", mode="before")
    @classmethod
    def parse_comma_int_list(cls, v: Any) -> list[int]:
        return _parse_comma_int_list(v)

    # --- Startup validation (REQ-11-28, REQ-11-29) ---

    @model_validator(mode="after")
    def validate_startup(self) -> "OdooMcpConfig":
        errors: list[str] = []

        # 1. URL is valid
        if self.odoo_url:
            url = self.odoo_url.rstrip("/")
            self.odoo_url = url
            if not url.startswith(("http://", "https://")):
                errors.append(
                    f"odoo_url must start with http:// or https://, got: {url}"
                )

        # 2. Database is non-empty (only enforce if URL is set — allows partial config)
        # We check at connect time, not at config load time, for flexibility.

        # 3. At least one auth method provided (only enforce if URL is set)
        if self.odoo_url and self.odoo_db:
            has_password_auth = self.odoo_username and self.odoo_password
            has_api_key_auth = self.odoo_api_key is not None
            if not has_password_auth and not has_api_key_auth:
                errors.append(
                    "At least one auth method required: "
                    "set odoo_username+odoo_password or odoo_api_key"
                )

        # 5. Allowlist and blocklist not both set
        if self.model_allowlist and self.model_blocklist:
            errors.append(
                "model_allowlist and model_blocklist are mutually exclusive; "
                "set one or the other, not both"
            )

        # 6. Write allowlist subset of model allowlist
        if self.write_allowlist and self.model_allowlist:
            extra = set(self.write_allowlist) - set(self.model_allowlist)
            if extra:
                errors.append(
                    f"write_allowlist contains models not in model_allowlist: {extra}"
                )

        # 7. Port in valid range
        if not 1 <= self.port <= 65535:
            errors.append(f"port must be 1-65535, got: {self.port}")

        # 8. Rate limit RPM > 0 if enabled
        if self.rate_limit_enabled and self.rate_limit_rpm <= 0:
            errors.append("rate_limit_rpm must be > 0 when rate limiting is enabled")

        if errors:
            raise ValueError(
                "Configuration validation failed:\n  - " + "\n  - ".join(errors)
            )

        return self


def load_config(
    cli_overrides: dict[str, Any] | None = None,
) -> OdooMcpConfig:
    """Load configuration with priority: CLI > env > config file > defaults.

    REQ-01-29, REQ-11-26, REQ-11-27.
    """
    cli = cli_overrides or {}

    # Determine config file path
    config_path = cli.pop("_config_path", None) or os.environ.get("ODOO_MCP_CONFIG")

    file_values: dict[str, Any] = {}
    if config_path:
        path = Path(config_path)
        if path.exists():
            with open(path) as f:
                file_values = json.load(f)
        else:
            raise FileNotFoundError(f"Config file not found: {config_path}")

    # Merge: file values are the base, CLI overrides on top.
    # Pydantic-settings will also read env vars automatically with higher priority
    # than init values, but CLI overrides must win over everything.
    # Strategy: pass file values as init kwargs, then overlay CLI.
    merged = {**file_values, **cli}

    return OdooMcpConfig(**merged)
