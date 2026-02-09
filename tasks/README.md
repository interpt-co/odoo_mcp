# Odoo MCP Server - Implementation Tasks

## Parallel Development Strategy

This project is split into **5 independent work groups** designed for parallel development
in separate git worktrees/branches. Each group:

- Owns exclusive files (no overlap between groups)
- Contains sequential tasks (ordered by dependency within the group)
- Has no cross-group code dependencies (each group can compile/test independently)
- Produces a clean merge when all 5 branches are combined

## Group Overview

| Group | Branch | Focus | Files Owned | Tasks |
|-------|--------|-------|-------------|-------|
| 1 | `feat/foundation-connection` | Project setup, config, connection layer, MCP server | `pyproject.toml`, `Dockerfile`, `odoo_mcp/{__init__,__main__,server,config}.py`, `odoo_mcp/connection/*` | 10 |
| 2 | `feat/errors-safety` | Error handling, safety modes, rate limiting, audit | `odoo_mcp/errors/*`, `odoo_mcp/safety/*` | 8 |
| 3 | `feat/registry-resources` | Model registry, resources, prompts, static generator | `odoo_mcp/registry/*`, `odoo_mcp/resources/*`, `odoo_mcp/prompts/*`, `scripts/*` | 9 |
| 4 | `feat/core-tools-search` | Toolset framework, core CRUD tools, search engine | `odoo_mcp/toolsets/{__init__,registry,base,core,formatting}.py`, `odoo_mcp/search/*` | 10 |
| 5 | `feat/workflow-toolsets` | Business workflow tools, wizard protocol, domain toolsets | `odoo_mcp/toolsets/{wizard,helpers,sales,accounting,inventory,crm,helpdesk,project,chatter,attachments,reports}.py` | 11 |

**Total: 48 tasks across 5 groups**

## File Ownership Map

```
odoo_mcp/
├── __init__.py              → Group 1
├── __main__.py              → Group 1
├── server.py                → Group 1
├── config.py                → Group 1
├── connection/              → Group 1 (all files)
│   ├── __init__.py
│   ├── manager.py
│   ├── protocol.py
│   ├── xmlrpc_adapter.py
│   ├── jsonrpc_adapter.py
│   ├── json2_adapter.py
│   └── version.py
├── errors/                  → Group 2 (all files)
│   ├── __init__.py
│   ├── handler.py
│   └── patterns.py
├── safety/                  → Group 2 (all files)
│   ├── __init__.py
│   ├── modes.py
│   ├── audit.py
│   └── limits.py
├── registry/                → Group 3 (all files)
│   ├── __init__.py
│   ├── model_registry.py
│   ├── static_data.py
│   └── generator.py
├── resources/               → Group 3 (all files)
│   ├── __init__.py
│   ├── provider.py
│   └── uri.py
├── prompts/                 → Group 3 (all files)
│   ├── __init__.py
│   └── provider.py
├── toolsets/
│   ├── __init__.py          → Group 4
│   ├── registry.py          → Group 4
│   ├── base.py              → Group 4
│   ├── core.py              → Group 4
│   ├── formatting.py        → Group 4
│   ├── wizard.py            → Group 5
│   ├── helpers.py           → Group 5
│   ├── sales.py             → Group 5
│   ├── accounting.py        → Group 5
│   ├── inventory.py         → Group 5
│   ├── crm.py               → Group 5
│   ├── helpdesk.py          → Group 5
│   ├── project.py           → Group 5
│   ├── chatter.py           → Group 5
│   ├── attachments.py       → Group 5
│   └── reports.py           → Group 5
├── search/                  → Group 4 (all files)
│   ├── __init__.py
│   ├── progressive.py
│   └── domain.py
pyproject.toml               → Group 1
Dockerfile                   → Group 1
.dockerignore                → Group 1
scripts/
└── runtime_introspect.py    → Group 3
tests/
├── test_connection/         → Group 1
├── test_errors/             → Group 2
├── test_safety/             → Group 2
├── test_registry/           → Group 3
├── test_resources/          → Group 3
├── test_toolsets/           → Group 4
├── test_search/             → Group 4
└── test_workflows/          → Group 5
```

## Merge Strategy

1. All 5 branches are developed from the same `main` base commit
2. Each branch creates ONLY its owned files (no overlapping edits)
3. Merge order doesn't matter (no conflicts expected)
4. After merging all 5, a final integration commit wires everything together in `server.py`:
   - Import all toolsets into `toolsets/__init__.py` ALL_TOOLSETS list
   - Wire error handler, safety, registry, resources, prompts into server.py startup
   - This integration step is trivial because each module exposes clean interfaces

## Interface Contracts

Each group must respect these interfaces (defined in spec, implemented independently):

- **OdooProtocol** (Group 1 defines): abstract class with `execute_kw`, `search_read`, etc.
- **OdooRpcError** (Group 1 defines): exception with `error_class`, `traceback`, `model`, `method`
- **OdooMcpConfig** (Group 1 defines): Pydantic settings model with all config fields
- **ConnectionManager** (Group 1 defines): exposes `.protocol`, `.odoo_version`, `.is_ready`, `.uid`
- **ErrorResponse** (Group 2 defines): dataclass with `category`, `code`, `message`, `suggestion`
- **SafetyConfig** (Group 2 defines): mode enforcement, model/field filtering
- **ModelRegistry** (Group 3 defines): `get_model()`, `get_field()`, `model_exists()`, etc.
- **BaseToolset** (Group 4 defines): abstract class with `metadata()` and `register_tools()`
- **ToolsetRegistry** (Group 4 defines): `discover_and_register()`, registration report
