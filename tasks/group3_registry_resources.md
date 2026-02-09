# Group 3: Model Registry & Resources/Prompts

| Field | Value |
|-------|-------|
| Branch | `feat/registry-resources` |
| Focus | Model/field/method registry, MCP resources, MCP prompts, static registry generator |
| Spec Docs | SPEC-06, SPEC-07 |
| Requirements | REQ-06-01 through REQ-06-23, REQ-07-01 through REQ-07-20 |

## Files Owned

```
odoo_mcp/registry/__init__.py
odoo_mcp/registry/model_registry.py
odoo_mcp/registry/static_data.py
odoo_mcp/registry/generator.py
odoo_mcp/resources/__init__.py
odoo_mcp/resources/provider.py
odoo_mcp/resources/uri.py
odoo_mcp/prompts/__init__.py
odoo_mcp/prompts/provider.py
scripts/runtime_introspect.py
tests/test_registry/__init__.py
tests/test_registry/test_model_registry.py
tests/test_registry/test_generator.py
tests/test_registry/test_merge.py
tests/test_resources/__init__.py
tests/test_resources/test_uri.py
tests/test_resources/test_provider.py
```

## Interface Dependencies (from other groups, available after merge)

- **OdooProtocol** (Group 1): For dynamic introspection calls (`search_read`, `fields_get`, `execute_kw`)
- **ConnectionManager** (Group 1): For connection info, installed modules list
- **SafetyConfig** (Group 2): For model/field blocklist filtering in resources

---

## Task 3.1: Registry Data Models

**Complexity**: Medium

**Description**: Define all registry data structures — FieldInfo, MethodInfo, ModelInfo, Registry.

**Spec References**: REQ-07-01, REQ-07-17, REQ-07-19

**Files to Create**:
- `odoo_mcp/registry/__init__.py`
- `odoo_mcp/registry/model_registry.py` (data classes and Registry shell)

**Implementation Details**:
1. Define `FieldInfo` dataclass (REQ-07-01):
   - `name`, `label`, `type`, `required`, `readonly`, `store`, `help`
   - `relation` (for relational fields), `selection` (for selection fields)
   - `default`, `groups`, `compute`, `depends`
2. Define `MethodInfo` dataclass:
   - `name`, `description`, `accepts_kwargs`, `decorator`
3. Define `ModelInfo` dataclass:
   - `model`, `name`, `description`, `transient`
   - `fields: dict[str, FieldInfo]`
   - `methods: dict[str, MethodInfo]`
   - `states: list[tuple[str, str]] | None`
   - `parent_models: list[str]`
   - `has_chatter: bool`
4. Define `Registry` dataclass:
   - `models: dict[str, ModelInfo]`
   - `version`, `build_mode` ("static"/"dynamic"/"merged"), `build_timestamp`
   - `model_count`, `field_count`
5. Define `NO_KWARGS_METHODS` set (REQ-07-17):
   - All methods from spec: `action_cancel`, `action_confirm`, `action_draft`, `action_done`, `action_lock`, `action_unlock`, `button_validate`, `button_draft`, `button_cancel`, `button_confirm`, `action_post`, `action_open`, `action_set_draft`, `action_quotation_send`, `action_view_invoice`, `copy`, `name_get`, `name_search`, `read`, `search`, `search_read`, `search_count`, `fields_get`, `default_get`, `onchange`
6. Define field type reference mapping (REQ-07-19):
   - Odoo type -> Python type -> JSON type mapping table

**Acceptance Criteria**:
- All dataclasses match the spec structures exactly
- `NO_KWARGS_METHODS` set matches spec
- Types are serializable to/from JSON
- Field type mapping is complete

---

## Task 3.2: Registry Access API

**Complexity**: Medium

**Description**: Implement the ModelRegistry class with all query methods.

**Spec References**: REQ-07-13, REQ-07-16, REQ-07-18

**Files to Create**:
- Update `odoo_mcp/registry/model_registry.py` (add ModelRegistry class)

**Implementation Details**:
1. `ModelRegistry` class with query methods (REQ-07-16):
   ```python
   def get_model(model_name) -> ModelInfo | None
   def get_field(model_name, field_name) -> FieldInfo | None
   def get_method(model_name, method_name) -> MethodInfo | None
   def list_models(filter: str | None = None) -> list[ModelInfo]
   def get_required_fields(model_name) -> list[FieldInfo]
   def get_state_field(model_name) -> FieldInfo | None
   def get_relational_fields(model_name) -> list[FieldInfo]
   def method_accepts_kwargs(method_name) -> bool
   async def model_exists(model_name) -> bool
   ```
