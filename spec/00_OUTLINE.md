# Odoo MCP Server — Master Specification Outline

| Field        | Value                                           |
|-------------|--------------------------------------------------|
| Document ID | SPEC-00                                          |
| Title       | Master Outline & Document Map                    |
| Status      | Draft                                            |
| Version     | 0.1.0                                            |
| MCP Spec    | 2025-11-25                                       |
| Odoo Target | 14.0, 15.0, 16.0, 17.0, 18.0, 19.0 (forward-compatible) |
| Created     | 2025-02-09                                       |

---

## 1. Purpose

This document is the root of the Odoo MCP Server specification. It provides:

- A **document map** listing every specification document and its purpose
- **Section summaries** for each L1 specification
- A **cross-reference index** linking requirements across documents
- The **requirement numbering scheme** used throughout

The specification is designed so that a developer can implement the entire MCP server from these documents alone, without needing to ask clarifying questions.

---

## 2. Requirement Numbering Scheme

All requirements follow the pattern: **REQ-{section}-{number}**

| Prefix   | Section                        | Document                         |
|----------|-------------------------------|----------------------------------|
| REQ-01   | Architecture                  | `01_ARCHITECTURE.md`             |
| REQ-02   | Connection                    | `02_CONNECTION.md`               |
| REQ-03   | Toolsets                      | `03_TOOLSETS.md`                 |
| REQ-04   | Core Tools                    | `04_CORE_TOOLS.md`               |
| REQ-05   | Workflow Tools                | `05_WORKFLOW_TOOLS.md`           |
| REQ-06   | Resources & Prompts           | `06_RESOURCES_AND_PROMPTS.md`    |
| REQ-07   | Registry                      | `07_REGISTRY.md`                 |
| REQ-08   | Search                        | `08_SEARCH.md`                   |
| REQ-09   | Chatter, Attachments, Reports | `09_CHATTER_ATTACHMENTS_REPORTS.md` |
| REQ-10   | Error Handling                | `10_ERROR_HANDLING.md`           |
| REQ-11   | Safety & Configuration        | `11_SAFETY_CONFIG.md`            |

L2 sub-specifications use extended prefixes: **REQ-02a-{number}**, **REQ-05a-{number}**, etc.

---

## 3. Document Map

### L0 — Master Outline

| Document | Title | Purpose |
|----------|-------|---------|
| `spec/00_OUTLINE.md` | Master Outline & Document Map | This document. Root of the specification hierarchy. |

### L1 — Detailed Specifications

| # | Document | Title | Summary |
|---|----------|-------|---------|
| 01 | `spec/01_ARCHITECTURE.md` | System Architecture | Module structure, tech stack (Python, `mcp` SDK), deployment models (stdio, SSE, streamable HTTP), directory layout, dependency graph. |
| 02 | `spec/02_CONNECTION.md` | Connection Management | Odoo connection lifecycle, authentication flows (password, API key), version auto-detection, dual protocol adapter (XML-RPC + JSON-2), connection pooling, session management. |
| 03 | `spec/03_TOOLSETS.md` | Toolset Architecture | Toolset registry pattern, toolset dependency graph, dynamic tool registration, lazy loading, per-connection tool enablement. |
| 04 | `spec/04_CORE_TOOLS.md` | Core CRUD Tools | `search_read`, `read`, `create`, `write`, `unlink`, `count`, `fields_get`, `execute`, `name_get`, `default_get`. Full schemas for each tool including input/output JSON schemas. |
| 05 | `spec/05_WORKFLOW_TOOLS.md` | Business Workflow Tools | High-level tools for sales, accounting, inventory, CRM, helpdesk, project. Wizard handling protocol. Module-aware tool availability. |
| 06 | `spec/06_RESOURCES_AND_PROMPTS.md` | MCP Resources & Prompts | `odoo://` URI scheme, resource templates, model metadata resources, system prompts, prompt templates for common operations. |
| 07 | `spec/07_REGISTRY.md` | Model/Field/Method Registry | Static registry generation, runtime merge with live introspection, method signatures, workflow state machines, field metadata caching. |
| 08 | `spec/08_SEARCH.md` | Progressive Deep Search | Name search, multi-word search, domain builder, progressive search strategy, search result formatting. |
| 09 | `spec/09_CHATTER_ATTACHMENTS_REPORTS.md` | Chatter, Attachments & Reports | Chatter message operations, file attachment handling (upload/download), PDF report generation, binary field management. |
| 10 | `spec/10_ERROR_HANDLING.md` | Error Handling | Error classification taxonomy, LLM-friendly error format, error pattern database, retry guidance, traceback translation. |
| 11 | `spec/11_SAFETY_CONFIG.md` | Safety & Configuration | Operation modes (readonly/restricted/full), tool annotations, model/field allowlists and blocklists, rate limiting, audit logging, full configuration reference. |

