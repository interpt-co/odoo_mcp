# 02 — Connection Management

| Field        | Value                              |
|-------------|-------------------------------------|
| Document ID | SPEC-02                             |
| Title       | Connection Management               |
| Status      | Draft                               |
| Depends On  | SPEC-01                             |
| Referenced By | SPEC-03, SPEC-04, SPEC-05         |
| Sub-Specs   | L2/02a (Version Detection), L2/02b (Multi-Protocol) |

---

## 1. Overview

This document specifies how the MCP server establishes, maintains, and manages connections to an Odoo instance. It covers authentication, version auto-detection, protocol selection (XML-RPC vs JSON-2), connection pooling, and session management.

---

## 2. Connection Parameters

**REQ-02-01**: The following parameters are required to establish an Odoo connection:

| Parameter | Env Var | Type | Required | Default | Description |
|-----------|---------|------|----------|---------|-------------|
| `url` | `ODOO_URL` | string (URL) | Yes | — | Base URL of the Odoo instance (e.g., `https://mycompany.odoo.com`) |
| `database` | `ODOO_DB` | string | Yes | — | Odoo database name |
| `username` | `ODOO_USERNAME` | string | Yes (for password auth) | — | Odoo username (login) |
| `password` | `ODOO_PASSWORD` | string | Yes (for password auth) | — | Odoo password or API key |
| `api_key` | `ODOO_API_KEY` | string | Yes (for API key auth) | — | Odoo API key (Odoo 14+). Mutually exclusive with username/password for JSON-2. |
| `protocol` | `ODOO_PROTOCOL` | enum | No | `auto` | Force protocol: `auto`, `xmlrpc`, `jsonrpc`, `json2` |
| `timeout` | `ODOO_TIMEOUT` | integer | No | `30` | Request timeout in seconds |
| `verify_ssl` | `ODOO_VERIFY_SSL` | boolean | No | `true` | Verify SSL certificates |

**REQ-02-02**: The `url` parameter MUST be validated as a well-formed URL. Trailing slashes MUST be stripped. The scheme MUST be `http` or `https`.

**REQ-02-03**: If both `password` and `api_key` are provided, `api_key` takes precedence for authentication.

---

## 3. Authentication

### 3.1 Password Authentication (XML-RPC)

**REQ-02-04**: Password authentication MUST use the XML-RPC `/xmlrpc/2/common` endpoint's `authenticate` method:

```python
# Pseudocode
uid = xmlrpc_common.authenticate(database, username, password, {})
```

The returned `uid` (integer) is the authenticated user's ID. A return value of `False` indicates authentication failure.

**REQ-02-05**: After successful authentication, subsequent XML-RPC calls MUST use the `uid` and `password` for every `execute_kw` call:

```python
result = xmlrpc_object.execute_kw(database, uid, password, model, method, args, kwargs)
```

### 3.2 API Key Authentication

**REQ-02-06**: When `api_key` is provided, the server MUST:
1. For **XML-RPC**: Use the API key as the `password` parameter in both `authenticate()` and `execute_kw()` calls. The `username` is still required for `authenticate()`.
2. For **JSON-2**: Send the API key in the `Authorization: Bearer <api_key>` HTTP header. No separate authentication call is needed — the server MUST still resolve the `uid` via a `res.users` search or `/web/session/authenticate`.

**REQ-02-07**: API key authentication MUST be attempted first if an `api_key` is provided. If it fails (e.g., Odoo version < 14), the server MUST fall back to password authentication if `username` and `password` are also provided, logging a warning.

### 3.3 Session Authentication (JSON-2)

**REQ-02-08**: For JSON-2 protocol, authentication MUST use the `/web/session/authenticate` endpoint:

```json
{
  "jsonrpc": "2.0",
  "method": "call",
  "params": {
    "db": "<database>",
    "login": "<username>",
    "password": "<password>"
  }
}
```

The response contains a `session_id` cookie that MUST be stored and sent with all subsequent JSON-2 requests.

**REQ-02-09**: The JSON-2 authentication response also contains user information (`uid`, `name`, `username`, `is_admin`, `server_version`, `server_version_info`) which MUST be captured and stored in the connection state.

---

## 4. Version Detection

