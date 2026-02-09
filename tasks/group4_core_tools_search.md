# Group 4: Toolset Framework, Core Tools & Search Engine

| Field | Value |
|-------|-------|
| Branch | `feat/core-tools-search` |
| Focus | Toolset base class, registry, core CRUD tools, response formatting, progressive search |
| Spec Docs | SPEC-03, SPEC-04, SPEC-08, L2/04a |
| Requirements | REQ-03-01 through REQ-03-19, REQ-04-01 through REQ-04-38, REQ-04a-01 through REQ-04a-14, REQ-08-01 through REQ-08-19 |

## Files Owned

```
odoo_mcp/toolsets/__init__.py
odoo_mcp/toolsets/registry.py
odoo_mcp/toolsets/base.py
odoo_mcp/toolsets/core.py
odoo_mcp/toolsets/formatting.py
odoo_mcp/search/__init__.py
odoo_mcp/search/progressive.py
odoo_mcp/search/domain.py
tests/test_toolsets/__init__.py
tests/test_toolsets/test_base.py
tests/test_toolsets/test_registry.py
tests/test_toolsets/test_core.py
tests/test_toolsets/test_formatting.py
tests/test_search/__init__.py
tests/test_search/test_progressive.py
tests/test_search/test_domain.py
```

## Interface Dependencies (from other groups, available after merge)

- **OdooProtocol/ConnectionManager** (Group 1): For executing Odoo API calls
- **OdooMcpConfig** (Group 1): For safety config, search limits, display settings
- **ErrorHandler** (Group 2): For error classification on tool execution failures
- **SafetyConfig/enforce_mode** (Group 2): For mode checking before operations
- **ModelRegistry** (Group 3): For field info, model existence, method metadata

---

## Task 4.1: Base Toolset Class & Metadata

**Complexity**: Small

**Description**: Define the base toolset abstract class and metadata structures.

**Spec References**: REQ-03-01, REQ-03-02, REQ-03-03, REQ-03-11, REQ-03-12, REQ-03-13, REQ-03-14

**Files to Create**:
- `odoo_mcp/toolsets/base.py`

**Implementation Details**:
1. Define `ToolsetMetadata` dataclass (REQ-03-01):
   - `name: str` — unique identifier (e.g., "sales")
   - `description: str` — human-readable
   - `version: str` — semver
   - `required_modules: list[str]` — Odoo modules that must be installed
   - `min_odoo_version: int | None`
   - `max_odoo_version: int | None`
   - `depends_on: list[str]` — other toolset names
   - `tags: list[str]`
2. Define `BaseToolset(ABC)` (REQ-03-01):
   - `metadata() -> ToolsetMetadata` (abstract, REQ-03-02)
   - `register_tools(server, connection) -> list[str]` (abstract, REQ-03-03)
3. Tool naming convention (REQ-03-11):
   - Pattern: `odoo_{toolset}_{action}`
   - Naming helper: `tool_name(toolset, action) -> str`
4. Tool annotations integration (REQ-03-13, REQ-03-14):
   - Helper for attaching MCP annotations to registered tools
   - Read-only tools: `readOnlyHint=True`
   - Destructive tools: `destructiveHint=True`
   - All tools: `openWorldHint=True`

**Acceptance Criteria**:
- `BaseToolset` is properly abstract
- `ToolsetMetadata` captures all required fields
- Naming convention helper produces correct names
- Annotation helper produces correct MCP annotations

---

## Task 4.2: Toolset Registry (Discovery & Dependency Resolution)

**Complexity**: Medium

**Description**: Implement the toolset registry that discovers, filters, and registers toolsets.

**Spec References**: REQ-03-04 through REQ-03-10, REQ-03-15 through REQ-03-18

**Files to Create**:
- `odoo_mcp/toolsets/registry.py`
- `tests/test_toolsets/test_registry.py`

**Implementation Details**:
1. `ToolsetRegistry` class (REQ-03-04):
   ```python
   class ToolsetRegistry:
       def __init__(self, connection, config): ...
       async def discover_and_register(self, server) -> RegistrationReport: ...
       def get_registered_toolsets(self) -> list[ToolsetMetadata]: ...
       def get_toolset_for_tool(self, tool_name) -> ToolsetMetadata | None: ...
   ```