### L2 — Sub-Specifications

| Document | Parent | Title | Purpose |
|----------|--------|-------|---------|
| `spec/L2/02a_VERSION_DETECTION.md` | 02 | Version Detection Protocol | Probe sequence for detecting Odoo version, version-to-protocol mapping table, fallback strategy for unknown versions. |
| `spec/L2/02b_DUAL_PROTOCOL.md` | 02 | Multi-Protocol Interface | Abstract protocol interface definition, XML-RPC adapter, JSON-RPC adapter, JSON-2 adapter (Odoo 19+), response normalization. |
| `spec/L2/04a_DOMAIN_SYNTAX.md` | 04 | Domain Filter Reference | Complete domain filter syntax, all operators, Polish notation rules, Many2many/One2many command tuples, LLM-friendly domain examples. |
| `spec/L2/05a_WIZARD_PROTOCOL.md` | 05 | Wizard Execution Protocol | TransientModel detection, wizard lifecycle (create → execute → read result), known wizard catalog with parameter schemas. |
| `spec/L2/10a_ERROR_PATTERNS.md` | 10 | Error Pattern Database | Complete mapping of Odoo error strings/patterns to LLM-friendly explanations and resolution guidance. |

---

## 4. Section Summaries

### 01 — Architecture

Defines the overall system as a Python package using the official `mcp` SDK. The server supports three transport modes: **stdio** (for Claude Desktop / CLI integration), **SSE** (for web clients), and **streamable HTTP** (MCP spec 2025-11-25 preferred transport). The codebase follows a modular architecture with clear separation between protocol handling, Odoo communication, and tool definitions. Key architectural decision: the **toolset pattern** (inspired by Salesforce MCP) where tools are grouped into functional sets that can be independently enabled/disabled.

### 02 — Connection

Covers everything needed to establish and maintain a connection to an Odoo instance. Supports three protocols: **XML-RPC** (universally available, Odoo 8–18), **JSON-RPC** (session-based, Odoo 8–18, richer error data), and **JSON-2** (Odoo 19+, REST-style, API key auth). Connection parameters come from either environment variables or MCP configuration. The server auto-detects the Odoo version on first connection and selects the optimal protocol. Connection pooling reuses authenticated sessions. Authentication supports both password-based login and API key authentication (Odoo 14+).

### 03 — Toolsets

The toolset architecture is the primary organizational pattern. Each toolset is a self-contained group of related tools (e.g., `core`, `sales`, `inventory`). Toolsets declare dependencies on other toolsets, specific Odoo modules, and minimum Odoo versions. The toolset registry handles discovery, dependency resolution, and conditional registration. An LLM client only sees tools from toolsets whose prerequisites are met by the connected Odoo instance.

### 04 — Core Tools

Defines the fundamental CRUD tools that work on any Odoo model. These are always available regardless of installed modules. Each tool has a complete JSON schema for both input and output. Core tools include `search_read` (the workhorse for data retrieval), `read`, `create`, `write`, `unlink`, `count`, `fields_get`, `execute` (generic method execution), `name_get`, and `default_get`. Every tool enforces safety constraints from the configuration.

