# Group 1: Foundation & Connection Layer

| Field | Value |
|-------|-------|
| Branch | `feat/foundation-connection` |
| Focus | Project scaffolding, configuration, Odoo connection, MCP server entry point |
| Spec Docs | SPEC-01, SPEC-02, L2/02a, L2/02b |
| Requirements | REQ-01-01 through REQ-01-31, REQ-02-01 through REQ-02-33, REQ-02a-01 through REQ-02a-12, REQ-02b-01 through REQ-02b-16 |

## Files Owned

```
pyproject.toml
Dockerfile
.dockerignore
odoo_mcp/__init__.py
odoo_mcp/__main__.py
odoo_mcp/server.py
odoo_mcp/config.py
odoo_mcp/connection/__init__.py
odoo_mcp/connection/protocol.py
odoo_mcp/connection/version.py
odoo_mcp/connection/xmlrpc_adapter.py
odoo_mcp/connection/jsonrpc_adapter.py
odoo_mcp/connection/json2_adapter.py
odoo_mcp/connection/manager.py
tests/conftest.py
tests/test_connection/__init__.py
tests/test_connection/test_version.py
tests/test_connection/test_xmlrpc.py
tests/test_connection/test_jsonrpc.py
tests/test_connection/test_json2.py
tests/test_connection/test_manager.py
tests/test_config.py
```

---

## Task 1.1: Project Scaffolding

**Complexity**: Small

**Description**: Create the Python package structure, `pyproject.toml`, and CLI entry points.

**Spec References**: REQ-01-01, REQ-01-02, REQ-01-03, REQ-01-04, REQ-01-05, REQ-01-07, REQ-01-12, REQ-01-19, REQ-01-20

**Files to Create**:
- `pyproject.toml`
- `odoo_mcp/__init__.py` (package version, public exports)
- `odoo_mcp/__main__.py` (CLI entry point stub)

**Implementation Details**:
1. Create `pyproject.toml` with PEP 621 metadata:
   - Name: `odoo-mcp`
   - Python: `>=3.11`
   - Dependencies: `mcp`, `httpx>=0.27`, `pydantic>=2.0`, `pydantic-settings>=2.0`
   - Entry points: `odoo-mcp` -> `odoo_mcp.__main__:main`, `odoo-mcp-registry` -> `odoo_mcp.registry.generator:main`
   - Dev dependencies: `pytest`, `pytest-asyncio`, `pytest-mock`
   - NO Odoo-specific libraries (`odoorpc`, `erppeek`, etc.)
2. `__init__.py`: Export `__version__` (read from package metadata)
3. `__main__.py`: Basic CLI skeleton with argparse for `--transport`, `--config`, `--odoo-url`, `--log-level`

**Acceptance Criteria**:
- `pip install -e .` succeeds
- `python -m odoo_mcp --help` shows CLI help
- Package structure matches SPEC-01 REQ-01-12 directory layout

---

## Task 1.2: Configuration Management

**Complexity**: Medium

**Description**: Implement the complete configuration system using Pydantic Settings.

**Spec References**: REQ-01-29, REQ-02-01, REQ-11-25 through REQ-11-31

**Files to Create**:
- `odoo_mcp/config.py`
- `tests/test_config.py`

**Implementation Details**:
1. Create `OdooMcpConfig(BaseSettings)` with ALL fields from REQ-11-25:
   - Connection: `odoo_url`, `odoo_db`, `odoo_username`, `odoo_password`, `odoo_api_key`, `odoo_protocol`, `odoo_timeout`, `odoo_verify_ssl`, `odoo_ca_cert`
   - Transport: `transport`, `host`, `port`, `mcp_path`
   - Safety: `mode`, `model_allowlist`, `model_blocklist`, `write_allowlist`, `field_blocklist`, `method_blocklist`
   - Toolsets: `enabled_toolsets`, `disabled_toolsets`
   - Registry: `static_registry_path`, `introspect_on_startup`, `introspect_models`
   - Rate limiting: `rate_limit_enabled`, `rate_limit_rpm`, `rate_limit_rph`, `rate_limit_burst`
   - Audit: `audit_enabled`, `audit_log_file`, `audit_log_reads`, `audit_log_writes`, `audit_log_deletes`
   - Context: `odoo_lang`, `odoo_tz`, `odoo_company_id`, `odoo_company_ids`
   - Search: `search_default_limit`, `search_max_limit`, `deep_search_max_depth`
   - Display: `strip_html`, `normalize_many2one`
   - Logging: `log_level`
   - Health: `health_check_interval`, `reconnect_max_attempts`, `reconnect_backoff_base`
