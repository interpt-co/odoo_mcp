# 01 — System Architecture

| Field        | Value                              |
|-------------|-------------------------------------|
| Document ID | SPEC-01                             |
| Title       | System Architecture                 |
| Status      | Draft                               |
| Depends On  | —                                   |
| Referenced By | SPEC-02, SPEC-03, SPEC-11         |

---

## 1. Overview

This document defines the overall system architecture of the Odoo MCP Server: its module structure, technology stack, deployment models, startup sequence, and directory layout.

The server is a Python application that implements the Model Context Protocol (MCP, spec 2025-11-25) to expose Odoo ERP functionality as tools, resources, and prompts consumable by LLM clients (e.g., Claude Desktop, Claude Code, custom agents).

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      MCP Client                              │
│              (Claude Desktop / CLI / Agent)                   │
└─────────────┬───────────────────────────────┬───────────────┘
              │  MCP Protocol                  │
              │  (stdio | SSE | streamable HTTP)│
              ▼                                ▼
┌─────────────────────────────────────────────────────────────┐
│                     MCP Server Layer                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │Transport │  │  Tool    │  │ Resource │  │  Prompt    │  │
│  │ Handler  │  │ Router   │  │ Router   │  │  Router    │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └─────┬──────┘  │
│       │              │              │               │        │
│  ┌────▼──────────────▼──────────────▼───────────────▼────┐  │
│  │                  Toolset Registry                      │  │
│  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌────────────┐  │  │
│  │  │ Core │ │Sales │ │ Acct │ │Stock │ │ ...more    │  │  │
│  │  └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘ └─────┬──────┘  │  │
│  └─────┼────────┼────────┼────────┼────────────┼─────────┘  │
│        ▼        ▼        ▼        ▼            ▼            │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Odoo Connection Layer                    │   │
│  │  ┌──────────────┐  ┌──────────────┐                  │   │
│  │  │  XML-RPC      │  │   JSON-2     │                  │   │
│  │  │  Adapter      │  │   Adapter    │                  │   │
│  │  └──────┬────────┘  └──────┬───────┘                  │   │
│  │         └──────┬───────────┘                          │   │
│  │         ┌──────▼───────┐                              │   │
│  │         │  Protocol    │                              │   │
│  │         │  Abstraction │                              │   │
│  │         └──────────────┘                              │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌────────────────────┐  ┌────────────────────┐             │
│  │   Model Registry   │  │   Error Handler    │             │
│  └────────────────────┘  └────────────────────┘             │
└─────────────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Odoo Instance                             │
│            (14.0 — 18.0, self-hosted or Odoo.sh)            │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Requirements

### 3.1 Technology Stack

**REQ-01-01**: The server MUST be implemented in Python >= 3.11.

**REQ-01-02**: The server MUST use the official `mcp` Python SDK (PyPI: `mcp`) as its MCP protocol implementation.

**REQ-01-03**: The server MUST use `httpx` (>= 0.27) for all HTTP communication with Odoo (JSON-2 protocol, health checks).

**REQ-01-04**: The server MUST use the stdlib `xmlrpc.client` module for XML-RPC communication with Odoo.

**REQ-01-05**: The server MUST use Pydantic v2 (>= 2.0) for all configuration validation, tool input/output schemas, and internal data models.

**REQ-01-06**: The server MUST use `asyncio` as its async runtime. All public API methods that perform I/O MUST be async. XML-RPC calls (which are synchronous) MUST be wrapped in `asyncio.to_thread()` to avoid blocking the event loop.

**REQ-01-07**: The server MUST be packaged using `pyproject.toml` (PEP 621) with the following entry points:
- `odoo-mcp` — CLI entry point for launching the server
- `odoo-mcp-registry` — CLI entry point for static registry generation

### 3.2 Transport Modes

**REQ-01-08**: The server MUST support the **stdio** transport for integration with Claude Desktop and Claude Code. This is the default transport.

**REQ-01-09**: The server MUST support the **SSE** (Server-Sent Events) transport for web-based clients, bound to a configurable host and port.

**REQ-01-10**: The server MUST support the **streamable HTTP** transport (MCP spec 2025-11-25 preferred transport). This is HTTP POST with optional upgrade to SSE for streaming responses.