2. Discovery via explicit registration (REQ-03-05):
   - Import from `toolsets/__init__.py` `ALL_TOOLSETS` list
   - Initially only `CoreToolset` (Group 5 adds workflow toolsets after merge)
3. Dependency resolution (REQ-03-06):
   - Topological sort of toolsets based on `depends_on`
   - Detect and reject circular dependencies with clear error
4. Prerequisite checking (REQ-03-07):
   - Module check: query `ir.module.module` for installed modules
   - Version check: compare against `min_odoo_version`/`max_odoo_version`
   - Dependency check: all `depends_on` toolsets must be registered
   - Config filter: respect `enabled_toolsets` / `disabled_toolsets`
5. Failed prerequisite handling (REQ-03-08):
   - Log at `info` level
   - Skip without failing
   - Record skip reason in report
6. Registration report (REQ-03-09, REQ-03-10):
   - `ToolsetRegistrationResult`: name, status (registered/skipped/failed), tools_registered, skip_reason, error
   - `RegistrationReport`: results list, totals, timestamp
   - Logged at `info` level
   - Available via `odoo://system/toolsets` resource
7. Unique tool name enforcement (REQ-03-12):
   - Reject duplicate tool names at registration time
8. Dynamic tool list updates (REQ-03-17, REQ-03-18):
   - Send `notifications/tools/list_changed` when available tools change
   - Don't re-register without sending notification first
9. Toolset catalog (REQ-03-15):
   - Define expected toolsets (core, sales, accounting, inventory, crm, helpdesk, project, chatter, attachments, reports)
   - Core: no required modules, no depends
   - All others: depend on core, require specific modules

**Acceptance Criteria**:
- Topological sort correctly orders toolsets
- Circular dependency detected and reported
- Missing modules cause graceful skip
- Registration report is complete and accurate
- Duplicate tool names rejected
- Tests with mock toolsets verify all scenarios

---

## Task 4.3: Response Formatting & Normalization

**Complexity**: Medium

**Description**: Implement response normalization utilities shared by all tools.

**Spec References**: REQ-04-05, REQ-04-35, REQ-04-36, REQ-04-37, REQ-08-18, REQ-08-19

**Files to Create**:
- `odoo_mcp/toolsets/formatting.py`
- `tests/test_toolsets/test_formatting.py`

**Implementation Details**:
1. Many2one normalization (REQ-04-05, REQ-04-35):
   - `[1, "Name"]` -> `{"id": 1, "name": "Name"}`
   - `False` (empty Many2one) -> `null`
2. Boolean/None normalization (REQ-04-35):
   - `False` for empty string field -> `""`
   - `False` for empty date field -> `null`
   - `[1, 2, 3]` (x2many) -> `[1, 2, 3]` (no change)
3. Datetime normalization (REQ-04-37):
   - `"2025-02-09 14:30:00"` -> `"2025-02-09T14:30:00Z"` (append Z for UTC)
4. Binary field handling (REQ-04-36):
   - Binary fields excluded from results by default
   - Only returned when explicitly requested
   - Returned as base64 strings
5. HTML stripping (REQ-08-18, REQ-08-19):
   ```python
   def strip_html(html_content: str) -> str:
       # Replace <br> and </p> with newlines
       # Remove all remaining tags
       # Decode HTML entities
       # Clean up whitespace
   ```
   - Strip HTML from known HTML fields: `description`, `comment`, `body`, `note`
   - Configurable (default: strip)
6. `normalize_record(record, model_info, config)` function:
   - Apply all normalizations to a single record dict
   - Uses `FieldInfo` from registry to determine field types
7. `normalize_records(records, model_info, config)` for lists

**Acceptance Criteria**:
- Many2one tuples correctly converted to objects
- False values correctly mapped based on field type
- Datetimes have UTC Z suffix
- Binary fields excluded unless requested
- HTML stripped to clean plain text
- Tests cover all normalization rules

---

## Task 4.4: Domain Builder & Validation

**Complexity**: Medium

**Description**: Implement the domain builder utility and domain validation.

**Spec References**: REQ-04-38, REQ-04a-01 through REQ-04a-14, REQ-08-14, REQ-08-15

**Files to Create**:
- `odoo_mcp/search/__init__.py`
- `odoo_mcp/search/domain.py`
- `tests/test_search/test_domain.py`

