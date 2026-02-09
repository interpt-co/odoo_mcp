# 11 — Safety & Configuration

| Field        | Value                              |
|-------------|-------------------------------------|
| Document ID | SPEC-11                             |
| Title       | Safety & Configuration               |
| Status      | Draft                               |
| Depends On  | SPEC-01, SPEC-03                    |
| Referenced By | SPEC-04, SPEC-05                  |

---

## 1. Overview

This document specifies all safety mechanisms and the complete configuration reference for the Odoo MCP server. Safety is enforced at multiple layers: operation modes, tool annotations, model/field filtering, rate limiting, and audit logging.

---

## 2. Operation Modes

**REQ-11-01**: The server MUST support three operation modes:

| Mode | Value | Description |
|------|-------|-------------|
| Read-Only | `readonly` | Only read operations allowed. No creates, writes, deletes, or state changes. |
| Restricted | `restricted` | Reads allowed on all permitted models. Writes/creates limited to models in the write allowlist. Deletes not allowed. |
| Full | `full` | All operations allowed on permitted models. Requires explicit opt-in. |

**REQ-11-02**: The operation mode MUST be set via configuration (default: `readonly`):
- Environment variable: `ODOO_MCP_MODE=readonly|restricted|full`
- Config file: `"mode": "readonly"`

**REQ-11-03**: Mode enforcement MUST happen at the tool execution layer, before any Odoo API call:

```python
async def enforce_mode(mode: str, operation: str, model: str, config: SafetyConfig):
    """
    operation: "read", "search", "create", "write", "unlink", "execute"
    Raises ModeViolationError if not allowed.
    """
    if mode == "readonly" and operation not in ("read", "search"):
        raise ModeViolationError(f"'{operation}' not allowed in readonly mode")

    if mode == "restricted":
        if operation in ("create", "write", "execute"):
            if model not in config.write_allowlist:
                raise ModeViolationError(
                    f"'{operation}' on '{model}' not allowed in restricted mode. "
                    f"Allowed models: {config.write_allowlist}"
                )
        if operation == "unlink":
            raise ModeViolationError("Delete not allowed in restricted mode")

    # "full" mode: all operations allowed (subject to model filtering)
```

### 2.1 Mode-Specific Tool Behavior

**REQ-11-04**: Tool registration MUST respect the operation mode:

| Tool | readonly | restricted | full |
|------|----------|-----------|------|
| `odoo_core_search_read` | Available | Available | Available |
| `odoo_core_read` | Available | Available | Available |
| `odoo_core_count` | Available | Available | Available |
| `odoo_core_fields_get` | Available | Available | Available |
| `odoo_core_name_get` | Available | Available | Available |
| `odoo_core_default_get` | Available | Available | Available |
| `odoo_core_deep_search` | Available | Available | Available |
| `odoo_core_create` | Hidden | Available (filtered) | Available |
| `odoo_core_write` | Hidden | Available (filtered) | Available |
| `odoo_core_unlink` | Hidden | Hidden | Available |
| `odoo_core_execute` | Available (read methods only) | Available (write methods filtered) | Available |
| Workflow tools (create/confirm) | Hidden | Available (filtered) | Available |
| `odoo_chatter_post_message` | Hidden | Available | Available |
| `odoo_attachments_upload` | Hidden | Available | Available |
| `odoo_attachments_delete` | Hidden | Hidden | Available |

**REQ-11-05**: "Hidden" means the tool is NOT registered with the MCP server in that mode. The LLM will not see it in the tool list.

---

## 3. Model Filtering

### 3.1 Model Allowlist

**REQ-11-06**: If `model_allowlist` is configured (non-empty list), ONLY models in the list are accessible. All other models are blocked.

```json
{
  "model_allowlist": ["res.partner", "sale.order", "sale.order.line", "product.product"]
}
```

### 3.2 Model Blocklist

**REQ-11-07**: If `model_blocklist` is configured, models in the list are NEVER accessible, regardless of other settings.

```json
{
  "model_blocklist": ["ir.cron", "ir.config_parameter", "base.automation"]
}
```

**REQ-11-08**: Default blocklist (always applied in addition to user configuration):