**REQ-01-11**: The transport mode MUST be selectable via:
1. CLI argument: `--transport stdio|sse|http` (default: `stdio`)
2. Environment variable: `ODOO_MCP_TRANSPORT`
3. Configuration file: `transport` key

Priority: CLI argument > environment variable > config file > default.

### 3.3 Module Structure

**REQ-01-12**: The codebase MUST follow this package structure:

```
odoo_mcp/
├── __init__.py
├── __main__.py              # CLI entry point
├── server.py                # MCP server initialization
├── config.py                # Configuration management (Pydantic models)
├── connection/
│   ├── __init__.py
│   ├── manager.py           # Connection lifecycle management
│   ├── protocol.py          # Abstract protocol interface
│   ├── xmlrpc_adapter.py    # XML-RPC implementation (Odoo 14-18)
│   ├── jsonrpc_adapter.py   # JSON-RPC implementation (Odoo 14-18)
│   ├── json2_adapter.py     # JSON-2 implementation (Odoo 19+)
│   └── version.py           # Version detection logic
├── toolsets/
│   ├── __init__.py
│   ├── registry.py          # Toolset registry and dependency resolution
│   ├── base.py              # Base toolset class
│   ├── core.py              # Core CRUD tools
│   ├── sales.py             # Sales workflow tools
│   ├── accounting.py        # Accounting workflow tools
│   ├── inventory.py         # Inventory/warehouse tools
│   ├── crm.py               # CRM tools
│   ├── helpdesk.py          # Helpdesk tools
│   ├── project.py           # Project management tools
│   ├── chatter.py           # Messaging/chatter tools
│   ├── attachments.py       # Attachment handling tools
│   └── reports.py           # Report generation tools
├── resources/
│   ├── __init__.py
│   ├── provider.py          # Resource and resource template registration
│   └── uri.py               # odoo:// URI scheme parser
├── prompts/
│   ├── __init__.py
│   └── provider.py          # Prompt template registration
├── registry/
│   ├── __init__.py
│   ├── model_registry.py    # Runtime model/field registry
│   ├── static_data.py       # Pre-generated registry data
│   └── generator.py         # Static registry generation script
├── search/
│   ├── __init__.py
│   ├── progressive.py       # Progressive deep search engine
│   └── domain.py            # Domain builder utilities
├── errors/
│   ├── __init__.py
│   ├── handler.py           # Error classification and translation
│   └── patterns.py          # Error pattern database
└── safety/
    ├── __init__.py
    ├── modes.py             # Operation mode enforcement
    ├── audit.py             # Audit logging
    └── limits.py            # Rate limiting
```

**REQ-01-13**: Each subdirectory (`connection/`, `toolsets/`, etc.) MUST be a self-contained module that can be tested independently.

### 3.4 Startup Sequence

**REQ-01-14**: The server startup sequence MUST proceed in this order:

1. **Parse configuration** — Load and validate config from CLI args, env vars, and config file (see SPEC-11).
2. **Initialize MCP server** — Create the `mcp.Server` instance with server name and version.
3. **Establish Odoo connection** — Authenticate with Odoo, detect version, select protocol (see SPEC-02).
4. **Build model registry** — Load static registry if available, merge with live introspection (see SPEC-07).
5. **Register toolsets** — Discover toolsets, resolve dependencies, register tools whose prerequisites are met (see SPEC-03).
6. **Register resources** — Register `odoo://` resources and templates (see SPEC-06).
7. **Register prompts** — Register prompt templates (see SPEC-06).
8. **Start transport** — Begin listening on the configured transport.

**REQ-01-15**: If step 3 (Odoo connection) fails, the server MUST NOT start. It MUST log a clear error message and exit with a non-zero status code.

