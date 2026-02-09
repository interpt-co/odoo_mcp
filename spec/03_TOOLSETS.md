# 03 — Toolset Architecture

| Field        | Value                              |
|-------------|-------------------------------------|
| Document ID | SPEC-03                             |
| Title       | Toolset Architecture                |
| Status      | Draft                               |
| Depends On  | SPEC-01, SPEC-02                    |
| Referenced By | SPEC-04, SPEC-05, SPEC-11         |

---

## 1. Overview

This document defines the toolset architecture — the organizational pattern for grouping, registering, and managing MCP tools. Toolsets are the primary mechanism for scaling the tool surface while keeping it manageable for LLM clients.

The design is inspired by the Salesforce MCP Server's toolset pattern, adapted for Odoo's module-based architecture.

---

## 2. Design Principles

1. **Grouped by domain**: Tools that operate on related Odoo models are grouped into a single toolset (e.g., all sales-related tools in the `sales` toolset).
2. **Conditional registration**: A toolset's tools are only registered if the toolset's prerequisites (Odoo modules, version) are met.
3. **Dependency-aware**: Toolsets can depend on other toolsets. Dependencies are resolved at startup.
4. **Discoverable**: The LLM client can query which toolsets are available and what tools they contain.
5. **Configurable**: Administrators can enable/disable specific toolsets via configuration.

---

## 3. Requirements

### 3.1 Base Toolset Class

**REQ-03-01**: Every toolset MUST extend the `BaseToolset` abstract class:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

@dataclass
class ToolsetMetadata:
    """Metadata describing a toolset's requirements and identity."""
    name: str                           # Unique identifier (e.g., "sales")
    description: str                    # Human-readable description
    version: str                        # Toolset version (semver)
    required_modules: list[str] = field(default_factory=list)   # Odoo modules that must be installed
    min_odoo_version: int | None = None # Minimum Odoo major version (e.g., 14)
    max_odoo_version: int | None = None # Maximum Odoo major version (e.g., 18)
    depends_on: list[str] = field(default_factory=list)         # Other toolset names this depends on
    tags: list[str] = field(default_factory=list)               # Categorization tags

class BaseToolset(ABC):
    """Abstract base class for all toolsets."""

    @abstractmethod
    def metadata(self) -> ToolsetMetadata:
        """Return toolset metadata."""
        ...

    @abstractmethod
    def register_tools(self, server: McpServer, connection: ConnectionManager) -> list[str]:
        """Register this toolset's tools with the MCP server. Returns list of tool names registered."""
        ...
```

**REQ-03-02**: The `metadata()` method MUST return a `ToolsetMetadata` instance that fully describes the toolset's identity and requirements.

**REQ-03-03**: The `register_tools()` method MUST register all of the toolset's tools using the MCP SDK's `@server.tool()` decorator or equivalent programmatic registration. It MUST return a list of the tool names that were registered.

### 3.2 Toolset Registry

**REQ-03-04**: The `ToolsetRegistry` class MUST:
1. Discover all available toolset classes (via explicit registration or entry points).
2. Resolve dependencies between toolsets (topological sort).
3. Check prerequisites (installed modules, version) against the connected Odoo instance.
4. Register eligible toolsets and track which tools belong to which toolset.

```python
class ToolsetRegistry:
    def __init__(self, connection: ConnectionManager, config: ServerConfig):
        ...

    async def discover_and_register(self, server: McpServer) -> RegistrationReport:
        """Discover, filter, and register all eligible toolsets."""
        ...

    def get_registered_toolsets(self) -> list[ToolsetMetadata]:
        """Return metadata for all registered toolsets."""
        ...

    def get_toolset_for_tool(self, tool_name: str) -> ToolsetMetadata | None:
        """Return the toolset that owns a given tool."""
        ...
```

**REQ-03-05**: The discovery phase MUST use explicit registration (not auto-discovery). Each toolset class MUST be imported and registered in the toolsets package `__init__.py`:

```python
# toolsets/__init__.py
ALL_TOOLSETS = [
    CoreToolset,
    SalesToolset,
    AccountingToolset,
    InventoryToolset,
    CrmToolset,
    HelpdeskToolset,
    ProjectToolset,
    ChatterToolset,
    AttachmentsToolset,
    ReportsToolset,
]
```

**REQ-03-06**: Dependency resolution MUST use topological sorting. If a circular dependency is detected, the server MUST fail at startup with a clear error message listing the cycle.

### 3.3 Prerequisite Checking

**REQ-03-07**: Before registering a toolset, the registry MUST verify:

1. **Module prerequisites**: All entries in `required_modules` MUST be installed on the Odoo instance. Module installation is checked by querying `ir.module.module`:
   ```python
   installed = await connection.protocol.search_read(
       'ir.module.module',
       [('name', 'in', required_modules), ('state', '=', 'installed')],
       fields=['name'],
   )
   installed_names = {m['name'] for m in installed}
   ```

2. **Version prerequisites**: The Odoo version MUST be >= `min_odoo_version` and <= `max_odoo_version` (if set).

3. **Dependency prerequisites**: All toolsets listed in `depends_on` MUST have been successfully registered.

4. **Configuration filter**: If the configuration specifies `enabled_toolsets` (allowlist) or `disabled_toolsets` (blocklist), apply accordingly.

**REQ-03-08**: If a toolset's prerequisites are not met, the registry MUST:
1. Log a message at `info` level explaining why the toolset was skipped.
2. Skip the toolset without failing.
3. Record the skip reason in the `RegistrationReport`.

### 3.4 Registration Report

**REQ-03-09**: After registration completes, the registry MUST produce a `RegistrationReport`:

```python
@dataclass
class ToolsetRegistrationResult:
    name: str
    status: Literal["registered", "skipped", "failed"]
    tools_registered: list[str]         # Empty if skipped/failed
    skip_reason: str | None             # Reason for skip (e.g., "module 'sale' not installed")
    error: str | None                   # Error message if failed

