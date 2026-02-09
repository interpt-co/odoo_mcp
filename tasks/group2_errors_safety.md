# Group 2: Error Handling & Safety Infrastructure

| Field | Value |
|-------|-------|
| Branch | `feat/errors-safety` |
| Focus | Error classification, pattern database, safety modes, rate limiting, audit logging |
| Spec Docs | SPEC-10, SPEC-11, L2/10a |
| Requirements | REQ-10-01 through REQ-10-19, REQ-10a-01 through REQ-10a-03, REQ-11-01 through REQ-11-24 |

## Files Owned

```
odoo_mcp/errors/__init__.py
odoo_mcp/errors/handler.py
odoo_mcp/errors/patterns.py
odoo_mcp/safety/__init__.py
odoo_mcp/safety/modes.py
odoo_mcp/safety/audit.py
odoo_mcp/safety/limits.py
tests/test_errors/__init__.py
tests/test_errors/test_handler.py
tests/test_errors/test_patterns.py
tests/test_safety/__init__.py
tests/test_safety/test_modes.py
tests/test_safety/test_audit.py
tests/test_safety/test_limits.py
```

## Interface Dependencies (from other groups, available after merge)

- **OdooRpcError** (Group 1): Exception with `error_class`, `traceback`, `model`, `method` attributes. Group 2 defines its own interface for this and connects at merge time.
- **OdooMcpConfig** (Group 1): Configuration fields for safety, rate limiting, audit. Group 2 defines its own `SafetyConfig` and `RateLimitConfig` models that match the same field names.

---

## Task 2.1: Error Data Models & Categories

**Complexity**: Small

**Description**: Define the error data models, error categories, and the structured error response format.

**Spec References**: REQ-10-01, REQ-10-02, REQ-10-03, REQ-10-04, REQ-10-15, REQ-10-16, REQ-10-17

**Files to Create**:
- `odoo_mcp/errors/__init__.py`

**Implementation Details**:
1. Define error category enum (REQ-10-01):
   ```python
   class ErrorCategory(str, Enum):
       VALIDATION = "validation"
       ACCESS = "access"
       NOT_FOUND = "not_found"
       CONSTRAINT = "constraint"
       STATE = "state"
       WIZARD = "wizard"
       CONNECTION = "connection"
       RATE_LIMIT = "rate_limit"
       CONFIGURATION = "configuration"
       UNKNOWN = "unknown"
   ```
2. Define `ErrorResponse` dataclass (REQ-10-02, REQ-10-03, REQ-10-04):
   - Required: `error=True`, `category`, `code`, `message`, `suggestion`, `retry`
   - Optional: `details` (dict), `original_error` (str)
3. Define error code constants matching each category (REQ-10-01 table)
4. Define retry guidance mapping (REQ-10-15):
   - `validation` -> retry=True
   - `access` -> retry=False
   - `not_found` -> retry=True
   - `constraint` -> retry=True
   - `state` -> retry=True
   - `wizard` -> retry=True
   - `connection` -> retry=True (include `retry_after`)
   - `rate_limit` -> retry=True (include `retry_after`)
   - `configuration` -> retry=False
   - `unknown` -> retry=False
5. Define MCP error code mapping (REQ-10-16):
   - `MethodNotFound` (-32601) -> unknown tool
   - `InvalidParams` (-32602) -> schema validation
   - `InternalError` (-32603) -> unhandled error
6. Helper to return errors as MCP tool results with `isError: true` (REQ-10-17)

**Acceptance Criteria**:
- All 10 error categories defined
- `ErrorResponse` serializes to the exact JSON format in spec
- Retry guidance is correct for each category

---

## Task 2.2: Error Pattern Database

**Complexity**: Large

**Description**: Implement the complete error pattern database with regex matching.

**Spec References**: REQ-10-11, REQ-10-12, REQ-10a-01, REQ-10a-02, REQ-10a-03

**Files to Create**:
- `odoo_mcp/errors/patterns.py`
- `tests/test_errors/test_patterns.py`

**Implementation Details**:
1. Define `ErrorPattern` dataclass (REQ-10a-01):
   - `id`: Unique pattern ID (e.g., "VAL-001")
   - `pattern`: Regex string
   - `error_class`: Optional Odoo exception class to narrow matching
   - `category`: Error category string
   - `code`: Error code string
   - `message_template`: Template with `{placeholders}`
   - `suggestion_template`: Template with `{placeholders}`
   - `extract_groups`: Dict mapping names to regex group references