**REQ-02-10**: After authentication, the server MUST detect the Odoo version. See SPEC-L2/02a for the full detection protocol.

**REQ-02-11**: The detected version MUST be stored as a structured object:

```python
@dataclass
class OdooVersion:
    major: int          # e.g., 17
    minor: int          # e.g., 0
    micro: int          # e.g., 0 (patch level)
    level: str          # "final", "alpha", "beta", "rc"
    serial: int         # e.g., 0
    full_string: str    # e.g., "17.0-20240101"
    edition: str        # "community" or "enterprise"
```

**REQ-02-12**: The server MUST support Odoo versions 14.0 through 19.0. Versions outside this range MUST log a warning but attempt to connect using XML-RPC (the most compatible protocol for versions < 19) or JSON-2 (for versions >= 19).

---

## 5. Protocol Selection

**REQ-02-13**: The server supports three wire protocols:

| Protocol | Endpoints | Auth Method | Odoo Versions | Status |
|----------|-----------|-------------|---------------|--------|
| XML-RPC | `/xmlrpc/2/common`, `/xmlrpc/2/object` | uid + password per call | 8.0 — 18.0 | Stable (deprecated in 19, removed in 20) |
| JSON-RPC | `/web/session/authenticate`, `/web/dataset/call_kw` | Session cookie | 8.0 — 18.0 | Stable (deprecated in 19, removed in 20) |
| JSON-2 | `/json/2/<model>/<method>` | `Authorization: Bearer <api_key>` | 19.0+ | New, replaces XML-RPC and JSON-RPC |

When `protocol` is `auto` (default), the server MUST select the protocol based on the detected Odoo version:

| Odoo Version | Default Protocol | Reason |
|-------------|-----------------|--------|
| 14.0 — 16.0 | XML-RPC | Most compatible, well-tested |
| 17.0 — 18.0 | JSON-RPC | Session-based, richer error data than XML-RPC |
| 19.0+ | JSON-2 | New official API, XML-RPC/JSON-RPC deprecated |

**REQ-02-14**: When `protocol` is explicitly set to `xmlrpc`, `jsonrpc`, or `json2`, that protocol MUST be used regardless of version. If the selected protocol is not available (e.g., `json2` on Odoo 14, or `xmlrpc` on a future Odoo version that removed it), the server MUST fail with a clear error message.

**REQ-02-15**: The protocol adapter MUST be abstracted behind a common interface so that toolsets and other components do not depend on the specific protocol. See SPEC-L2/02b for the interface definition.

---

## 6. Protocol Abstraction

**REQ-02-16**: The abstract protocol interface MUST expose these methods:

```python
class OdooProtocol(Protocol):
    async def authenticate(self) -> int:
        """Authenticate and return uid."""
        ...

    async def execute_kw(
        self,
        model: str,
        method: str,
        args: list,
        kwargs: dict | None = None,
    ) -> Any:
        """Execute an Odoo model method."""
        ...

    async def search_read(
        self,
        model: str,
        domain: list,
        fields: list[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
    ) -> list[dict]:
        """Optimized search_read shortcut."""
        ...

    async def version_info(self) -> dict:
        """Get server version information."""
        ...

    def is_connected(self) -> bool:
        """Check if connection is active."""
        ...

    async def close(self) -> None:
        """Close the connection and release resources."""
        ...
```

**REQ-02-17**: Both the XML-RPC adapter and JSON-2 adapter MUST implement this interface. See SPEC-L2/02b for implementation details.

---

## 7. Connection Lifecycle

**REQ-02-18**: The connection manager MUST implement the following lifecycle:

```
DISCONNECTED → CONNECTING → AUTHENTICATED → READY → DISCONNECTED
                   ↓              ↓           ↓
                 ERROR          ERROR       ERROR
                   ↓              ↓           ↓
              DISCONNECTED   DISCONNECTED  RECONNECTING → AUTHENTICATED
```

States:
- **DISCONNECTED**: No connection. Initial state and terminal state.
- **CONNECTING**: Authentication in progress.
- **AUTHENTICATED**: Credentials verified, uid obtained.
- **READY**: Version detected, protocol selected, registry loaded. Tools can execute.
- **ERROR**: A connection error occurred.
- **RECONNECTING**: Automatic reconnection attempt in progress.