@dataclass
class RegistrationReport:
    results: list[ToolsetRegistrationResult]
    total_toolsets: int
    registered_toolsets: int
    total_tools: int
    timestamp: str                      # ISO 8601
```

**REQ-03-10**: The registration report MUST be logged at `info` level and also available via the `odoo://system/toolsets` resource (see SPEC-06).

### 3.5 Tool Naming Convention

**REQ-03-11**: All tool names MUST follow the pattern: `odoo_{toolset}_{action}` where:
- `toolset` is the toolset name (e.g., `core`, `sales`)
- `action` describes the operation (e.g., `search_read`, `create_order`)

Examples:
- `odoo_core_search_read`
- `odoo_core_create`
- `odoo_sales_create_order`
- `odoo_accounting_post_invoice`
- `odoo_inventory_validate_picking`

**REQ-03-12**: Tool names MUST be unique across all toolsets. The registry MUST reject duplicate tool names at registration time with a clear error.

### 3.6 Tool Annotations

**REQ-03-13**: Every registered tool MUST include MCP tool annotations that describe its behavior (per MCP spec 2025-11-25):

```python
@dataclass
class ToolAnnotations:
    title: str                          # Human-readable title
    readOnlyHint: bool = False          # True if tool only reads data
    destructiveHint: bool = False       # True if tool deletes data
    idempotentHint: bool = False        # True if repeated calls have same effect
    openWorldHint: bool = True          # True if tool interacts with external system
```

**REQ-03-14**: Tool annotations MUST be accurate:
- `search_read`, `read`, `count`, `fields_get`, `name_get`, `default_get` → `readOnlyHint: true`
- `create`, `write` → `readOnlyHint: false, destructiveHint: false`
- `unlink` → `readOnlyHint: false, destructiveHint: true`
- All tools → `openWorldHint: true` (they interact with Odoo)

---

## 4. Toolset Catalog

**REQ-03-15**: The following toolsets MUST be implemented:

| Toolset | Name | Required Modules | Min Version | Depends On | Description |
|---------|------|-----------------|-------------|------------|-------------|
| Core | `core` | — | 14 | — | CRUD operations on any model |
| Sales | `sales` | `sale` | 14 | `core` | Sales order workflows |
| Accounting | `accounting` | `account` | 14 | `core` | Invoice and payment workflows |
| Inventory | `inventory` | `stock` | 14 | `core` | Stock moves and warehouse operations |
| CRM | `crm` | `crm` | 14 | `core` | Lead and opportunity management |
| Helpdesk | `helpdesk` | `helpdesk` | 14 | `core` | Ticket management (Enterprise) |
| Project | `project` | `project` | 14 | `core` | Project and task management |
| Chatter | `chatter` | `mail` | 14 | `core` | Messaging and activity tools |
| Attachments | `attachments` | — | 14 | `core` | File attachment operations |
| Reports | `reports` | — | 14 | `core` | PDF report generation |

**REQ-03-16**: Additional toolsets MAY be added in future versions. The architecture MUST support adding new toolsets by:
1. Creating a new file in `toolsets/`.
2. Defining a class extending `BaseToolset`.
3. Adding it to the `ALL_TOOLSETS` list.

No changes to the core framework should be needed.

---

## 5. Dynamic Tool List Updates

**REQ-03-17**: If the set of available tools changes (e.g., after reconnection to a different Odoo instance), the server MUST send a `notifications/tools/list_changed` notification to the client per the MCP spec.

**REQ-03-18**: The server MUST NOT re-register tools during an active session without first sending the `list_changed` notification. The client is expected to re-fetch the tool list after receiving this notification.

---

## 6. Toolset Information Tool

**REQ-03-19**: The `core` toolset MUST include a meta-tool `odoo_core_list_toolsets` that returns information about all registered toolsets:

```json
{
  "name": "odoo_core_list_toolsets",
  "description": "List all available toolsets and their tools. Use this to discover what operations are available.",
  "inputSchema": {
    "type": "object",
    "properties": {}
  }
}
```

Response format:
```json
{
  "toolsets": [
    {
      "name": "core",
      "description": "Core CRUD operations on any Odoo model",
      "tools": ["odoo_core_search_read", "odoo_core_create", "..."],
      "odoo_modules": [],
      "status": "active"
    },
    {
      "name": "sales",
      "description": "Sales order workflows",
      "tools": ["odoo_sales_create_order", "..."],
      "odoo_modules": ["sale"],
      "status": "active"
    }
  ],
  "total_tools": 42,
  "odoo_version": "17.0",
  "connection": "https://mycompany.odoo.com"
}
```
