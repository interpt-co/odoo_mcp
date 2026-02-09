# L2/02b — Multi-Protocol Interface

| Field        | Value                              |
|-------------|-------------------------------------|
| Document ID | SPEC-L2-02b                         |
| Title       | Multi-Protocol Interface             |
| Status      | Draft                               |
| Parent      | SPEC-02 (Connection Management)     |

---

## 1. Overview

The Odoo MCP server supports three communication protocols with Odoo:

- **XML-RPC** (Odoo 8–18): Stateless, uid+password per call, universally available.
- **JSON-RPC** (Odoo 8–18): Session-based, cookie auth, richer error data in responses.
- **JSON-2** (Odoo 19+): REST-style, API key Bearer auth, new official API replacing both above.

Both XML-RPC and JSON-RPC are deprecated in Odoo 19 and will be removed in Odoo 20 (fall 2026). This document specifies the abstract protocol interface and the implementation details for each adapter.

---

## 2. Abstract Protocol Interface

**REQ-02b-01**: All Odoo communication MUST go through the `OdooProtocol` abstract interface. No component outside the `connection/` module may use protocol-specific code.

```python
from typing import Any, Protocol
from abc import abstractmethod

class OdooProtocol(Protocol):
    """Abstract interface for Odoo RPC communication."""

    @property
    def protocol_name(self) -> str:
        """Return 'xmlrpc' or 'json2'."""
        ...

    @abstractmethod
    async def authenticate(self, db: str, login: str, password: str) -> int:
        """
        Authenticate with Odoo.
        Returns: uid (user ID) on success.
        Raises: AuthenticationError on failure.
        """
        ...

    @abstractmethod
    async def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> Any:
        """
        Execute an Odoo model method.

        Args:
            model: Odoo model name (e.g., 'res.partner')
            method: Method name (e.g., 'search_read')
            args: Positional arguments
            kwargs: Keyword arguments (merged into the call)
            context: Odoo context (merged with base context)

        Returns: Raw result from Odoo.
        Raises: OdooRpcError on Odoo error, ConnectionError on network error.
        """
        ...

    @abstractmethod
    async def version_info(self) -> dict:
        """
        Get Odoo server version information.
        Returns: dict with 'server_version', 'server_version_info', etc.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close the connection and release resources."""
        ...

    def is_connected(self) -> bool:
        """Check if the connection is alive."""
        ...
```

**REQ-02b-02**: Convenience methods built on top of `execute_kw` (MUST be implemented in a shared base class, not duplicated):

```python
class BaseOdooProtocol:
    """Shared implementations for both protocol adapters."""

    async def search_read(
        self,
        model: str,
        domain: list,
        fields: list[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
        context: dict | None = None,
    ) -> list[dict]:
        kwargs = {}
        if fields is not None:
            kwargs['fields'] = fields
        if offset:
            kwargs['offset'] = offset
        if limit is not None:
            kwargs['limit'] = limit
        if order:
            kwargs['order'] = order
        return await self.execute_kw(model, 'search_read', [domain], kwargs, context)

    async def read(self, model: str, ids: list[int], fields: list[str] | None = None, context: dict | None = None) -> list[dict]:
        kwargs = {}
        if fields is not None:
            kwargs['fields'] = fields
        return await self.execute_kw(model, 'read', [ids], kwargs, context)

    async def create(self, model: str, values: dict, context: dict | None = None) -> int:
        return await self.execute_kw(model, 'create', [values], context=context)

    async def write(self, model: str, ids: list[int], values: dict, context: dict | None = None) -> bool:
        return await self.execute_kw(model, 'write', [ids, values], context=context)

    async def unlink(self, model: str, ids: list[int], context: dict | None = None) -> bool:
        return await self.execute_kw(model, 'unlink', [ids], context=context)

    async def search_count(self, model: str, domain: list, context: dict | None = None) -> int:
        return await self.execute_kw(model, 'search_count', [domain], context=context)

    async def fields_get(self, model: str, attributes: list[str] | None = None, context: dict | None = None) -> dict:
        kwargs = {}
        if attributes:
            kwargs['attributes'] = attributes
        return await self.execute_kw(model, 'fields_get', [], kwargs, context)

    async def name_search(self, model: str, name: str, args: list | None = None, operator: str = 'ilike', limit: int = 5, context: dict | None = None) -> list:
        kwargs = {'args': args or [], 'operator': operator, 'limit': limit}
        return await self.execute_kw(model, 'name_search', [name], kwargs, context)
```