**Implementation Details**:
1. `DomainBuilder` class (REQ-08-14):
   ```python
   class DomainBuilder:
       def equals(field, value) -> 'DomainBuilder'
       def not_equals(field, value) -> 'DomainBuilder'
       def contains(field, value) -> 'DomainBuilder'  # ilike
       def in_list(field, values) -> 'DomainBuilder'
       def greater_than(field, value) -> 'DomainBuilder'
       def less_than(field, value) -> 'DomainBuilder'
       def between(field, low, high) -> 'DomainBuilder'
       @staticmethod
       def or_(*conditions) -> 'DomainBuilder'
       def build() -> list
   ```
   - Used internally by tools and search engine (REQ-08-15)
   - NOT exposed as an MCP tool
2. Domain validation (REQ-04a-13):
   - Each element is a 3-element tuple/list OR a string operator ('&', '|', '!')
   - Operators validated against allowed set (REQ-04a-04): `=`, `!=`, `>`, `>=`, `<`, `<=`, `like`, `not like`, `ilike`, `not ilike`, `=like`, `=ilike`, `in`, `not in`, `child_of`, `parent_of`
   - `in`/`not in` operators require list values
   - Well-formed prefix notation (correct operand count)
3. Domain validation error responses (REQ-04a-14):
   - Return helpful error with correct syntax suggestion
   - Example: `"Change [('state', 'in', 'draft')] to [('state', 'in', ['draft'])]"`
4. Multi-word ilike domain builder for search:
   ```python
   def build_multi_word_ilike_domain(fields, query) -> list:
       # Split query into words
       # Create OR domain across all fields and words
       # Return prefix-notation domain
   ```

**Acceptance Criteria**:
- DomainBuilder produces correct Odoo domain syntax
- Validation catches all invalid domain patterns
- Validation errors include actionable fix suggestions
- Multi-word ilike builder works correctly
- Tests cover all operators, prefix notation, and edge cases

---

## Task 4.5: Core Toolset — Read-Only Tools

**Complexity**: Large

**Description**: Implement all read-only core tools: search_read, read, count, fields_get, name_get, default_get, list_models, list_toolsets.

**Spec References**: REQ-04-01 through REQ-04-07, REQ-04-20 through REQ-04-24, REQ-04-28 through REQ-04-34, REQ-03-19

**Files to Create**:
- `odoo_mcp/toolsets/core.py` (partial — read-only tools)
- `tests/test_toolsets/test_core.py` (partial)

**Implementation Details**:
1. `CoreToolset(BaseToolset)` class:
   - `metadata()`: name="core", no required_modules, no depends_on, min_version=14
   - `register_tools()`: Register all core tools
2. `odoo_core_search_read` (REQ-04-01 through REQ-04-05):
   - Input: model, domain (default []), fields (default [id,name,display_name]), limit (default 80, max 500), offset (default 0), order, context
   - Pre-execution: validate model (safety), validate fields (blocklist), enforce max limit, replace `['*']` with None
   - Response: `{records, count, model, limit, offset, has_more}`
   - `has_more = len(records) == limit`
   - Many2one normalization, domain syntax help in description (REQ-04-38)
3. `odoo_core_read` (REQ-04-06, REQ-04-07):
   - Input: model, ids (max 100), fields, context
   - Handle MissingError: return existing records + `missing_ids` list
4. `odoo_core_count` (REQ-04-20, REQ-04-21):
   - Input: model, domain (default []), context
   - Response: `{model, domain, count}`
5. `odoo_core_fields_get` (REQ-04-22 through REQ-04-24):
   - Input: model, attributes (default: string, type, required, readonly, help, selection, relation), context
   - Format for LLM: each field has `label`, `type`, `required`, `readonly`, `relation`, `selection`, `help`
   - Exclude blocklisted fields
6. `odoo_core_name_get` (REQ-04-28, REQ-04-29):
   - Input: model, ids (max 200)
   - Response: `{model, names: [{id, name}]}`
7. `odoo_core_default_get` (REQ-04-30, REQ-04-31):
   - Input: model, fields (default []), context
   - Response: `{model, defaults: {...}}`
8. `odoo_core_list_models` (REQ-04-32 through REQ-04-34):
   - Input: filter (ilike on name), transient (default false)
   - Response: `{models: [{model, name, transient, field_count, access}], count}`
   - Exclude blocklisted models
   - Only models user has read access to (`check_access_rights`)