2. Configuration priority: CLI args > env vars > config file > defaults (REQ-01-29)
3. Support JSON config file loaded via `ODOO_MCP_CONFIG` env var or `--config` CLI arg (REQ-11-26, REQ-11-27)
4. List-type env vars parsed as comma-separated strings (REQ-11-30)
5. Boolean env vars accept `true/1/yes` and `false/0/no` (REQ-11-31)
6. Startup validation (REQ-11-28):
   - URL is valid
   - Database is non-empty
   - At least one auth method provided
   - Mode is valid enum value
   - Allowlist and blocklist not both set
   - Write allowlist subset of model allowlist (if both set)
   - Port in valid range
   - Rate limit RPM > 0 if enabled
7. Validation errors produce clear messages and prevent startup (REQ-11-29)

**Acceptance Criteria**:
- Config loads from env vars, JSON file, and CLI args with correct priority
- All 40+ config fields have proper types, defaults, and validation
- Invalid config raises clear `ValueError` messages
- Test coverage for all validation rules

---

## Task 1.3: Protocol Abstraction & Error Types

**Complexity**: Medium

**Description**: Define the abstract protocol interface, shared base class, and unified error types.

**Spec References**: REQ-02-15, REQ-02-16, REQ-02-17, REQ-02b-01, REQ-02b-02, REQ-02b-12

**Files to Create**:
- `odoo_mcp/connection/__init__.py`
- `odoo_mcp/connection/protocol.py`

**Implementation Details**:
1. Define `OdooProtocol` abstract class (REQ-02b-01):
   - `protocol_name` property -> str
   - `authenticate(db, login, password)` -> int (uid)
   - `execute_kw(model, method, args, kwargs, context)` -> Any
   - `version_info()` -> dict
   - `close()` -> None
   - `is_connected()` -> bool
2. Define `BaseOdooProtocol` with shared convenience methods (REQ-02b-02):
   - `search_read(model, domain, fields, offset, limit, order, context)`
   - `read(model, ids, fields, context)`
   - `create(model, values, context)` -> int
   - `write(model, ids, values, context)` -> bool
   - `unlink(model, ids, context)` -> bool
   - `search_count(model, domain, context)` -> int
   - `fields_get(model, attributes, context)` -> dict
   - `name_search(model, name, args, operator, limit, context)` -> list
   - All convenience methods call `self.execute_kw()` internally
3. Define `OdooRpcError(Exception)` (REQ-02b-12):
   - Attributes: `message`, `error_class`, `traceback`, `model`, `method`
   - Class methods: `from_xmlrpc_fault()`, `from_jsonrpc_error()`, `from_json2_error()`
4. Define other connection exceptions:
   - `AuthenticationError(OdooRpcError)`
   - `ConnectionError(Exception)`
   - `SessionExpiredError(OdooRpcError)`
   - `AccessDeniedError(OdooRpcError)`
5. Define `OdooVersion` dataclass (REQ-02-11):
   - Fields: `major`, `minor`, `micro`, `level`, `serial`, `full_string`, `edition`
6. Define `ConnectionState` enum: `DISCONNECTED`, `CONNECTING`, `AUTHENTICATED`, `READY`, `ERROR`, `RECONNECTING`

**Acceptance Criteria**:
- `OdooProtocol` is a proper Python Protocol/ABC
- `BaseOdooProtocol` convenience methods all delegate to `execute_kw()`
- Error classes have proper `from_*` factory methods for each protocol
- All types are importable from `odoo_mcp.connection`

---

## Task 1.4: Version Detection

**Complexity**: Medium

**Description**: Implement the multi-probe version detection protocol.

**Spec References**: REQ-02-10, REQ-02-11, REQ-02-12, REQ-02a-01 through REQ-02a-12

**Files to Create**:
- `odoo_mcp/connection/version.py`
- `tests/test_connection/test_version.py`

**Implementation Details**:
1. Implement three probes in priority order (REQ-02a-01):
   - **Probe 1** - XML-RPC `version()`: Call `/xmlrpc/2/common` `version()`, parse `server_version_info` tuple (REQ-02a-01, REQ-02a-02)
   - **Probe 2** - JSON-RPC session info: POST to `/web/session/authenticate`, extract `server_version` from response (REQ-02a-03)
   - **Probe 3** - HTTP header inspection: GET `/web/login`, search for `<meta name="generator" content="Odoo XX">` or asset URL patterns (REQ-02a-04)
2. Version parser (REQ-02a-05):
   - Handle `[17, 0, 0, "final", 0]` tuple format
   - Handle `"17.0"`, `"17.0-20240101"`, `"17.0e"` string formats
   - Handle `"saas-17.1"`, `"saas~17.1"` SaaS formats
   - Return `OdooVersion` dataclass