---

## 3. XML-RPC Adapter

**REQ-02b-03**: The XML-RPC adapter MUST implement `OdooProtocol` using Python's `xmlrpc.client`:

```python
class XmlRpcAdapter(BaseOdooProtocol):
    def __init__(self, url: str, timeout: int = 30, verify_ssl: bool = True):
        self._url = url
        self._timeout = timeout
        self._common: xmlrpc.client.ServerProxy | None = None
        self._object: xmlrpc.client.ServerProxy | None = None
        self._db: str | None = None
        self._uid: int | None = None
        self._password: str | None = None

    @property
    def protocol_name(self) -> str:
        return "xmlrpc"

    def _get_common(self) -> xmlrpc.client.ServerProxy:
        if self._common is None:
            transport = SafeTransport(timeout=self._timeout, verify_ssl=self.verify_ssl)
            self._common = xmlrpc.client.ServerProxy(
                f"{self._url}/xmlrpc/2/common",
                transport=transport,
                allow_none=True,
            )
        return self._common

    def _get_object(self) -> xmlrpc.client.ServerProxy:
        if self._object is None:
            transport = SafeTransport(timeout=self._timeout, verify_ssl=self.verify_ssl)
            self._object = xmlrpc.client.ServerProxy(
                f"{self._url}/xmlrpc/2/object",
                transport=transport,
                allow_none=True,
            )
        return self._object
```

**REQ-02b-04**: All XML-RPC calls MUST be wrapped in `asyncio.to_thread()` to avoid blocking the event loop:

```python
async def execute_kw(self, model, method, args, kwargs=None, context=None):
    merged_kwargs = dict(kwargs or {})
    if context:
        merged_kwargs['context'] = {**self._base_context, **context}
    elif self._base_context:
        merged_kwargs['context'] = self._base_context

    try:
        result = await asyncio.to_thread(
            self._get_object().execute_kw,
            self._db, self._uid, self._password,
            model, method, list(args),
            merged_kwargs if merged_kwargs else {},
        )
        return result
    except xmlrpc.client.Fault as e:
        raise OdooRpcError.from_xmlrpc_fault(e, model=model, method=method)
    except xmlrpc.client.ProtocolError as e:
        raise ConnectionError(f"XML-RPC protocol error: {e.errcode} {e.errmsg}")
    except OSError as e:
        raise ConnectionError(f"Network error: {e}")
```

**REQ-02b-05**: The XML-RPC adapter MUST use a custom `SafeTransport` that:
1. Supports configurable timeouts.
2. Supports SSL verification toggle.
3. Supports custom CA certificates.

```python
class SafeTransport(xmlrpc.client.SafeTransport):
    def __init__(self, timeout: int = 30, verify_ssl: bool = True, ca_cert: str | None = None):
        super().__init__()
        self._timeout = timeout
        self._verify_ssl = verify_ssl
        self._ca_cert = ca_cert

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        if not self._verify_ssl:
            import ssl
            conn._http_vsn_str = 'HTTP/1.1'
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            conn._context = context
        elif self._ca_cert:
            import ssl
            context = ssl.create_default_context(cafile=self._ca_cert)
            conn._context = context
        return conn
```

---

## 4. JSON-RPC Adapter (Odoo 14–18)

**REQ-02b-06**: The JSON-RPC adapter MUST implement `OdooProtocol` using `httpx` with session-based authentication:

```python
class JsonRpcAdapter(BaseOdooProtocol):
    def __init__(self, url: str, timeout: int = 30, verify_ssl: bool = True, ca_cert: str | None = None):
        self._url = url
        self._client: httpx.AsyncClient | None = None
        self._session_id: str | None = None
        self._uid: int | None = None
        self._db: str | None = None
        self._request_id: int = 0
        verify = ca_cert if ca_cert else verify_ssl
        self._client = httpx.AsyncClient(
            base_url=url,
            timeout=timeout,
            verify=verify,
            headers={"Content-Type": "application/json"},
        )

    @property
    def protocol_name(self) -> str:
        return "jsonrpc"
```

**REQ-02b-07**: JSON-RPC authentication uses `/web/session/authenticate`:

```python
async def authenticate(self, db: str, login: str, password: str) -> int:
    self._db = db
    self._request_id += 1
    response = await self._client.post("/web/session/authenticate", json={
        "jsonrpc": "2.0",
        "id": self._request_id,
        "method": "call",
        "params": {
            "db": db,
            "login": login,
            "password": password,
        },
    })
    data = response.json()

    if "error" in data:
        raise AuthenticationError(data["error"].get("message", "Authentication failed"))

    result = data.get("result", {})
    self._uid = result.get("uid")
    if not self._uid:
        raise AuthenticationError("Authentication failed: no uid returned")

    # Store session cookie — required for all subsequent JSON-RPC calls
    self._session_id = response.cookies.get("session_id")
    if self._session_id:
        self._client.cookies.set("session_id", self._session_id)

    return self._uid
```

**REQ-02b-08**: JSON-RPC method execution uses `/web/dataset/call_kw`:

```python
async def execute_kw(self, model, method, args, kwargs=None, context=None):
    merged_kwargs = dict(kwargs or {})
    if context:
        merged_kwargs['context'] = {**self._base_context, **context}
    elif self._base_context:
        merged_kwargs['context'] = self._base_context

    self._request_id += 1
    payload = {
        "jsonrpc": "2.0",
        "id": self._request_id,
        "method": "call",
        "params": {
            "model": model,
            "method": method,
            "args": list(args),
            "kwargs": merged_kwargs,
        },
    }

    try:
        # Path-based endpoint available on Odoo 17+
        endpoint = f"/web/dataset/call_kw/{model}/{method}"
        response = await self._client.post(endpoint, json=payload)

        if response.status_code == 401:
            raise SessionExpiredError("Session expired")
        if response.status_code == 403:
            raise AccessDeniedError("Access denied")

        data = response.json()

        if "error" in data:
            error_data = data["error"]
            raise OdooRpcError.from_jsonrpc_error(error_data, model=model, method=method)

        return data.get("result")

    except httpx.TimeoutException:
        raise ConnectionError(f"Request timed out after {self._client.timeout}s")
    except httpx.ConnectError as e:
        raise ConnectionError(f"Connection failed: {e}")
```

---

## 5. JSON-2 Adapter (Odoo 19+)

**REQ-02b-09**: The JSON-2 adapter MUST implement `OdooProtocol` for Odoo 19's new REST-style API:

```python
class Json2Adapter(BaseOdooProtocol):
    def __init__(self, url: str, api_key: str, timeout: int = 30, verify_ssl: bool = True, ca_cert: str | None = None):
        self._url = url
        self._api_key = api_key
        self._uid: int | None = None
        verify = ca_cert if ca_cert else verify_ssl
        self._client = httpx.AsyncClient(
            base_url=url,
            timeout=timeout,
            verify=verify,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )

    @property
    def protocol_name(self) -> str:
        return "json2"
```

**REQ-02b-09a**: JSON-2 authentication uses API key Bearer token. No separate session authentication is needed:

```python
async def authenticate(self, db: str, login: str, password: str) -> int:
    # JSON-2 uses API key — resolve uid by reading current user
    result = await self.execute_kw('res.users', 'search_read',
        [[('login', '=', login)]],
        {'fields': ['id'], 'limit': 1},
    )
    if not result:
        raise AuthenticationError("User not found")
    self._uid = result[0]['id']
    return self._uid
```

**REQ-02b-09b**: JSON-2 method execution uses the new `/json/2/<model>/<method>` endpoints:

```python
async def execute_kw(self, model, method, args, kwargs=None, context=None):
    merged_kwargs = dict(kwargs or {})
    if context:
        merged_kwargs['context'] = {**self._base_context, **context}
    elif self._base_context:
        merged_kwargs['context'] = self._base_context

    # JSON-2 uses named parameters, not positional args + kwargs
    params = {"args": list(args)}
    params.update(merged_kwargs)

    try:
        endpoint = f"/json/2/{model}/{method}"
        response = await self._client.post(endpoint, json=params)

        if response.status_code == 401:
            raise AuthenticationError("Invalid API key")
        if response.status_code == 403:
            raise AccessDeniedError("Access denied")
        if response.status_code == 404:
            raise OdooRpcError(f"Model '{model}' or method '{method}' not found",
                             model=model, method=method)

        data = response.json()
        return data.get("result")

    except httpx.TimeoutException:
        raise ConnectionError(f"Request timed out")
    except httpx.ConnectError as e:
        raise ConnectionError(f"Connection failed: {e}")
```

**REQ-02b-09c**: Key differences of JSON-2 from JSON-RPC:
- Each call runs in its own SQL transaction (no multi-call sessions).
- Proper HTTP status codes (400 for bad input, 404 for not found, 403 for access denied).
- API key required (no session cookie auth).
- The `/doc` auto-generated endpoint provides API documentation.