2. Model existence checking (REQ-07-13):
   - Check in-memory registry first
   - If not found, attempt `search_count(model, [], limit=0)` on live instance
   - Cache both positive and negative results
3. `method_accepts_kwargs()` (REQ-07-18):
   - Check against `NO_KWARGS_METHODS` set
   - If method in set, return False -> kwargs must be stripped
4. Internal `_registry: Registry` storage
5. Methods to populate: `load_static()`, `build_dynamic()`, `merge()`

**Acceptance Criteria**:
- All 9 query methods implemented
- Model existence checking with caching works
- `method_accepts_kwargs()` correctly identifies no-kwargs methods
- Thread-safe access to registry data

---

## Task 3.3: Dynamic Registry (Live Introspection)

**Complexity**: Large

**Description**: Build registry by introspecting a live Odoo instance via the API.

**Spec References**: REQ-07-09, REQ-07-10, REQ-07-11, REQ-07-12

**Files to Create**:
- Update `odoo_mcp/registry/model_registry.py` (add `build_dynamic()`)

**Implementation Details**:
1. Introspection process (REQ-07-10):
   a. Get installed modules: `search_read('ir.module.module', [('state', '=', 'installed')], ['name', 'shortdesc'])`
   b. Get available models: `search_read('ir.model', [...], ['model', 'name', 'info', 'transient'])` for target models. Filter to models user has read access to.
   c. Get field metadata: Call `fields_get(attributes=[...])` for each target model
   d. Method discovery: rely on static registry + `action_*/button_*` pattern
2. Default target models (REQ-07-07):
   - `res.partner`, `res.users`, `res.company`
   - `sale.order`, `sale.order.line`
   - `purchase.order`, `purchase.order.line`
   - `account.move`, `account.move.line`
   - `stock.picking`, `stock.move`, `stock.move.line`, `stock.quant`, `stock.warehouse`, `stock.location`
   - `product.template`, `product.product`, `product.category`
   - `crm.lead`, `crm.stage`
   - `helpdesk.ticket`, `helpdesk.stage`, `helpdesk.team`
   - `project.project`, `project.task`, `project.milestone`
   - `hr.employee`, `hr.department`, `hr.leave`
   - `calendar.event`
   - `mail.message`, `mail.activity`
   - `ir.attachment`
3. Throttling (REQ-07-11):
   - Max 5 concurrent `fields_get` calls (use `asyncio.Semaphore`)
   - Total introspection time limit: 60 seconds
   - After timeout, use whatever was collected (log warning)
4. Caching (REQ-07-12):
   - Cache in memory
   - Refresh on explicit request only
   - Detect stale data opportunistically during tool execution
   - NEVER auto-refresh on timer
5. Connection interface: accept a protocol object that has `search_read()`, `fields_get()`, `execute_kw()`

**Acceptance Criteria**:
- Introspects all default models
- Respects concurrency limit (semaphore)
- Respects time limit
- Gracefully handles models that don't exist or aren't accessible
- Tests with mocked protocol responses

---

## Task 3.4: Static Registry Generator

**Complexity**: Large

**Description**: Implement the AST-based static registry generator CLI tool.

**Spec References**: REQ-07-02, REQ-07-03, REQ-07-04, REQ-07-05, REQ-07-06, REQ-07-08

**Files to Create**:
- `odoo_mcp/registry/generator.py`
- `odoo_mcp/registry/static_data.py`
- `scripts/runtime_introspect.py`
- `tests/test_registry/test_generator.py`

**Implementation Details**:
1. CLI tool `odoo-mcp-registry` (REQ-07-03):
   - `--addons-path`: Comma-separated Odoo addon directories
   - `--output`: Output JSON file path (default: `odoo_mcp/registry/static_data.json`)
   - `--models`: Comma-separated model filter
   - `--version`: Odoo version label
2. AST parser (REQ-07-04):
   - **Model detection**: Find classes with `_name = '...'` or `_inherit = '...'`
   - **Field extraction**: Parse `fields.Char(...)`, `fields.Many2one(...)` etc. Extract parameters from AST keyword args (string, required, readonly, help, relation, selection)
   - **Method extraction**: Find methods named `action_*` or `button_*`. Extract first line of docstring.
   - **Inheritance resolution** (REQ-07-05):
     - Single: `_inherit = 'sale.order'` extends existing
     - Multiple: `_inherit = ['mail.thread', 'mail.activity.mixin']`
     - New model: `_name = 'my.model'` with `_inherit` for mixins
     - `_inherits` delegation inheritance