3. Edition detection (REQ-02a-06):
   - Check `is_enterprise` in session info (Odoo 16+)
   - Probe for `web_enterprise` module installation
   - Fallback to "community"
4. Version-to-protocol mapping table (REQ-02a-07):
   - 14.0-16.0 -> xmlrpc (default)
   - 17.0-18.0 -> jsonrpc (default)
   - 19.0+ -> json2 (default)
5. Fallback strategy (REQ-02a-09, REQ-02a-10):
   - All probes fail -> assume 14.0, use XML-RPC, log warning
   - Version < 14 -> warn, use XML-RPC
   - Version >= 19 -> use JSON-2
6. Cache version for connection lifetime (REQ-02a-11)

**Acceptance Criteria**:
- All three probes implemented with proper error handling
- Version parser handles all documented format variations
- Protocol selection table matches spec exactly
- Fallback behavior matches spec
- Tests cover all version string formats and edge cases

---

## Task 1.5: XML-RPC Adapter

**Complexity**: Medium

**Description**: Implement the XML-RPC protocol adapter for Odoo 14-18.

**Spec References**: REQ-01-04, REQ-01-06, REQ-02-04, REQ-02-05, REQ-02-23, REQ-02-24, REQ-02b-03, REQ-02b-04, REQ-02b-05, REQ-02b-13, REQ-02b-15

**Files to Create**:
- `odoo_mcp/connection/xmlrpc_adapter.py`
- `tests/test_connection/test_xmlrpc.py`

**Implementation Details**:
1. `XmlRpcAdapter(BaseOdooProtocol)` class (REQ-02b-03):
   - Constructor: `url`, `timeout`, `verify_ssl`, `ca_cert`
   - Lazy-init `ServerProxy` for `/xmlrpc/2/common` and `/xmlrpc/2/object`
   - Cache and reuse both proxies (REQ-02-24)
2. `SafeTransport` class (REQ-02b-05):
   - Configurable timeout
   - SSL verification toggle
   - Custom CA certificate support
3. `authenticate()` (REQ-02-04, REQ-02-05):
   - Call `common.authenticate(db, username, password, {})`
   - Store `uid`, `db`, `password` for subsequent calls
   - Raise `AuthenticationError` if uid is `False`
4. `execute_kw()` wrapped in `asyncio.to_thread()` (REQ-01-06, REQ-02b-04):
   - Merge kwargs with base context
   - Call `object.execute_kw(db, uid, password, model, method, args, kwargs)`
   - Catch `xmlrpc.client.Fault` -> `OdooRpcError.from_xmlrpc_fault()`
   - Catch `xmlrpc.client.ProtocolError` -> `ConnectionError`
   - Catch `OSError` -> `ConnectionError`
5. API key auth: use api_key as password parameter (REQ-02b-13)
6. Session expiry detection (REQ-02-23):
   - `Fault` with "Access Denied" -> credentials expired
   - `ProtocolError` -> network issue, retry
7. `close()`: set proxies to None (REQ-02b-15)

**Acceptance Criteria**:
- All calls are async via `asyncio.to_thread()`
- Proper error translation from `Fault` to `OdooRpcError`
- SSL/timeout configuration works
- Tests with mocked `ServerProxy`

---

## Task 1.6: JSON-RPC Adapter

**Complexity**: Medium

**Description**: Implement the JSON-RPC protocol adapter for Odoo 14-18 with session-based authentication.

**Spec References**: REQ-02-08, REQ-02-09, REQ-02-22, REQ-02-25, REQ-02b-06, REQ-02b-07, REQ-02b-08, REQ-02b-13, REQ-02b-16

**Files to Create**:
- `odoo_mcp/connection/jsonrpc_adapter.py`
- `tests/test_connection/test_jsonrpc.py`

**Implementation Details**:
1. `JsonRpcAdapter(BaseOdooProtocol)` class (REQ-02b-06):
   - Constructor: `url`, `timeout`, `verify_ssl`, `ca_cert`
   - Create `httpx.AsyncClient` with connection pooling, timeout, SSL config (REQ-02-25)
   - Track `_session_id`, `_uid`, `_db`, `_request_id`
2. `authenticate()` via `/web/session/authenticate` (REQ-02b-07, REQ-02-08):
   - POST JSON-RPC payload with `db`, `login`, `password`
   - Extract `uid` from `result`
   - Store `session_id` cookie from response (REQ-02-09)
   - Capture user info: `uid`, `name`, `username`, `is_admin`, `server_version`
   - Raise `AuthenticationError` on failure