2. Implement ALL patterns from L2/10a:
   **Validation patterns (VAL-001 through VAL-007)**:
   - VAL-001: Missing required fields
   - VAL-001b: Not-null constraint violation
   - VAL-002: Invalid field on model
   - VAL-003: Wrong value for field
   - VAL-004: Expected singleton
   - VAL-005: Invalid selection value
   - VAL-006: Type mismatch
   - VAL-007: Invalid integer literal

   **Access patterns (ACC-001 through ACC-004)**:
   - ACC-001: Access Denied
   - ACC-002: Operation not allowed
   - ACC-003: Record rule violation
   - ACC-004: Model access denied

   **Not found patterns (NF-001, NF-002)**:
   - NF-001: Record not found (MissingError)
   - NF-002: Model not found

   **Constraint patterns (CON-001 through CON-003)**:
   - CON-001: Unique violation
   - CON-002: Check constraint
   - CON-003: Foreign key violation

   **State patterns (ST-001 through ST-003)**:
   - ST-001: Invalid state transition
   - ST-002: Draft required
   - ST-003: Already processed

   **Business logic patterns (BIZ-001 through BIZ-005)**:
   - BIZ-001: Missing accounting config
   - BIZ-002: Insufficient stock
   - BIZ-003: Missing lines
   - BIZ-004: Already reconciled
   - BIZ-005: Cannot delete processed record

   **Connection patterns (CONN-001 through CONN-003)**:
   - CONN-001: Connection refused
   - CONN-002: Timeout
   - CONN-003: Session expired

3. Store as `ERROR_PATTERNS: list[ErrorPattern]` ordered by specificity (most specific first)
4. Patterns MUST be extensible (REQ-10-12, REQ-10a-03): appending to `ERROR_PATTERNS` adds new patterns without modifying classifier

**Acceptance Criteria**:
- All 25+ patterns from L2/10a implemented
- Regex patterns compile without errors
- Each pattern has correct category, code, and templates
- Patterns are ordered by specificity
- Tests verify each pattern matches its intended error string

---

## Task 2.3: Error Classification Handler

**Complexity**: Large

**Description**: Implement the main error classifier that translates raw Odoo errors into LLM-friendly responses.

**Spec References**: REQ-10-05, REQ-10-06, REQ-10-07, REQ-10-08, REQ-10-09, REQ-10-10, REQ-10-13, REQ-10-14, REQ-10-18, REQ-10-19

**Files to Create**:
- `odoo_mcp/errors/handler.py`
- `tests/test_errors/test_handler.py`

**Implementation Details**:
1. `ErrorHandler` class with `classify()` method (REQ-10a-02):
   ```python
   def classify(
       error_message: str,
       error_class: str | None = None,
       model: str | None = None,
       method: str | None = None,
   ) -> ErrorResponse
   ```
2. Pattern matching order (REQ-10a-02):
   a. Match by `error_class` first (narrowest)
   b. Then match by `pattern` regex against message
   c. First matching pattern wins
   d. Fallback classification if no pattern matches
3. XML-RPC error classification rules (REQ-10-05):
   - Parse `xmlrpc.client.Fault` faultCode and faultString
   - Map faultString patterns to categories per spec table
4. JSON-RPC/JSON-2 error classification (REQ-10-07):
   - Parse `data.name` field for exception class
   - Map exception classes to categories per spec table
5. HTTP/network error classification (REQ-10-08):
   - `httpx.ConnectError` -> connection/CONNECTION_REFUSED
   - `httpx.TimeoutException` -> connection/TIMEOUT
   - HTTP 401/403 -> access/SESSION_EXPIRED
   - HTTP 404 -> connection/ENDPOINT_NOT_FOUND
   - HTTP 429 -> rate_limit/RATE_LIMITED
   - HTTP 500+ -> connection/SERVER_ERROR
6. Structured info extraction from fault strings (REQ-10-06):
   - Parse exception class name
   - Extract error message after class name
   - Extract field name if referenced
   - Extract model name if referenced
7. Suggestion generation (REQ-10-09, REQ-10-10):
   - Validation: field-specific help, type-specific guidance
   - State: current state info, valid transitions
   - Constraint: uniqueness guidance, FK guidance
   - Access: permission info
   - ALL suggestions reference specific tool names (REQ-10-10)
8. Traceback translation (REQ-10-13, REQ-10-14):
   - Extract final exception line from traceback
   - Extract exception class and message
   - Discard full traceback from LLM-facing response
   - Store full traceback in `original_error` for debugging
   - NEVER include full tracebacks in tool responses