3. Static data file format (REQ-07-08):
   - JSON with: `version`, `generated_at`, `generator_version`, `source: "ast_parse"`, `models: {}`
   - Each model: `name`, `description`, `transient`, `fields`, `methods`, `states`, `parent_models`, `has_chatter`
4. `static_data.py`: Functions to load/parse the static JSON file
5. Runtime introspection script (REQ-07-06):
   - Standalone Python script for running inside Odoo shell
   - Iterates target models, reads `_fields`, scans `dir()` for methods
   - Outputs JSON between `=== RUNTIME_REGISTRY_JSON_START ===` and `=== RUNTIME_REGISTRY_JSON_END ===` markers
   - Default target models from REQ-07-07

**Acceptance Criteria**:
- `odoo-mcp-registry --addons-path ./addons --output registry.json` produces valid JSON
- AST parser correctly extracts models, fields, methods from real Odoo addon code
- Inheritance resolution works for all 4 patterns
- Runtime script produces parseable output
- Static data loader correctly deserializes JSON to Registry

---

## Task 3.5: Registry Merge Strategy

**Complexity**: Medium

**Description**: Implement the merge of static and dynamic registry data.

**Spec References**: REQ-07-14, REQ-07-15

**Files to Create**:
- Update `odoo_mcp/registry/model_registry.py` (add `merge()`)
- `tests/test_registry/test_merge.py`

**Implementation Details**:
1. Merge rules (REQ-07-14):
   - Start with static registry as base
   - For each model in dynamic:
     - If exists in static: merge fields (dynamic wins for conflicts)
     - If not in static: add entirely from dynamic
   - Methods: static preferred (richer AST data, docstrings). Dynamic adds newly discovered methods.
   - States: dynamic preferred (reflects live selection values)
2. Conflict logging (REQ-07-15):
   - Log at `debug` level:
     - "Registry merge: sale.order.new_field - added from dynamic (not in static)"
     - "Registry merge: sale.order.state - selection values updated from dynamic"
3. Set `build_mode = "merged"` on result

**Acceptance Criteria**:
- Dynamic fields override static fields
- Static methods preserved, dynamic methods added
- Dynamic state values override static
- New models from dynamic added
- Conflicts logged at debug level
- Tests cover all merge scenarios

---

## Task 3.6: URI Scheme Parser

**Complexity**: Small

**Description**: Implement the `odoo://` URI scheme parser for MCP resources.

**Spec References**: REQ-06-01, REQ-06-11

**Files to Create**:
- `odoo_mcp/resources/__init__.py`
- `odoo_mcp/resources/uri.py`
- `tests/test_resources/test_uri.py`

**Implementation Details**:
1. Parse `odoo://` URIs with this structure: `odoo://{category}/{path}`
2. Categories: `model/`, `record/`, `system/`, `config/`
3. URI patterns to support:
   - `odoo://system/info`
   - `odoo://system/modules`
   - `odoo://system/toolsets`
   - `odoo://config/safety`
   - `odoo://model/{model_name}/fields`
   - `odoo://model/{model_name}/methods`
   - `odoo://model/{model_name}/states`
   - `odoo://record/{model_name}/{record_id}`
   - `odoo://record/{model_name}?domain={domain}&limit={limit}`
4. Query parameter parsing for record listings:
   - `domain`: URL-encoded JSON
   - `limit`: integer (max 100, default 20) (REQ-06-12)
5. Return parsed `OdooUri` object with category, path segments, and query params

**Acceptance Criteria**:
- All documented URI patterns parse correctly
- Invalid URIs raise clear errors
- Query parameter parsing handles URL-encoded JSON domains
- Limit enforcement (max 100, default 20)

---

## Task 3.7: Resource Provider

**Complexity**: Large

**Description**: Implement all MCP resources (static and template-based).

**Spec References**: REQ-06-02 through REQ-06-16, REQ-06-22, REQ-06-23, REQ-07-20

**Files to Create**:
- `odoo_mcp/resources/provider.py`
- `tests/test_resources/test_provider.py`