9. `odoo_core_list_toolsets` (REQ-03-19):
   - No input
   - Response: `{toolsets: [{name, description, tools, odoo_modules, status}], total_tools, odoo_version, connection}`

**Acceptance Criteria**:
- All 8 read-only tools registered with correct MCP schemas
- All tools validate model/field against safety config
- search_read enforces limit cap at 500
- fields_get output is LLM-formatted (not raw Odoo)
- list_models excludes blocklisted models
- All tools have accurate MCP annotations (readOnlyHint=true)
- Tests cover each tool with mocked connection

---

## Task 4.6: Core Toolset — Write Tools

**Complexity**: Medium

**Description**: Implement write-capable core tools: create, write, unlink, execute.

**Spec References**: REQ-04-08 through REQ-04-19, REQ-04-25 through REQ-04-27

**Files to Create**:
- Update `odoo_mcp/toolsets/core.py` (add write tools)
- Update `tests/test_toolsets/test_core.py`

**Implementation Details**:
1. `odoo_core_create` (REQ-04-08 through REQ-04-11):
   - Input: model, values, context
   - Mode check: readonly->reject, restricted->check write_allowlist, full->allow
   - Response: `{id, model, message}`
   - Error handler translates validation errors to actionable guidance
2. `odoo_core_write` (REQ-04-12 through REQ-04-15):
   - Input: model, ids (max 100), values, context
   - Mode check (same as create)
   - Validate fields not in blocklist and not readonly
   - Response: `{success, model, ids, message}`
3. `odoo_core_unlink` (REQ-04-16 through REQ-04-19):
   - Input: model, ids (max 50), context
   - Mode check: ONLY allowed in `full` mode
   - Check model against blocklist
   - Log deletion in audit log
   - Annotation: `destructiveHint=true`
   - Response: `{success, model, deleted_ids, message}`
4. `odoo_core_execute` (REQ-04-25 through REQ-04-27):
   - Input: model, method, args (default []), kwargs (default {}), context
   - Validations:
     - Methods starting with `_` REJECTED (private)
     - Check method blocklist
     - Mode check: readonly rejects non-read methods
     - Strip kwargs for `NO_KWARGS_METHODS`
   - Response formatting for action dicts:
     - `{result_type: "action", action: {type, res_model, res_id, view_mode, summary}}`
   - Simple value returns:
     - `{result_type: "value", result: ...}`
5. All write tools check mode BEFORE any Odoo API call

**Acceptance Criteria**:
- Mode enforcement works for all three modes
- Private methods (starting with `_`) rejected
- `NO_KWARGS_METHODS` have kwargs stripped
- Action dict results get human-readable summary
- Audit logging called for unlink operations
- Tests cover mode enforcement for each tool

---

## Task 4.7: Progressive Deep Search

**Complexity**: Large

**Description**: Implement the 5-level progressive search engine.

**Spec References**: REQ-08-01 through REQ-08-13

**Files to Create**:
- `odoo_mcp/search/progressive.py`
- `tests/test_search/test_progressive.py`

**Implementation Details**:
1. Define `ModelSearchConfig` dataclass (REQ-08-04):
   - `model`, `name_field`, `search_fields`, `deep_search_fields`, `default_fields`, `has_chatter`, `related_models`
2. Define all default search configs (REQ-08-05):
   - `res.partner`, `sale.order`, `account.move`, `crm.lead`, `helpdesk.ticket`, `product.product`, `project.task`
3. Implement 5 search levels (REQ-08-01):
   - **Level 1 — Exact Match** (REQ-08-07): `(name_field, '=', query)`
   - **Level 2 — Standard ilike** (REQ-08-08): Multi-word OR domain across `search_fields`
   - **Level 3 — Extended Fields** (REQ-08-09): Same as Level 2 but with `deep_search_fields`. Verify fields exist via registry.
   - **Level 4 — Related Models** (REQ-08-10):
     - Search query in related models (e.g., find partner in res.partner)
     - Extract partner IDs
     - Expand: company -> include child contacts; individual -> include parent + siblings
     - Search primary model: `('partner_id', 'in', expanded_ids)`
   - **Level 5 — Chatter Search** (REQ-08-11):
     - Search `mail.message` body for models with chatter
     - Extract `res_id` values, deduplicate
     - Read the actual records