**REQ-01-16**: If a non-critical step (4–7) partially fails (e.g., a toolset's module prerequisite is not met), the server MUST log a warning and continue with the successfully registered components. The server MUST NOT fail entirely due to an optional toolset being unavailable.

### 3.5 Server Metadata

**REQ-01-17**: The server MUST declare the following MCP capabilities during initialization:

```json
{
  "name": "odoo-mcp",
  "version": "<package version from pyproject.toml>",
  "capabilities": {
    "tools": { "listChanged": true },
    "resources": { "subscribe": true, "listChanged": true },
    "prompts": { "listChanged": true },
    "logging": {}
  }
}
```

**REQ-01-18**: `tools.listChanged` MUST be `true` because the available tools may change if the Odoo connection is re-established with a different instance or if modules are installed/uninstalled.

### 3.6 Dependency Management

**REQ-01-19**: The server MUST declare these runtime dependencies in `pyproject.toml`:

| Package | Minimum Version | Purpose |
|---------|----------------|---------|
| `mcp` | latest | MCP protocol SDK |
| `httpx` | 0.27 | HTTP client for JSON-2 |
| `pydantic` | 2.0 | Schema validation |
| `pydantic-settings` | 2.0 | Configuration from env vars |

**REQ-01-20**: The server MUST NOT depend on any Odoo-specific Python libraries (e.g., `odoorpc`, `erppeek`, `odoo-client-lib`). All Odoo communication MUST use the raw XML-RPC and JSON-2 protocols. This avoids version-specific library issues and reduces the dependency surface.

### 3.7 Logging

**REQ-01-21**: The server MUST use Python's stdlib `logging` module with the logger name `odoo_mcp`.

**REQ-01-22**: The server MUST support MCP protocol-level logging via the `logging` capability. Log messages sent over MCP MUST use the MCP log levels: `debug`, `info`, `warning`, `error`, `critical`.

**REQ-01-23**: The default log level MUST be `info`. It MUST be configurable via the `ODOO_MCP_LOG_LEVEL` environment variable or the `log_level` configuration key.

### 3.8 Graceful Shutdown

**REQ-01-24**: The server MUST handle `SIGTERM` and `SIGINT` signals gracefully:
1. Stop accepting new MCP requests.
2. Complete any in-flight tool executions (with a 30-second timeout).
3. Close the Odoo connection (release sessions).
4. Close the transport.
5. Exit with status code 0.

---

## 4. Deployment Models

### 4.1 Claude Desktop Integration

**REQ-01-25**: The server MUST be configurable in Claude Desktop's `claude_desktop_config.json` as:

```json
{
  "mcpServers": {
    "odoo": {
      "command": "odoo-mcp",
      "args": ["--transport", "stdio"],
      "env": {
        "ODOO_URL": "https://mycompany.odoo.com",
        "ODOO_DB": "mycompany",
        "ODOO_USERNAME": "admin",
        "ODOO_PASSWORD": "admin-api-key"
      }
    }
  }
}
```

### 4.2 SSE Deployment

**REQ-01-26**: When running in SSE mode, the server MUST:
- Bind to the configured host (default: `127.0.0.1`) and port (default: `8080`)
- Serve the SSE endpoint at `/sse`
- Support multiple concurrent client connections

### 4.3 Streamable HTTP Deployment

**REQ-01-27**: When running in streamable HTTP mode, the server MUST:
- Bind to the configured host (default: `127.0.0.1`) and port (default: `8080`)
- Accept POST requests at `/mcp` (configurable path)
- Support optional SSE upgrade for streaming responses
- Include session management headers per MCP spec

### 4.4 Docker Deployment

**REQ-01-28**: The repository MUST include a `Dockerfile` that:
- Uses `python:3.11-slim` as base image
- Installs the package in production mode
- Exposes port 8080 for SSE/HTTP transports
- Defaults to streamable HTTP transport
- Accepts all configuration via environment variables

---

## 5. Configuration Hierarchy

**REQ-01-29**: Configuration values MUST be resolved in this priority order (highest first):

1. CLI arguments (e.g., `--odoo-url`)
2. Environment variables (e.g., `ODOO_URL`)
3. Configuration file (JSON, path specified by `ODOO_MCP_CONFIG` env var or `--config` CLI arg)
4. Default values

See SPEC-11 for the full configuration reference.

---

## 6. Testing Strategy

**REQ-01-30**: The project MUST include:
- Unit tests for all modules (using `pytest`)
- Integration tests that connect to a real Odoo instance (gated behind `--integration` pytest marker)
- A mock Odoo server fixture for unit tests that simulates XML-RPC and JSON-2 responses

**REQ-01-31**: Unit tests MUST be runnable without any Odoo instance available. All Odoo interactions MUST be mockable at the protocol adapter level.