### 05 — Workflow Tools

Higher-level tools that combine multiple Odoo operations into business-meaningful actions: creating a sale order with lines, confirming invoices, processing inventory moves, creating CRM leads, etc. These tools are only available when their corresponding Odoo module is installed. The wizard handling protocol (detailed in L2/05a) provides a general mechanism for executing Odoo wizards (TransientModel) through MCP tools.

### 06 — Resources & Prompts

Defines the MCP resources exposed by the server using the `odoo://` URI scheme. Resource templates allow dynamic access to model metadata, record data, and system information. Prompts provide pre-built templates for common operations (e.g., "create an invoice", "search for a customer") that help LLMs use the tools correctly.

### 07 — Registry

The model/field/method registry is the server's knowledge base about the connected Odoo instance. It can be built two ways: **statically** (from a pre-generated JSON file for offline/fast startup) or **dynamically** (by introspecting the live Odoo instance at connection time). The runtime registry merges static data with live introspection results. It tracks model names, field definitions, available methods, and workflow state machines.

### 08 — Search

Implements a progressive deep search strategy designed for LLM interactions. When a simple `name_search` fails, the system progressively tries broader strategies: multi-field search, partial matching, related model search, and finally full-text search. The domain builder helps LLMs construct valid Odoo domain filters from natural language descriptions.

### 09 — Chatter, Attachments & Reports

Covers three related capabilities: **chatter** (Odoo's built-in messaging/activity system via `mail.message` and `mail.activity`), **attachments** (uploading, downloading, and linking files via `ir.attachment`), and **reports** (generating PDF documents from Odoo's QWeb report engine). Binary data is handled via base64 encoding.

### 10 — Error Handling

Defines how Odoo errors are caught, classified, and translated into LLM-friendly responses. Errors are categorized into classes (validation, access, constraint, programming, network) with specific guidance for each. The error pattern database (L2/10a) maps known Odoo error messages to structured responses that help an LLM understand what went wrong and how to fix it.

### 11 — Safety & Configuration

Defines the three operation modes (**readonly**, **restricted**, **full**) and all safety mechanisms. Tool annotations declare each tool's risk level per the MCP spec. Model/field allowlists and blocklists control what data the server can access. Rate limiting prevents abuse. Audit logging records all operations. The full configuration reference documents every configuration parameter with defaults, validation rules, and examples.

---

## 5. Key Design Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D-01 | Toolset architecture (not flat tool list) | Scales to large tool counts without overwhelming the LLM context. Allows conditional registration based on installed Odoo modules. Follows successful Salesforce MCP pattern. |
| D-02 | Triple protocol support (XML-RPC + JSON-RPC + JSON-2) | XML-RPC ensures compatibility with Odoo 14–18. JSON-RPC provides session-based access for Odoo 14–18 with richer error data. JSON-2 is the forward-compatible path for Odoo 19+. All abstracted behind a common interface. |
| D-03 | LLM-optimized error format | Raw Odoo tracebacks are useless to LLMs. Structured error responses with classification, explanation, and suggested fixes dramatically improve LLM recovery. |
| D-04 | Progressive deep search | LLMs often search with imprecise terms. Progressive strategies (name → multi-field → partial → related) compensate for this without requiring the LLM to understand Odoo's search internals. |
| D-05 | Static + dynamic registry | Static registry enables fast startup and offline documentation. Dynamic merge ensures accuracy against the live instance. Combined approach gives best of both worlds. |
| D-06 | Wizard as first-class pattern | Wizards are how Odoo handles complex multi-step operations. Most existing MCP implementations ignore them. First-class support unlocks significant workflow automation. |
| D-07 | Three operation modes | Clear security boundaries. Read-only mode for exploration, restricted for controlled writes, full for trusted environments. Prevents accidental data modification. |

---