**REQ-02-19**: The connection manager MUST expose the current state and allow other components to check connectivity:

```python
class ConnectionManager:
    @property
    def state(self) -> ConnectionState: ...

    @property
    def is_ready(self) -> bool: ...

    @property
    def odoo_version(self) -> OdooVersion | None: ...

    @property
    def protocol(self) -> OdooProtocol | None: ...

    @property
    def uid(self) -> int | None: ...

    @property
    def database(self) -> str: ...

    @property
    def server_url(self) -> str: ...
```

---

## 8. Connection Health & Reconnection

**REQ-02-20**: The server MUST perform a health check before the first tool execution after a period of inactivity (configurable, default: 5 minutes). The health check MUST call `execute_kw('res.users', 'search_count', [[('id', '=', uid)]])` and verify the result is 1.

**REQ-02-21**: If a tool execution fails with a connection error (timeout, connection refused, session expired), the server MUST:
1. Mark the connection as `ERROR`.
2. Attempt automatic reconnection (up to 3 attempts with exponential backoff: 1s, 2s, 4s).
3. If reconnection succeeds, retry the failed operation once.
4. If reconnection fails, return an MCP error to the client with clear guidance.

**REQ-02-22**: Session expiry detection for JSON-2:
- HTTP 401 or 403 response → session expired, must re-authenticate
- JSON-RPC error with `"code": 100` (session expired) → must re-authenticate
- Cookie-based session timeout → must re-authenticate

**REQ-02-23**: Session expiry detection for XML-RPC:
- `xmlrpc.client.Fault` with "Access Denied" or fault code 1 → credentials expired/invalid
- `xmlrpc.client.ProtocolError` → network-level issue, retry

---

## 9. Connection Pooling

**REQ-02-24**: For XML-RPC, connection pooling is NOT applicable (each call is a separate HTTP request with authentication). The `ServerProxy` instances for `/xmlrpc/2/common` and `/xmlrpc/2/object` MUST be cached and reused.

**REQ-02-25**: For JSON-2, the `httpx.AsyncClient` instance MUST be reused across requests. It MUST be configured with:
- Connection pooling (default `httpx` behavior)
- The session cookie from authentication
- Keep-alive connections
- The configured timeout

**REQ-02-26**: The server MUST support a single Odoo connection at a time. Multi-connection support (connecting to multiple Odoo instances simultaneously) is NOT in scope for this version.

---

## 10. Context Management

**REQ-02-27**: The server MUST support passing Odoo context parameters with every API call. The base context MUST include:

```python
{
    "lang": "<configured language, default: 'en_US'>",
    "tz": "<configured timezone, default: 'UTC'>",
}
```

**REQ-02-28**: Individual tool calls MAY extend the base context with additional parameters (e.g., `force_company`, `active_test`). The base context MUST NOT be mutated; tool-specific context MUST be merged at call time.

**REQ-02-29**: Multi-company support: if the configuration includes `company_id` or `company_ids`, they MUST be included in the base context as:

```python
{
    "allowed_company_ids": [company_id],  # List of allowed company IDs
}
```

---

## 11. SSL/TLS Configuration

**REQ-02-30**: When `verify_ssl` is `true` (default), the server MUST verify the Odoo instance's SSL certificate using the system's certificate store.

**REQ-02-31**: When `verify_ssl` is `false`, the server MUST skip SSL verification but log a warning at startup: "SSL verification disabled. This is insecure and should only be used for development."

**REQ-02-32**: The server MUST support custom CA certificates via the `ODOO_CA_CERT` environment variable (path to a PEM file).

---

## 12. Connection Information Resource

**REQ-02-33**: The connection manager MUST expose connection metadata for use by MCP resources (see SPEC-06):

```python
def get_connection_info(self) -> dict:
    return {
        "url": self.server_url,
        "database": self.database,
        "uid": self.uid,
        "username": "<authenticated username>",
        "odoo_version": str(self.odoo_version),
        "protocol": "xmlrpc" | "json2",
        "edition": "community" | "enterprise",
        "state": self.state.value,
        "installed_modules": [...],  # Populated during registry build
    }
```