```python
DEFAULT_MODEL_BLOCKLIST = [
    "ir.config_parameter",      # System parameters (may contain secrets)
    "ir.cron",                  # Scheduled actions (dangerous to modify)
    "base.automation",          # Automated actions
    "ir.rule",                  # Record rules (security)
    "ir.model.access",          # Access rights (security)
    "res.users",                # User records (contains auth data) — read allowed, write blocked
    "ir.mail_server",           # Mail server config (contains credentials)
    "fetchmail.server",         # Incoming mail config (contains credentials)
    "payment.provider",         # Payment provider config (contains credentials)
]
```

**REQ-11-09**: The `res.users` model is a special case: read access is allowed (for user lookups), but write access is always blocked unless explicitly overridden in configuration.

### 3.3 Write Allowlist (Restricted Mode)

**REQ-11-10**: In `restricted` mode, the `write_allowlist` specifies which models can be created/written:

```json
{
  "write_allowlist": [
    "sale.order", "sale.order.line",
    "crm.lead",
    "helpdesk.ticket",
    "project.task",
    "mail.message", "mail.activity",
    "ir.attachment"
  ]
}
```

**REQ-11-11**: If `write_allowlist` is empty in `restricted` mode, NO write operations are allowed (effectively same as `readonly` for writes).

---

## 4. Field Filtering

### 4.1 Field Blocklist

**REQ-11-12**: Specific fields can be blocked from read and write operations:

```json
{
  "field_blocklist": ["password", "password_crypt", "oauth_access_token", "api_key"]
}
```

**REQ-11-13**: Default field blocklist (always applied):

```python
DEFAULT_FIELD_BLOCKLIST = [
    "password",
    "password_crypt",
    "oauth_access_token",
    "oauth_provider_id",
    "api_key",
    "api_key_ids",
    "totp_secret",
    "totp_enabled",
    "signature",                    # User signature (can contain sensitive info)
]
```

**REQ-11-14**: Blocked fields MUST be:
1. Removed from `fields_get` responses.
2. Removed from `search_read` and `read` results.
3. Rejected in `create` and `write` values with a clear error.

---

## 5. Method Filtering

### 5.1 Method Blocklist

**REQ-11-15**: Specific methods can be blocked from execution:

```json
{
  "method_blocklist": ["unlink_all", "sudo", "with_user"]
}
```

**REQ-11-16**: Default method blocklist:

```python
DEFAULT_METHOD_BLOCKLIST = [
    "sudo",
    "with_user",
    "with_env",
    "with_context",     # Prevent context manipulation via execute
    "invalidate_cache",
    "clear_caches",
    "init",
    "uninstall",
    "module_uninstall",
]
```

---

## 6. Tool Annotations (MCP Spec)

**REQ-11-17**: Every tool MUST include MCP tool annotations as defined in the MCP 2025-11-25 spec:

```python
class ToolAnnotations(TypedDict, total=False):
    title: str                  # Human-readable display name
    readOnlyHint: bool          # True if tool only reads (default: False)
    destructiveHint: bool       # True if tool may destroy data (default: True)
    idempotentHint: bool        # True if repeated calls produce same result (default: False)
    openWorldHint: bool         # True if tool interacts with external systems (default: True)
```

**REQ-11-18**: Annotation values for each tool:

| Tool | readOnly | destructive | idempotent | openWorld |
|------|----------|-------------|------------|-----------|
| `search_read` | true | false | true | true |
| `read` | true | false | true | true |
| `count` | true | false | true | true |
| `fields_get` | true | false | true | true |
| `name_get` | true | false | true | true |
| `default_get` | true | false | true | true |
| `deep_search` | true | false | true | true |
| `list_models` | true | false | true | true |
| `list_toolsets` | true | false | true | true |
| `create` | false | false | false | true |
| `write` | false | false | true | true |
| `unlink` | false | true | true | true |
| `execute` | false | false | false | true |
| Workflow creates | false | false | false | true |
| Workflow confirms | false | false | true | true |
| Workflow cancels | false | false | true | true |
| `post_message` | false | false | false | true |
| `upload_attachment` | false | false | false | true |
| `delete_attachment` | false | true | true | true |
| `generate_report` | true | false | true | true |

---