9. Logging (REQ-10-18, REQ-10-19):
   - `warning` level: validation, state, not_found
   - `error` level: access, connection, unknown
   - `debug` level: full traceback/original error
   - Include: model, method, sanitized args, error code

**Acceptance Criteria**:
- Classifies all XML-RPC error patterns correctly
- Classifies all JSON-RPC/JSON-2 error patterns correctly
- Classifies HTTP/network errors correctly
- Suggestions always reference specific tool names
- Tracebacks never leak to LLM-facing responses
- Logging levels are correct per category
- Tests cover all major error classification paths

---

## Task 2.4: Safety Mode Enforcement

**Complexity**: Medium

**Description**: Implement the three operation modes and model/field/method filtering.

**Spec References**: REQ-11-01 through REQ-11-16

**Files to Create**:
- `odoo_mcp/safety/__init__.py`
- `odoo_mcp/safety/modes.py`
- `tests/test_safety/test_modes.py`

**Implementation Details**:
1. Define `OperationMode` enum: `readonly`, `restricted`, `full` (REQ-11-01)
2. Define `SafetyConfig` dataclass:
   - `mode: OperationMode`
   - `model_allowlist: list[str]`
   - `model_blocklist: list[str]`
   - `write_allowlist: list[str]`
   - `field_blocklist: list[str]`
   - `method_blocklist: list[str]`
3. `enforce_mode()` function (REQ-11-03):
   ```python
   async def enforce_mode(mode, operation, model, config) -> None:
       # readonly: reject all non-read operations
       # restricted: create/write/execute only on write_allowlist; unlink always rejected
       # full: all operations allowed (subject to model filtering)
   ```
4. Tool visibility by mode (REQ-11-04, REQ-11-05):
   - Define `get_tool_visibility(tool_name, mode)` -> bool
   - "Hidden" tools NOT registered with MCP server
   - Visibility table matching spec exactly
5. Model filtering (REQ-11-06 through REQ-11-09):
   - Allowlist: if non-empty, ONLY listed models accessible
   - Blocklist: listed models NEVER accessible
   - Default blocklist always applied (REQ-11-08):
     `ir.config_parameter`, `ir.cron`, `base.automation`, `ir.rule`, `ir.model.access`, `res.users` (write-blocked), `ir.mail_server`, `fetchmail.server`, `payment.provider`
   - `res.users` special case: read allowed, write blocked unless overridden (REQ-11-09)
   - `validate_model_access(model, operation)` -> bool
6. Field filtering (REQ-11-12 through REQ-11-14):
   - Default field blocklist: `password`, `password_crypt`, `oauth_access_token`, `oauth_provider_id`, `api_key`, `api_key_ids`, `totp_secret`, `totp_enabled`, `signature`
   - Blocked fields: removed from fields_get, search_read, read results
   - Blocked fields: rejected in create/write values
   - `filter_fields(fields, model, operation)` -> filtered fields
7. Method filtering (REQ-11-15, REQ-11-16):
   - Default method blocklist: `sudo`, `with_user`, `with_env`, `with_context`, `invalidate_cache`, `clear_caches`, `init`, `uninstall`, `module_uninstall`
   - `validate_method(method_name)` -> bool

**Acceptance Criteria**:
- All three modes enforce correct restrictions
- Default blocklists are always applied
- `res.users` special case works correctly
- Field filtering works for both read and write operations
- Method blocklist prevents dangerous method calls
- Tests cover all mode/operation combinations

---

## Task 2.5: Tool Annotations Framework

**Complexity**: Small

**Description**: Implement the MCP tool annotations system.

**Spec References**: REQ-03-13, REQ-03-14, REQ-11-17, REQ-11-18

**Files to Create**:
- Update `odoo_mcp/safety/modes.py` (add annotations section)

**Implementation Details**:
1. Define tool annotations dataclass matching MCP spec (REQ-11-17):
   ```python
   @dataclass
   class ToolAnnotation:
       title: str
       readOnlyHint: bool = False
       destructiveHint: bool = False
       idempotentHint: bool = False
       openWorldHint: bool = True
   ```
2. Define the complete annotation registry (REQ-11-18):
   - All read tools: `readOnlyHint=True, destructiveHint=False, idempotentHint=True`
   - Create: `readOnlyHint=False, destructiveHint=False, idempotentHint=False`
   - Write: `readOnlyHint=False, destructiveHint=False, idempotentHint=True`
   - Unlink: `readOnlyHint=False, destructiveHint=True, idempotentHint=True`
   - Execute: `readOnlyHint=False, destructiveHint=False, idempotentHint=False`
   - Workflow creates/confirms/cancels as per spec table
   - All tools: `openWorldHint=True`