3. `execute_kw()` via `/web/dataset/call_kw/{model}/{method}` (REQ-02b-08):
   - Build JSON-RPC 2.0 payload with incrementing request ID
   - Merge kwargs with base context
   - Check HTTP status: 401/403 -> `SessionExpiredError`/`AccessDeniedError`
   - Parse JSON-RPC response: error -> `OdooRpcError.from_jsonrpc_error()`
   - Return `result` field
   - Catch `httpx.TimeoutException` -> `ConnectionError`
   - Catch `httpx.ConnectError` -> `ConnectionError`
4. Session expiry detection (REQ-02-22):
   - HTTP 401/403 -> re-authenticate
   - JSON-RPC error code 100 -> session expired
5. API key auth: use as password in authenticate (REQ-02b-13)
6. `close()`: `await client.aclose()` (REQ-02b-16)

**Acceptance Criteria**:
- Session cookie properly stored and sent with requests
- JSON-RPC 2.0 protocol correctly implemented
- Session expiry properly detected
- Tests with mocked httpx responses

---

## Task 1.7: JSON-2 Adapter

**Complexity**: Medium

**Description**: Implement the JSON-2 protocol adapter for Odoo 19+.

**Spec References**: REQ-02-06, REQ-02b-09, REQ-02b-09a, REQ-02b-09b, REQ-02b-09c, REQ-02b-13, REQ-02b-16

**Files to Create**:
- `odoo_mcp/connection/json2_adapter.py`
- `tests/test_connection/test_json2.py`

**Implementation Details**:
1. `Json2Adapter(BaseOdooProtocol)` class (REQ-02b-09):
   - Constructor: `url`, `api_key`, `timeout`, `verify_ssl`, `ca_cert`
   - Create `httpx.AsyncClient` with `Authorization: Bearer {api_key}` header
   - Track `_uid`
2. `authenticate()` (REQ-02b-09a):
   - JSON-2 uses API key Bearer token, no separate session needed
   - Resolve uid by searching `res.users` with login
   - Raise `AuthenticationError` if user not found
3. `execute_kw()` via `/json/2/{model}/{method}` (REQ-02b-09b):
   - Build params: `{"args": list(args), ...merged_kwargs}`
   - POST to endpoint
   - Handle HTTP status codes: 401 -> `AuthenticationError`, 403 -> `AccessDeniedError`, 404 -> `OdooRpcError`
   - Return `result` from JSON response
   - Catch `httpx.TimeoutException`, `httpx.ConnectError`
4. Key differences from JSON-RPC (REQ-02b-09c):
   - Each call is its own SQL transaction
   - Proper HTTP status codes
   - API key required (no session cookie)
5. `close()`: `await client.aclose()` (REQ-02b-16)

**Acceptance Criteria**:
- Bearer token auth properly configured
- REST-style endpoints correctly constructed
- Proper HTTP status code handling
- Tests with mocked httpx responses

---

## Task 1.8: Connection Manager

**Complexity**: Large

**Description**: Implement the connection lifecycle manager with health checks and reconnection.

**Spec References**: REQ-02-18 through REQ-02-29, REQ-02-30 through REQ-02-33

**Files to Create**:
- `odoo_mcp/connection/manager.py`
- `tests/test_connection/test_manager.py`

**Implementation Details**:
1. `ConnectionManager` class implementing the state machine (REQ-02-18):
   - States: `DISCONNECTED -> CONNECTING -> AUTHENTICATED -> READY -> DISCONNECTED`
   - Error transitions: any state -> `ERROR` -> `DISCONNECTED` or `RECONNECTING`
2. Properties (REQ-02-19):
   - `state: ConnectionState`
   - `is_ready: bool`
   - `odoo_version: OdooVersion | None`
   - `protocol: OdooProtocol | None`
   - `uid: int | None`
   - `database: str`
   - `server_url: str`
3. Connection establishment:
   - Create protocol adapter based on config (`auto`, `xmlrpc`, `jsonrpc`, `json2`) (REQ-02-13, REQ-02-14)
   - Authenticate (REQ-02-04 through REQ-02-09)
   - Detect version (REQ-02-10)
   - Select optimal protocol if `auto` (REQ-02-13)
   - API key takes precedence if both provided (REQ-02-03)
   - API key fallback to password if it fails (REQ-02-07)
4. Health check (REQ-02-20):
   - Before first tool execution after inactivity (configurable interval, default 5 min)
   - Call `search_count('res.users', [('id', '=', uid)])` and verify result == 1