## 7. Rate Limiting

**REQ-11-19**: The server MUST support configurable rate limiting:

```json
{
  "rate_limit": {
    "enabled": true,
    "calls_per_minute": 60,
    "calls_per_hour": 1000,
    "burst": 10
  }
}
```

**REQ-11-20**: Rate limiting MUST be per-client (per MCP session). When the rate limit is exceeded, the tool MUST return a `RATE_LIMITED` error with a `retry_after` field (seconds).

**REQ-11-21**: Read-only operations MAY have a separate (higher) rate limit:

```json
{
  "rate_limit": {
    "read_calls_per_minute": 120,
    "write_calls_per_minute": 30
  }
}
```

---

## 8. Audit Logging

**REQ-11-22**: When audit logging is enabled, the server MUST log every tool invocation:

```json
{
  "audit": {
    "enabled": true,
    "log_file": "/var/log/odoo-mcp/audit.jsonl",
    "log_reads": false,
    "log_writes": true,
    "log_deletes": true
  }
}
```

**REQ-11-23**: Each audit log entry MUST be a JSON line:

```json
{
  "timestamp": "2025-02-09T14:30:00Z",
  "session_id": "abc123",
  "tool": "odoo_core_create",
  "model": "sale.order",
  "operation": "create",
  "values": {"partner_id": 1, "note": "Test order"},
  "result_id": 42,
  "success": true,
  "duration_ms": 150,
  "odoo_uid": 2
}
```

**REQ-11-24**: Audit logs MUST NOT contain:
- Passwords or API keys.
- Binary field content (log field names only).
- Full record data for read operations (log the domain/IDs only).

---

## 9. Complete Configuration Reference

**REQ-11-25**: The full configuration schema:

```python
class OdooMcpConfig(BaseSettings):
    """Complete server configuration."""

    # === Connection ===
    odoo_url: str                               # ODOO_URL
    odoo_db: str                                # ODOO_DB
    odoo_username: str | None = None            # ODOO_USERNAME
    odoo_password: str | None = None            # ODOO_PASSWORD
    odoo_api_key: str | None = None             # ODOO_API_KEY
    odoo_protocol: Literal["auto", "xmlrpc", "jsonrpc", "json2"] = "auto"  # ODOO_PROTOCOL
    odoo_timeout: int = 30                      # ODOO_TIMEOUT (seconds)
    odoo_verify_ssl: bool = True                # ODOO_VERIFY_SSL
    odoo_ca_cert: str | None = None             # ODOO_CA_CERT (path to PEM file)

    # === Transport ===
    transport: Literal["stdio", "sse", "http"] = "stdio"  # ODOO_MCP_TRANSPORT
    host: str = "127.0.0.1"                     # ODOO_MCP_HOST
    port: int = 8080                            # ODOO_MCP_PORT
    mcp_path: str = "/mcp"                      # ODOO_MCP_PATH (streamable HTTP)

    # === Safety ===
    mode: Literal["readonly", "restricted", "full"] = "readonly"  # ODOO_MCP_MODE
    model_allowlist: list[str] = []             # ODOO_MCP_MODEL_ALLOWLIST (comma-separated)
    model_blocklist: list[str] = []             # ODOO_MCP_MODEL_BLOCKLIST (comma-separated)
    write_allowlist: list[str] = []             # ODOO_MCP_WRITE_ALLOWLIST (comma-separated)
    field_blocklist: list[str] = []             # ODOO_MCP_FIELD_BLOCKLIST (comma-separated)
    method_blocklist: list[str] = []            # ODOO_MCP_METHOD_BLOCKLIST (comma-separated)

    # === Toolsets ===
    enabled_toolsets: list[str] = []            # ODOO_MCP_ENABLED_TOOLSETS (empty = all)
    disabled_toolsets: list[str] = []           # ODOO_MCP_DISABLED_TOOLSETS

    # === Registry ===
    static_registry_path: str | None = None     # ODOO_MCP_STATIC_REGISTRY (path to JSON)
    introspect_on_startup: bool = True          # ODOO_MCP_INTROSPECT
    introspect_models: list[str] = []           # ODOO_MCP_INTROSPECT_MODELS (empty = defaults)

    # === Rate Limiting ===
    rate_limit_enabled: bool = False            # ODOO_MCP_RATE_LIMIT
    rate_limit_rpm: int = 60                    # ODOO_MCP_RATE_LIMIT_RPM
    rate_limit_rph: int = 1000                  # ODOO_MCP_RATE_LIMIT_RPH
    rate_limit_burst: int = 10                  # ODOO_MCP_RATE_LIMIT_BURST

    # === Audit ===
    audit_enabled: bool = False                 # ODOO_MCP_AUDIT
    audit_log_file: str | None = None           # ODOO_MCP_AUDIT_FILE
    audit_log_reads: bool = False               # ODOO_MCP_AUDIT_READS
    audit_log_writes: bool = True               # ODOO_MCP_AUDIT_WRITES
    audit_log_deletes: bool = True              # ODOO_MCP_AUDIT_DELETES

    # === Context ===
    odoo_lang: str = "en_US"                    # ODOO_LANG
    odoo_tz: str = "UTC"                        # ODOO_TZ
    odoo_company_id: int | None = None          # ODOO_COMPANY_ID
    odoo_company_ids: list[int] = []            # ODOO_COMPANY_IDS (comma-separated)

    # === Search ===
    search_default_limit: int = 80              # ODOO_MCP_SEARCH_LIMIT
    search_max_limit: int = 500                 # ODOO_MCP_SEARCH_MAX_LIMIT
    deep_search_max_depth: int = 3              # ODOO_MCP_DEEP_SEARCH_DEPTH

    # === Display ===
    strip_html: bool = True                     # ODOO_MCP_STRIP_HTML
    normalize_many2one: bool = True             # ODOO_MCP_NORMALIZE_M2O

    # === Logging ===
    log_level: str = "info"                     # ODOO_MCP_LOG_LEVEL

    # === Health ===
    health_check_interval: int = 300            # ODOO_MCP_HEALTH_INTERVAL (seconds)
    reconnect_max_attempts: int = 3             # ODOO_MCP_RECONNECT_ATTEMPTS
    reconnect_backoff_base: int = 1             # ODOO_MCP_RECONNECT_BACKOFF (seconds)

    class Config:
        env_prefix = ""                         # No common prefix — each var has its own
        case_sensitive = False
```