---

## 6. Response Normalization

**REQ-02b-10**: All three adapters MUST normalize responses to the same format. Key differences:

| Aspect | XML-RPC | JSON-RPC | JSON-2 | Normalized |
|--------|---------|----------|--------|------------|
| Many2one field | `[1, "Name"]` or `False` | `[1, "Name"]` or `false` | `[1, "Name"]` or `null` | Same (normalized by tools) |
| Boolean false | `False` (Python) | `false` (JSON) | `false` (JSON) | Python `False` |
| None/null | `False` (XML-RPC conflates) | `null` or `false` | `null` | `None` |
| Integer overflow | 32-bit limit | Full 64-bit | Full 64-bit | Python int |
| Date fields | `"2025-02-09"` | `"2025-02-09"` | `"2025-02-09"` | Same |
| Datetime fields | `"2025-02-09 14:30:00"` | `"2025-02-09 14:30:00"` | `"2025-02-09 14:30:00"` | Same |
| Binary fields | base64 string | base64 string | base64 string | Same |

**REQ-02b-11**: The adapter layer MUST NOT perform response normalization beyond JSON deserialization. Response normalization (Many2one formatting, HTML stripping, etc.) is handled by the tool response formatting layer (SPEC-04 REQ-04-35).

---

## 6. Error Translation

**REQ-02b-12**: Both adapters MUST translate protocol-specific errors into a unified `OdooRpcError`:

```python
class OdooRpcError(Exception):
    def __init__(
        self,
        message: str,
        error_class: str | None = None,      # e.g., "odoo.exceptions.ValidationError"
        traceback: str | None = None,
        model: str | None = None,
        method: str | None = None,
    ):
        super().__init__(message)
        self.error_class = error_class
        self.traceback = traceback
        self.model = model
        self.method = method

    @classmethod
    def from_xmlrpc_fault(cls, fault: xmlrpc.client.Fault, **ctx) -> 'OdooRpcError':
        # Parse faultString to extract error class and message
        lines = fault.faultString.strip().split('\n')
        last_line = lines[-1] if lines else str(fault)
        # Pattern: "odoo.exceptions.ValidationError: message"
        match = re.match(r'^([\w.]+(?:Error|Warning|Exception)):\s*(.*)', last_line)
        if match:
            return cls(
                message=match.group(2),
                error_class=match.group(1),
                traceback=fault.faultString,
                **ctx,
            )
        return cls(message=str(fault.faultString), traceback=fault.faultString, **ctx)

    @classmethod
    def from_json2_error(cls, error_data: dict, **ctx) -> 'OdooRpcError':
        data = error_data.get("data", {})
        return cls(
            message=data.get("message", error_data.get("message", "Unknown error")),
            error_class=data.get("name"),
            traceback=data.get("debug"),
            **ctx,
        )
```

---

## 8. API Key Authentication

**REQ-02b-13**: API key authentication differences between protocols:

### XML-RPC with API Key
```python
# API key is used as the password parameter
uid = await asyncio.to_thread(common.authenticate, db, username, api_key, {})
# Subsequent calls use api_key as password
result = await asyncio.to_thread(object.execute_kw, db, uid, api_key, model, method, args, kwargs)
```

### JSON-RPC with API Key
```python
# API key is used as the password in session authenticate
response = await client.post("/web/session/authenticate", json={
    "jsonrpc": "2.0", "method": "call",
    "params": {"db": db, "login": username, "password": api_key},
})
```

### JSON-2 with API Key (Odoo 19+)
```python
# API key is the ONLY authentication method — sent as Bearer token
client.headers["Authorization"] = f"Bearer {api_key}"
# No session authentication needed. Calls go directly to /json/2/<model>/<method>
```

**REQ-02b-14**: The adapter MUST try API key authentication and fall back to password authentication if it fails (for XML-RPC and JSON-RPC). JSON-2 requires an API key.

---

## 9. Connection Cleanup

**REQ-02b-15**: XML-RPC adapter cleanup:
```python
async def close(self):
    self._common = None
    self._object = None
    self._uid = None
```

**REQ-02b-16**: JSON-RPC and JSON-2 adapter cleanup:
```python
async def close(self):
    if self._client:
        await self._client.aclose()
        self._client = None
    self._session_id = None
    self._uid = None
```