## 6. Technology Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Language | Python | >= 3.11 |
| MCP SDK | `mcp` (official Python SDK) | latest |
| Transport | stdio, SSE, streamable HTTP | MCP spec 2025-11-25 |
| Odoo Protocol | XML-RPC (`xmlrpc.client`), JSON-2 (`httpx`) | — |
| HTTP Client | `httpx` | >= 0.27 |
| Configuration | Environment variables + JSON config | — |
| Schema Validation | Pydantic v2 | >= 2.0 |
| Async Runtime | `asyncio` | stdlib |
| Packaging | `pyproject.toml` (PEP 621) | — |

---

## 7. Cross-Reference Index

| Requirement | Referenced By | Context |
|------------|---------------|---------|
| REQ-01-06 (asyncio wrapping) | REQ-02b-04 (XML-RPC to_thread) | XML-RPC calls wrapped in asyncio.to_thread |
| REQ-01-12 (Module structure) | REQ-03-05 (Toolset discovery) | Toolsets discovered from toolsets/__init__.py |
| REQ-01-14 (Startup sequence) | REQ-02-01 (Connection params), REQ-03-04 (Registry) | Startup calls connection, then registry, then toolsets |
| REQ-02-10 (Version detection) | REQ-02a-01..12 (Version detection sub-spec) | Full probe sequence in L2 |
| REQ-02-13 (Protocol selection) | REQ-02a-07 (Version-to-protocol map) | Version determines default protocol |
| REQ-02-15 (Protocol abstraction) | REQ-02b-01..02 (Abstract interface) | Interface + convenience methods in L2 |
| REQ-02-16 (Protocol interface) | REQ-02b-03..09 (Adapters) | XML-RPC and JSON-2 implementations |
| REQ-03-07 (Prerequisite checking) | REQ-02-33 (Connection info) | Module list from connection for toolset filtering |
| REQ-03-13 (Tool annotations) | REQ-11-17..18 (Annotations spec) | Safety spec defines annotation values |
| REQ-04-01 (search_read) | REQ-08-07..11 (Search levels) | Deep search uses search_read internally |
| REQ-04-02 (Safety validation) | REQ-11-06..09 (Model filtering) | search_read checks allowlist/blocklist |
| REQ-04-05 (Many2one normalization) | REQ-04-35 (Response formatting) | Normalization rules for all tools |
| REQ-04-08 (create) | REQ-05-01..33 (Workflow tools) | Workflow tools call create internally |
| REQ-04-25 (execute) | REQ-05a-04 (Wizard execution) | Wizards use execute for action methods |
| REQ-04-26 (NO_KWARGS_METHODS) | REQ-07-17 (Known methods registry) | Registry maintains the no-kwargs set |
| REQ-04-38 (Domain syntax help) | REQ-04a-01..14 (Domain reference) | Complete syntax in L2 |
| REQ-05-02 (Name resolution) | REQ-05-36 (Name resolution pattern) | Shared disambiguation pattern |
| REQ-05-16 (Register payment) | REQ-05a-04..08 (Wizard protocol) | Payment uses wizard protocol |
| REQ-05-21 (Validate picking) | REQ-05a-08 (Known wizard catalog) | Backorder/immediate transfer wizards |
| REQ-05-34 (Wizard handling) | REQ-05a-01..11 (Full wizard protocol) | Complete wizard spec in L2 |
| REQ-06-06..08 (Model resources) | REQ-07-20 (Registry as resource) | Resources served from registry data |
| REQ-06-18 (Domain help prompt) | REQ-04a-12 (Common patterns) | Prompt includes domain patterns from L2 |
| REQ-07-01 (Registry data model) | REQ-07-09..12 (Dynamic registry) | Runtime introspection populates model |
| REQ-07-14 (Registry merge) | REQ-07-02..08 (Static + dynamic) | Merge strategy for both sources |
| REQ-08-04 (Search config) | REQ-07-01 (Registry structure) | Search configs reference registry fields |
| REQ-08-18 (HTML stripping) | REQ-09-01..03 (Chatter messages) | Same strip_html function used |
| REQ-10-01 (Error categories) | REQ-10a-01..03 (Pattern database) | Patterns classified into categories |
| REQ-10-05 (XML-RPC errors) | REQ-02b-12 (Error translation) | Adapter translates to OdooRpcError |
| REQ-10-11 (Pattern database) | REQ-10a-01..03 (Full database) | Complete patterns in L2 |
| REQ-10-17 (MCP error handling) | REQ-04-11 (Create error) | Tools return isError:true with structured data |
| REQ-11-01 (Operation modes) | REQ-04-09,17 (Mode enforcement) | Core tools enforce mode before operations |
| REQ-11-04 (Tool visibility) | REQ-03-13 (Tool annotations) | Mode determines which tools are registered |
| REQ-11-06..09 (Model filtering) | REQ-04-02,34 (Validation) | Core tools validate against filters |
| REQ-11-22..24 (Audit logging) | REQ-04-17 (Delete audit) | Destructive operations logged |