---

## 10. Configuration File Format

**REQ-11-26**: The configuration file MUST be JSON:

```json
{
  "odoo_url": "https://mycompany.odoo.com",
  "odoo_db": "mycompany",
  "odoo_username": "admin",
  "odoo_api_key": "...",
  "mode": "restricted",
  "write_allowlist": ["sale.order", "sale.order.line", "crm.lead"],
  "model_blocklist": ["ir.config_parameter"],
  "transport": "stdio",
  "log_level": "info",
  "rate_limit_enabled": true,
  "rate_limit_rpm": 60
}
```

**REQ-11-27**: The configuration file path is specified via:
1. CLI argument: `--config /path/to/config.json`
2. Environment variable: `ODOO_MCP_CONFIG=/path/to/config.json`

---

## 11. Startup Validation

**REQ-11-28**: At startup, the server MUST validate the configuration:

1. `odoo_url` is a valid URL.
2. `odoo_db` is non-empty.
3. At least one authentication method is provided (`username`+`password` or `api_key`).
4. `mode` is a valid value.
5. `model_allowlist` and `model_blocklist` are not both non-empty (they are mutually exclusive).
6. If `write_allowlist` is set, all models in it are also in `model_allowlist` (if allowlist is set).
7. `port` is in valid range (1-65535).
8. `rate_limit_rpm` > 0 if rate limiting is enabled.

**REQ-11-29**: Validation errors MUST be reported at startup with clear messages and the server MUST NOT start.

---

## 12. Environment Variable Parsing

**REQ-11-30**: List-type environment variables MUST be comma-separated:

```bash
export ODOO_MCP_MODEL_ALLOWLIST="res.partner,sale.order,product.product"
export ODOO_MCP_COMPANY_IDS="1,2,3"
```

**REQ-11-31**: Boolean environment variables MUST accept: `true`, `1`, `yes` (truthy) and `false`, `0`, `no` (falsy). Case-insensitive.
