# L2/02a — Version Detection Protocol

| Field        | Value                              |
|-------------|-------------------------------------|
| Document ID | SPEC-L2-02a                         |
| Title       | Version Detection Protocol           |
| Status      | Draft                               |
| Parent      | SPEC-02 (Connection Management)     |

---

## 1. Overview

Odoo instances across versions 14.0–18.0 expose version information through different mechanisms. This sub-specification details the exact probe sequence for detecting the Odoo version, mapping versions to protocol capabilities, and handling unknown or unsupported versions.

---

## 2. Probe Sequence

**REQ-02a-01**: Version detection MUST follow this probe sequence (in order of preference):

### Probe 1: XML-RPC `version()` (Fastest, Most Universal)

```python
async def probe_xmlrpc_version(url: str) -> dict | None:
    """Call /xmlrpc/2/common version() — available on all Odoo versions."""
    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    try:
        result = await asyncio.to_thread(common.version)
        return result
    except Exception:
        return None
```

Expected response (Odoo 17.0 example):
```python
{
    "server_version": "17.0-20240101",
    "server_version_info": [17, 0, 0, "final", 0],
    "server_serie": "17.0",
    "protocol_version": 1,
}
```

**REQ-02a-02**: The `server_version_info` tuple MUST be parsed as:
```
[major, minor, micro, release_level, serial]
```
- `major`: Integer (14, 15, 16, 17, 18)
- `minor`: Integer (0)
- `micro`: Integer (patch level)
- `release_level`: String ("alpha", "beta", "candidate", "final")
- `serial`: Integer

### Probe 2: JSON-2 Session Info (Available After Authentication)

**REQ-02a-03**: If XML-RPC version probe fails (blocked, not available), attempt to get version from the JSON-2 authentication response:

```python
async def probe_json2_version(url: str, db: str, login: str, password: str) -> dict | None:
    """Authenticate via /web/session/authenticate and extract version."""
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{url}/web/session/authenticate", json={
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"db": db, "login": login, "password": password},
        })
        data = response.json()
        if "result" in data:
            return {
                "server_version": data["result"].get("server_version"),
                "server_version_info": data["result"].get("server_version_info"),
            }
    return None
```

### Probe 3: HTTP Header Inspection (Fallback)

**REQ-02a-04**: If both probes above fail, attempt to detect version from HTTP response headers or the login page:

```python
async def probe_http_version(url: str) -> str | None:
    """Inspect HTTP response for version hints."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{url}/web/login", follow_redirects=True)
        # Look for version in HTML meta tags or headers
        # Some Odoo instances include: <meta name="generator" content="Odoo 17">
        # Or the asset URLs contain version numbers: /web/assets/17.0-...
        match = re.search(r'content="Odoo\s+(\d+)"', response.text)
        if match:
            return match.group(1) + ".0"
    return None
```

---

## 3. Version Parsing

**REQ-02a-05**: The version parser MUST handle these format variations:

| Input Format | Parsed As |
|-------------|-----------|
| `[17, 0, 0, "final", 0]` | OdooVersion(major=17, minor=0, micro=0) |
| `"17.0"` | OdooVersion(major=17, minor=0, micro=0) |
| `"17.0-20240101"` | OdooVersion(major=17, minor=0, micro=0) |
| `"17.0e"` | OdooVersion(major=17, minor=0, edition="enterprise") |
| `"saas-17.1"` | OdooVersion(major=17, minor=1, level="saas") |
| `"saas~17.1"` | OdooVersion(major=17, minor=1, level="saas") |

```python
def parse_version(version_info: list | str) -> OdooVersion:
    if isinstance(version_info, list):
        return OdooVersion(
            major=version_info[0],
            minor=version_info[1],
            micro=version_info[2] if len(version_info) > 2 else 0,
            level=version_info[3] if len(version_info) > 3 else "final",
            serial=version_info[4] if len(version_info) > 4 else 0,
        )
    elif isinstance(version_info, str):
        # Handle "17.0", "17.0-20240101", "saas-17.1", "17.0e"
        version_info = version_info.replace("saas~", "saas-")
        is_enterprise = version_info.endswith("e")
        cleaned = version_info.rstrip("e").split("-")[0]
        if cleaned.startswith("saas-"):
            cleaned = cleaned[5:]
        parts = cleaned.split(".")
        return OdooVersion(
            major=int(parts[0]),
            minor=int(parts[1]) if len(parts) > 1 else 0,
            edition="enterprise" if is_enterprise else "community",
        )
```