3. `get_annotation(tool_name)` lookup function
4. Annotations are accurate per REQ-03-14

**Acceptance Criteria**:
- Every tool in the spec has a defined annotation
- Annotation values match the spec table exactly
- Lookup function works for all tool names

---

## Task 2.6: Rate Limiting

**Complexity**: Medium

**Description**: Implement per-session rate limiting.

**Spec References**: REQ-11-19, REQ-11-20, REQ-11-21

**Files to Create**:
- `odoo_mcp/safety/limits.py`
- `tests/test_safety/test_limits.py`

**Implementation Details**:
1. `RateLimiter` class:
   - Configurable: `calls_per_minute`, `calls_per_hour`, `burst`
   - Per-client (per MCP session) tracking (REQ-11-20)
   - Sliding window implementation
2. Configuration (REQ-11-19):
   - `enabled: bool` (default: False)
   - `calls_per_minute: int` (default: 60)
   - `calls_per_hour: int` (default: 1000)
   - `burst: int` (default: 10)
3. Separate limits for read vs write (REQ-11-21):
   - `read_calls_per_minute: int` (default: 120)
   - `write_calls_per_minute: int` (default: 30)
4. `check_rate_limit(operation_type: str) -> None`:
   - Raises `RateLimitError` with `retry_after` seconds when exceeded
5. Rate limit error returns `RATE_LIMITED` code with `retry_after` field

**Acceptance Criteria**:
- Per-minute and per-hour limits work
- Burst allowance works
- Separate read/write limits work
- Returns `retry_after` in seconds when exceeded
- Thread-safe for concurrent requests

---

## Task 2.7: Audit Logging

**Complexity**: Medium

**Description**: Implement the audit logging system for tool invocations.

**Spec References**: REQ-11-22, REQ-11-23, REQ-11-24

**Files to Create**:
- `odoo_mcp/safety/audit.py`
- `tests/test_safety/test_audit.py`

**Implementation Details**:
1. `AuditLogger` class:
   - Configurable (REQ-11-22):
     - `enabled: bool`
     - `log_file: str | None` (path to JSONL file)
     - `log_reads: bool` (default: False)
     - `log_writes: bool` (default: True)
     - `log_deletes: bool` (default: True)
2. Each entry is a JSON line (REQ-11-23):
   ```json
   {
     "timestamp": "ISO 8601",
     "session_id": "abc123",
     "tool": "odoo_core_create",
     "model": "sale.order",
     "operation": "create",
     "values": {"partner_id": 1},
     "result_id": 42,
     "success": true,
     "duration_ms": 150,
     "odoo_uid": 2
   }
   ```
3. Data sanitization (REQ-11-24):
   - NEVER log passwords or API keys
   - NEVER log binary field content (log field names only)
   - For read operations: log domain/IDs only, not full record data
4. `log_operation()` method:
   ```python
   async def log_operation(
       tool: str, model: str, operation: str,
       values: dict | None, result: Any,
       success: bool, duration_ms: int,
       session_id: str, odoo_uid: int,
   ) -> None
   ```
5. File rotation: basic support (or document that logrotate should be used externally)
6. Async file writing (non-blocking)

**Acceptance Criteria**:
- JSONL output matches spec format
- Sensitive data is never logged
- Read operations only logged when `log_reads=True`
- File writing is non-blocking
- Binary field content filtered out

---

## Task 2.8: Integration Tests for Error & Safety Modules

**Complexity**: Medium

**Description**: Write comprehensive tests for all error handling and safety components.

**Files to Create/Update**:
- `tests/test_errors/test_handler.py` (expand)
- `tests/test_errors/test_patterns.py` (expand)
- `tests/test_safety/test_modes.py` (expand)

**Implementation Details**:
1. Error handler tests:
   - Test classification of real Odoo error strings for each category
   - Test XML-RPC fault parsing
   - Test JSON-RPC error parsing
   - Test HTTP error classification
   - Test traceback extraction
   - Test suggestion generation references tool names
2. Pattern database tests:
   - Test each pattern against sample error messages
   - Test pattern priority (specific wins over general)
   - Test group extraction for each pattern
   - Test fallback when no pattern matches
3. Safety mode tests:
   - Test all mode/operation/model combinations
   - Test allowlist and blocklist interactions
   - Test default blocklist always applied
   - Test `res.users` special case
   - Test field filtering for read and write
   - Test method blocklist

**Acceptance Criteria**:
- >90% code coverage for errors/ and safety/ modules
- All edge cases documented in tests
- Tests run without any Odoo instance