---

## 8. Glossary

| Term | Definition |
|------|-----------|
| **Domain** | Odoo's query filter format — a list of tuples in Polish (prefix) notation. Example: `[('state', '=', 'draft'), ('partner_id.name', 'ilike', 'acme')]` |
| **JSON-RPC** | Odoo's session-based JSON-RPC API, accessed at `/web/dataset/call_kw`. Available since Odoo 8. Uses session cookies for auth. Deprecated in Odoo 19. |
| **JSON-2** | Odoo's new REST-style API introduced in Odoo 19, accessed at `/json/2/<model>/<method>`. Uses API key Bearer auth. Replaces XML-RPC and JSON-RPC. |
| **MCP** | Model Context Protocol — Anthropic's open protocol for connecting LLMs to external tools and data sources |
| **Toolset** | A logical group of related MCP tools that share a common domain (e.g., all sales-related tools) |
| **TransientModel** | Odoo model type used for wizards — records are temporary and auto-deleted |
| **XML-RPC** | Odoo's legacy remote procedure call protocol, available at `/xmlrpc/2/common` and `/xmlrpc/2/object` |
| **Registry** | (In this spec) The server's cached knowledge about Odoo models, fields, and methods |
| **SSE** | Server-Sent Events — one of MCP's transport mechanisms |
| **Streamable HTTP** | MCP's preferred transport (spec 2025-11-25) — HTTP POST with optional SSE upgrade |
| **Tool Annotation** | MCP metadata on a tool declaring its behavior (readOnlyHint, destructiveHint, etc.) |

---

## 9. Document Status Tracker

| Document | Status | Requirements | Open Questions |
|----------|--------|-------------|----------------|
| `00_OUTLINE.md` | Review | — | 0 |
| `01_ARCHITECTURE.md` | Review | 31 | 0 |
| `02_CONNECTION.md` | Review | 33 | 0 |
| `03_TOOLSETS.md` | Review | 19 | 0 |
| `04_CORE_TOOLS.md` | Review | 38 | 0 |
| `05_WORKFLOW_TOOLS.md` | Review | 37 | 0 |
| `06_RESOURCES_AND_PROMPTS.md` | Review | 23 | 0 |
| `07_REGISTRY.md` | Review | 20 | 0 |
| `08_SEARCH.md` | Review | 19 | 0 |
| `09_CHATTER_ATTACHMENTS_REPORTS.md` | Review | 26 | 0 |
| `10_ERROR_HANDLING.md` | Review | 19 | 0 |
| `11_SAFETY_CONFIG.md` | Review | 31 | 0 |
| `L2/02a_VERSION_DETECTION.md` | Review | 12 | 0 |
| `L2/02b_DUAL_PROTOCOL.md` | Review | 19 | 0 |
| `L2/04a_DOMAIN_SYNTAX.md` | Review | 14 | 0 |
| `L2/05a_WIZARD_PROTOCOL.md` | Review | 11 | 0 |
| `L2/10a_ERROR_PATTERNS.md` | Review | 3 | 0 |
| **TOTAL** | — | **355** | **0** |

*Status values: Draft → Review → Final*