4. Stop behavior (REQ-08-02): Stop when a level produces >= 1 result (unless `exhaustive=True`)
5. Fallback for unknown models (REQ-08-06): use `name` field and `name_search`
6. `odoo_core_deep_search` tool integration (REQ-08-03):
   - Input: query, model (optional), max_depth (default 3), limit (default 20), fields (optional), exhaustive (default false)
   - Register as part of core toolset
7. Response format (REQ-08-12):
   - Results grouped by model
   - Search log: level, strategy, model, results_found per step
   - depth_reached, total_results, strategies_used
   - LLM-actionable suggestions (REQ-08-13)

**Acceptance Criteria**:
- All 5 search levels implemented
- Progressive stop-on-results works
- Exhaustive mode runs all levels
- Related model expansion works (company->contacts, individual->parent)
- Chatter search works
- Search log provides full transparency
- Suggestions are actionable (reference tool names)
- Tests with mocked data for each level

---

## Task 4.8: Name Search Utility

**Complexity**: Small

**Description**: Implement the reusable name_search utility for workflow tools.

**Spec References**: REQ-08-16, REQ-08-17

**Files to Create**:
- Update `odoo_mcp/search/__init__.py` (add name_search utility)

**Implementation Details**:
1. `name_search()` function (REQ-08-16):
   ```python
   async def name_search(
       connection, model, name,
       operator='ilike', limit=5, domain=None,
   ) -> list[dict]:
   ```
2. Wraps Odoo's native `name_search` method (REQ-08-17):
   - Calls `execute_kw(model, 'name_search', [name], {args, operator, limit})`
   - Normalizes `[[id, name], ...]` to `[{"id": id, "name": name}, ...]`
3. This utility is used by:
   - Group 5's workflow tools for name resolution
   - Group 4's deep search (Level 1 fallback)

**Acceptance Criteria**:
- Correctly wraps Odoo's name_search
- Normalizes tuple format to dict format
- Works with custom operators and domains

---

## Task 4.9: Toolsets __init__.py & Integration

**Complexity**: Small

**Description**: Create the toolsets package initialization with the ALL_TOOLSETS registry.

**Spec References**: REQ-03-05, REQ-03-16

**Files to Create**:
- `odoo_mcp/toolsets/__init__.py`

**Implementation Details**:
1. Define `ALL_TOOLSETS` list (REQ-03-05):
   ```python
   from .core import CoreToolset
   # After merge with Group 5, add:
   # from .sales import SalesToolset
   # from .accounting import AccountingToolset
   # ... etc.

   ALL_TOOLSETS = [
       CoreToolset,
       # SalesToolset,      # Added by Group 5 merge
       # AccountingToolset,  # Added by Group 5 merge
       # ... etc.
   ]
   ```
2. Document that adding toolsets only requires (REQ-03-16):
   - Creating the file
   - Adding the class to `ALL_TOOLSETS`
   - No core framework changes needed

**Acceptance Criteria**:
- Package imports correctly
- `ALL_TOOLSETS` contains CoreToolset
- Comments clearly indicate where Group 5 toolsets will be added

---

## Task 4.10: Core Tools & Search Tests

**Complexity**: Medium

**Description**: Comprehensive tests for toolset framework, core tools, and search.

**Files to Create/Update**:
- `tests/test_toolsets/test_base.py`
- `tests/test_toolsets/test_registry.py`
- `tests/test_toolsets/test_core.py`
- `tests/test_search/test_progressive.py`
- `tests/test_search/test_domain.py`

**Implementation Details**:
1. Base toolset tests:
   - Test metadata validation
   - Test tool naming convention
2. Registry tests:
   - Test topological sort
   - Test circular dependency detection
   - Test prerequisite checking (modules, version)
   - Test registration report
3. Core tool tests:
   - Test each tool with mocked connection
   - Test safety mode enforcement (readonly, restricted, full)
   - Test domain validation
   - Test response normalization
   - Test error handling for each tool
4. Search tests:
   - Test each search level independently
   - Test progressive stop behavior
   - Test exhaustive mode
   - Test domain builder
   - Test name_search utility

**Acceptance Criteria**:
- >90% coverage for toolsets/ and search/
- All tests pass without Odoo instance
- Mock protocol used consistently