**Implementation Details**:
1. `ResourceProvider` class that registers resources with the MCP server
2. **Static resources**:
   - `odoo://system/info` (REQ-06-02): Server version, database, URL, protocol, user, MCP version
   - `odoo://system/modules` (REQ-06-03): Installed modules list
   - `odoo://system/toolsets` (REQ-06-04): Registered toolsets and tools
   - `odoo://config/safety` (REQ-06-05): Current safety config (mode, allowlist, blocklist, rate limit)
3. **Resource templates**:
   - `odoo://model/{model_name}/fields` (REQ-06-06): Field definitions from registry (REQ-07-20)
   - `odoo://model/{model_name}/methods` (REQ-06-07): Available methods from registry (REQ-07-20)
   - `odoo://model/{model_name}/states` (REQ-06-08): State machine from registry (REQ-07-20)
   - `odoo://record/{model_name}/{record_id}` (REQ-06-09): Read a specific record. Key fields from registry, no binary fields, normalized format (REQ-06-10)
   - `odoo://record/{model_name}?domain=...&limit=...` (REQ-06-11): Search records. Max limit 100, default 20 (REQ-06-12)
4. **Resource subscriptions** (REQ-06-13 through REQ-06-16):
   - Support `resources/subscribe` for record and system info resources (REQ-06-15)
   - Change detection via polling (configurable interval, default 60s) using `write_date` (REQ-06-14)
   - Send `notifications/resources/updated` on change (REQ-06-13)
   - Max 50 active subscriptions per client (REQ-06-16)
5. **Access control** (REQ-06-22, REQ-06-23):
   - Respect model/field blocklists
   - Respect Odoo access control (return error, not empty, for unauthorized)
   - In readonly mode, only read resources available

**Acceptance Criteria**:
- All 4 static resources return correct data
- All 5 resource templates work with parameters
- Resource subscriptions detect changes via write_date polling
- Max 50 subscriptions enforced
- Blocklisted models/fields not accessible via resources
- Access errors return proper error, not empty

---

## Task 3.8: Prompt Provider

**Complexity**: Medium

**Description**: Implement all MCP prompt templates.

**Spec References**: REQ-06-17 through REQ-06-21

**Files to Create**:
- `odoo_mcp/prompts/__init__.py`
- `odoo_mcp/prompts/provider.py`

**Implementation Details**:
1. `PromptProvider` class that registers prompts with MCP server
2. **Static prompts**:
   - `odoo_overview` (REQ-06-17): System overview — version, edition, URL, database, user, available toolsets, tool count, key models, getting started guide
   - `odoo_domain_help` (REQ-06-18): Complete domain syntax reference from L2/04a — operators, polish notation, examples, date patterns, relational patterns, command tuples
3. **Parameterized prompts**:
   - `odoo_model_guide` (REQ-06-19): Context-aware model guide
     - Argument: `model_name` (required)
     - Response: fields (grouped by required/key/other), state machine, common operations, related models, tips
     - Generated dynamically from registry
   - `odoo_create_record` (REQ-06-20): Record creation guidance
     - Argument: `model_name` (required)
     - Response: required fields with types, default values, example values, relational field resolution guidance
   - `odoo_search_help` (REQ-06-21): Search query construction help
     - Arguments: `model_name` (required), `query` (required — natural language)
     - Response: suggested domain filter, recommended fields, tool call to execute

**Acceptance Criteria**:
- All 5 prompts registered with MCP server
- Static prompts include complete information per spec
- Parameterized prompts generate dynamic content from registry
- Domain help prompt includes all operators, examples, and command tuples

---

## Task 3.9: Registry & Resource Tests

**Complexity**: Medium

**Description**: Comprehensive tests for all registry and resource functionality.

**Files to Create/Update**:
- `tests/test_registry/test_model_registry.py`
- `tests/test_registry/test_merge.py`
- `tests/test_resources/test_provider.py`

**Implementation Details**:
1. Registry tests:
   - Test data model serialization/deserialization
   - Test all query methods (get_model, get_field, etc.)
   - Test model existence checking with caching
   - Test NO_KWARGS_METHODS lookup
   - Test dynamic introspection with mocked protocol
   - Test merge scenarios (conflicts, additions, overrides)
2. Resource tests:
   - Test URI parsing for all patterns
   - Test each static resource returns expected format
   - Test resource templates with parameters
   - Test subscription limit enforcement
   - Test access control (blocklist, permissions)
3. Prompt tests:
   - Test each prompt generates expected content structure
   - Test parameterized prompts with different models

**Acceptance Criteria**:
- >90% coverage for registry/, resources/, prompts/
- All tests pass without Odoo instance
- Mock protocol used for all dynamic operations