---

## 4. Edition Detection

**REQ-02a-06**: After version detection, the server MUST attempt to detect the Odoo edition (Community vs Enterprise):

1. **From authentication response**: Check for `"is_enterprise"` key in session info (Odoo 16+).
2. **Module probe**: Check if `web_enterprise` module is installed:
   ```python
   result = await connection.search_read(
       'ir.module.module',
       [('name', '=', 'web_enterprise'), ('state', '=', 'installed')],
       fields=['name'],
   )
   is_enterprise = len(result) > 0
   ```
3. **Fallback**: If neither method works, default to `"community"` and log a warning.

---

## 5. Version-to-Protocol Mapping

**REQ-02a-07**: Protocol selection based on detected version:

| Odoo Version | XML-RPC | JSON-RPC | JSON-2 | Default Protocol | Notes |
|-------------|---------|----------|--------|-----------------|-------|
| 14.0 | Full | Full | N/A | `xmlrpc` | API key auth introduced |
| 15.0 | Full | Full | N/A | `xmlrpc` | |
| 16.0 | Full | Full | N/A | `xmlrpc` | |
| 17.0 | Full | Full | N/A | `jsonrpc` | OWL framework, richer JSON-RPC responses |
| 18.0 | Full | Full | N/A | `jsonrpc` | |
| 19.0 | Deprecated | Deprecated | Full | `json2` | JSON-2 introduced, legacy deprecated |
| 20.0+ | Removed | Removed | Full | `json2` | Legacy protocols removed |

### 5.1 Feature Availability by Version

**REQ-02a-08**: Feature availability matrix:

| Feature | 14.0 | 15.0 | 16.0 | 17.0 | 18.0 | 19.0 |
|---------|------|------|------|------|------|------|
| XML-RPC `/xmlrpc/2/*` | Yes | Yes | Yes | Yes | Yes | Deprecated |
| JSON-RPC `/web/dataset/call_kw` | Yes | Yes | Yes | Yes | Yes | Deprecated |
| JSON-2 `/json/2/<model>/<method>` | No | No | No | No | No | Yes |
| API key authentication | Yes | Yes | Yes | Yes | Yes | Yes |
| `fields_get` with attributes | Yes | Yes | Yes | Yes | Yes | Yes |
| `name_search` | Yes | Yes | Yes | Yes | Yes | Yes |
| `properties` field type | No | No | No | Yes | Yes | Yes |
| Report `/report/download` | Yes | Yes | Yes | Yes | Yes | Yes |
| `mail.activity.schedule` | No | No | No | Yes | Yes | Yes |
| `allowed_company_ids` context | Yes | Yes | Yes | Yes | Yes | Yes |
| Auto-generated `/doc` endpoint | No | No | No | No | No | Yes |

---

## 6. Fallback Strategy

**REQ-02a-09**: If version detection fails entirely (all probes fail):

1. Log a warning: "Could not detect Odoo version. Falling back to XML-RPC with version assumption 14.0."
2. Use XML-RPC protocol (most compatible).
3. Set version to `OdooVersion(major=14, minor=0, level="unknown")`.
4. Disable features that require version > 14.0.

**REQ-02a-10**: If the detected version is outside the primary supported range (< 14 or > 19):

| Version | Behavior |
|---------|----------|
| < 14 | Log warning, use XML-RPC, disable advanced features. May not work. |
| 19.0 | Fully supported. Use JSON-2 protocol. |
| 20+ | Log info, use JSON-2 (XML-RPC/JSON-RPC removed). Likely works. |

---

## 7. Version Caching

**REQ-02a-11**: The detected version MUST be cached for the lifetime of the connection. Version re-detection MUST only happen on reconnection.

**REQ-02a-12**: The version information MUST be available via `connection_manager.odoo_version` and exposed through the `odoo://system/info` resource.