5. Automatic reconnection (REQ-02-21):
   - On connection error: mark as ERROR
   - Retry up to 3 attempts with exponential backoff (1s, 2s, 4s)
   - On success: retry failed operation once
   - On failure: return MCP error
6. Session expiry handling per protocol (REQ-02-22, REQ-02-23)
7. Context management (REQ-02-27, REQ-02-28, REQ-02-29):
   - Base context: `{"lang": config.odoo_lang, "tz": config.odoo_tz}`
   - Multi-company: `{"allowed_company_ids": [company_id]}`
   - Tool-specific context merged at call time (base never mutated)
8. SSL configuration (REQ-02-30, REQ-02-31, REQ-02-32):
   - SSL verification toggle + warning when disabled
   - Custom CA cert support via `ODOO_CA_CERT`
9. `get_connection_info()` method (REQ-02-33):
   - Returns dict with url, database, uid, username, version, protocol, edition, state, installed_modules

**Acceptance Criteria**:
- Full state machine implemented with proper transitions
- Health check triggers after configurable inactivity
- Reconnection with exponential backoff works
- Context properly managed (base never mutated)
- SSL configuration works for all adapters
- Single connection enforced (REQ-02-26)

---

## Task 1.9: MCP Server Setup & Transport

**Complexity**: Medium

**Description**: Implement the MCP server initialization, transport setup, and startup sequence.

**Spec References**: REQ-01-08 through REQ-01-11, REQ-01-14 through REQ-01-18, REQ-01-21 through REQ-01-27

**Files to Create**:
- `odoo_mcp/server.py` (full implementation)
- Update `odoo_mcp/__main__.py` (wire CLI to server)

**Implementation Details**:
1. MCP server initialization (REQ-01-17):
   - Create `mcp.Server` with name `"odoo-mcp"`, version from package
   - Declare capabilities: `tools.listChanged`, `resources.subscribe`, `resources.listChanged`, `prompts.listChanged`, `logging`
2. Startup sequence (REQ-01-14):
   1. Parse configuration (Task 1.2)
   2. Initialize MCP server
   3. Establish Odoo connection (Task 1.8)
   4. Build model registry (stub - Group 3 implements)
   5. Register toolsets (stub - Group 4 implements)
   6. Register resources (stub - Group 3 implements)
   7. Register prompts (stub - Group 3 implements)
   8. Start transport
   - Connection failure -> exit with non-zero status (REQ-01-15)
   - Non-critical failure -> log warning, continue (REQ-01-16)
3. Transport modes (REQ-01-08, REQ-01-09, REQ-01-10):
   - **stdio**: Default, for Claude Desktop/CLI
   - **SSE**: Bind to host:port, serve at `/sse` (REQ-01-26)
   - **streamable HTTP**: Bind to host:port, serve at configurable path (REQ-01-27)
   - Transport selected via CLI/env/config (REQ-01-11)
4. Logging setup (REQ-01-21, REQ-01-22, REQ-01-23):
   - Logger name: `odoo_mcp`
   - MCP protocol-level logging via `logging` capability
   - Default level: `info`, configurable
5. Graceful shutdown (REQ-01-24):
   - Handle SIGTERM and SIGINT
   - Stop accepting requests
   - Complete in-flight operations (30s timeout)
   - Close Odoo connection
   - Close transport
   - Exit 0
6. Stubs for integration points (to be filled after merge):
   - `_register_toolsets(server, connection)` -> no-op stub
   - `_register_resources(server, connection)` -> no-op stub
   - `_register_prompts(server, connection)` -> no-op stub

**Acceptance Criteria**:
- Server starts on all three transports
- Startup sequence follows spec order
- Graceful shutdown handles signals
- Connection failure prevents startup
- Non-critical failures logged but don't block startup
- `--help` shows all CLI options

---

## Task 1.10: Dockerfile & Docker Support

**Complexity**: Small

**Description**: Create Docker deployment configuration.

**Spec References**: REQ-01-28

**Files to Create**:
- `Dockerfile`
- `.dockerignore`

**Implementation Details**:
1. `Dockerfile` (REQ-01-28):
   - Base: `python:3.11-slim`
   - Install package in production mode
   - Expose port 8080
   - Default to streamable HTTP transport
   - Accept all configuration via environment variables
   - Healthcheck using a simple script
2. `.dockerignore`:
   - Exclude `.git`, `tests/`, `*.pyc`, `__pycache__/`, `.idea/`, `spec/`, `tasks/`
3. Multi-stage build for smaller image

**Acceptance Criteria**:
- `docker build .` succeeds
- Container starts with env vars for Odoo connection
- Port 8080 exposed for SSE/HTTP transports
- Image size is reasonable (<200MB)
