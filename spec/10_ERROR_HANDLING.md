# 10 — Error Handling

| Field        | Value                              |
|-------------|-------------------------------------|
| Document ID | SPEC-10                             |
| Title       | Error Handling                       |
| Status      | Draft                               |
| Depends On  | SPEC-02, SPEC-04                    |
| Referenced By | —                                  |
| Sub-Specs   | L2/10a (Error Patterns)             |

---

## 1. Overview

Raw Odoo error messages and Python tracebacks are cryptic and useless to LLMs. This document specifies how the MCP server catches, classifies, and translates Odoo errors into structured, LLM-friendly responses that help the LLM understand what went wrong and how to fix it.

---

## 2. Error Classification

**REQ-10-01**: All errors MUST be classified into one of these categories:

| Category | Code | Description | Typical LLM Action |
|----------|------|-------------|---------------------|
| `validation` | `VALIDATION_ERROR` | Missing required fields, invalid values, constraint violations | Fix the input values and retry |
| `access` | `ACCESS_DENIED` | Insufficient permissions, wrong credentials | Report to user, do not retry |
| `not_found` | `NOT_FOUND` | Record or model does not exist | Check the ID or model name |
| `constraint` | `CONSTRAINT_ERROR` | Database constraint violation (unique, check, foreign key) | Fix the conflicting value |
| `state` | `STATE_ERROR` | Invalid state transition (e.g., confirming a cancelled order) | Check current state first |
| `wizard` | `WIZARD_REQUIRED` | Operation requires a wizard interaction | Follow wizard protocol |
| `connection` | `CONNECTION_ERROR` | Network, timeout, or session errors | Wait and retry |
| `rate_limit` | `RATE_LIMITED` | Too many requests | Wait and retry after delay |
| `configuration` | `CONFIG_ERROR` | Server misconfiguration | Report to user |
| `unknown` | `UNKNOWN_ERROR` | Unclassified error | Report to user |

---

## 3. LLM-Friendly Error Format

**REQ-10-02**: Every error response MUST follow this structure:

```json
{
  "error": true,
  "category": "validation",
  "code": "VALIDATION_ERROR",
  "message": "Required field 'partner_id' is missing on sale.order",
  "details": {
    "model": "sale.order",
    "field": "partner_id",
    "field_label": "Customer",
    "field_type": "many2one",
    "field_relation": "res.partner"
  },
  "suggestion": "Include 'partner_id' in the values. Search for the customer first: odoo_core_search_read with model='res.partner' and domain=[['name', 'ilike', '<customer name>']]",
  "retry": true,
  "original_error": "odoo.exceptions.ValidationError: Missing required fields: partner_id"
}
```

**REQ-10-03**: Required fields in every error response:
- `error`: always `true`
- `category`: error classification (from REQ-10-01)
- `code`: machine-readable error code
- `message`: concise, human/LLM-readable description
- `suggestion`: actionable guidance for the LLM on how to resolve the error
- `retry`: boolean indicating if the operation can be retried (after fixing the issue)

**REQ-10-04**: Optional fields:
- `details`: structured data about the error context (model, field, current state, etc.)
- `original_error`: raw Odoo error string (for debugging, not for LLM consumption)

---

## 4. Error Classification Rules

### 4.1 XML-RPC Errors

**REQ-10-05**: XML-RPC errors arrive as `xmlrpc.client.Fault` exceptions. Classification:

| Fault Pattern | Category | Code |
|--------------|----------|------|
| `faultCode` contains "Access Denied" | `access` | `ACCESS_DENIED` |
| `faultString` contains "ValidationError" | `validation` | `VALIDATION_ERROR` |
| `faultString` contains "MissingError" | `not_found` | `NOT_FOUND` |
| `faultString` contains "UserError" | `validation` | `USER_ERROR` |
| `faultString` contains "AccessError" | `access` | `ACCESS_DENIED` |
| `faultString` contains "unique" or "duplicate" | `constraint` | `UNIQUE_VIOLATION` |
| `faultString` contains "check constraint" | `constraint` | `CHECK_CONSTRAINT` |
| `faultString` contains "foreign key" | `constraint` | `FK_VIOLATION` |
| `faultString` contains "ir.actions" | `wizard` | `WIZARD_REQUIRED` |
| Any `xmlrpc.client.ProtocolError` | `connection` | `CONNECTION_ERROR` |
| Any other `Fault` | `unknown` | `UNKNOWN_ERROR` |

**REQ-10-06**: The classifier MUST extract structured information from the fault string:
1. Parse the error class name (e.g., `odoo.exceptions.ValidationError`).
2. Extract the error message (text after the exception class).
3. If the message references a field name, extract it.
4. If the message references a model name, extract it.

### 4.2 JSON-2 Errors

**REQ-10-07**: JSON-2 errors arrive as JSON-RPC error responses:

```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": 200,
    "message": "Odoo Server Error",
    "data": {
      "name": "odoo.exceptions.ValidationError",
      "debug": "Traceback (most recent call last):\n...",
      "message": "Required field 'name' is missing.",
      "arguments": ["Required field 'name' is missing."],
      "context": {}
    }
  }
}
```

Classification uses the `data.name` field:

| `data.name` | Category | Code |
|-------------|----------|------|
| `odoo.exceptions.ValidationError` | `validation` | `VALIDATION_ERROR` |
| `odoo.exceptions.UserError` | `validation` | `USER_ERROR` |
| `odoo.exceptions.AccessError` | `access` | `ACCESS_DENIED` |
| `odoo.exceptions.MissingError` | `not_found` | `NOT_FOUND` |
| `odoo.exceptions.AccessDenied` | `access` | `ACCESS_DENIED` |
| `odoo.exceptions.RedirectWarning` | `validation` | `REDIRECT_WARNING` |
| `builtins.ValueError` | `validation` | `VALUE_ERROR` |
| `psycopg2.errors.UniqueViolation` | `constraint` | `UNIQUE_VIOLATION` |
| `psycopg2.errors.CheckViolation` | `constraint` | `CHECK_CONSTRAINT` |
| `psycopg2.errors.ForeignKeyViolation` | `constraint` | `FK_VIOLATION` |

### 4.3 HTTP/Network Errors

**REQ-10-08**: Network-level errors:

| Error | Category | Code |
|-------|----------|------|
| `httpx.ConnectError` | `connection` | `CONNECTION_REFUSED` |
| `httpx.TimeoutException` | `connection` | `TIMEOUT` |
| HTTP 401/403 | `access` | `SESSION_EXPIRED` |
| HTTP 404 | `connection` | `ENDPOINT_NOT_FOUND` |
| HTTP 429 | `rate_limit` | `RATE_LIMITED` |
| HTTP 500+ | `connection` | `SERVER_ERROR` |

---

## 5. Suggestion Generation

**REQ-10-09**: The error handler MUST generate actionable suggestions based on the error category and context:

### 5.1 Validation Errors

| Pattern | Suggestion |
|---------|-----------|
| Missing required field `X` | "Include '{X}' in the values. {field_type_help}" |
| Invalid value for selection field `X` | "Valid values for '{X}' are: {selection_values}" |
| Invalid date format | "Use format YYYY-MM-DD for dates, YYYY-MM-DD HH:MM:SS for datetimes" |
| Invalid many2one value | "'{field}' expects an integer (record ID). Search for the record first." |

### 5.2 State Errors

| Pattern | Suggestion |
|---------|-----------|
| Cannot confirm draft | "The record is in state '{current_state}'. {valid_transitions}" |
| Cannot modify posted record | "The record is posted. Reset to draft first with action_draft, then modify." |

### 5.3 Constraint Errors

| Pattern | Suggestion |
|---------|-----------|
| Unique violation on field `X` | "A record with this '{X}' already exists. Use a different value or search for the existing record." |
| Foreign key violation | "The referenced record does not exist. Verify the ID is correct." |

### 5.4 Access Errors

| Pattern | Suggestion |
|---------|-----------|
| No read access to model | "The current user does not have read access to '{model}'. This requires specific Odoo permissions." |
| Record rule prevented access | "Access to this specific record is restricted by Odoo security rules." |

**REQ-10-10**: Suggestions MUST reference specific tool names when recommending actions:
- "Use `odoo_core_search_read` to find the record"
- "Use `odoo_core_fields_get` to see valid field values"
- "Use `odoo_core_execute` with method 'action_draft' to reset the state"

---

## 6. Error Pattern Database

**REQ-10-11**: The error handler MUST maintain a pattern database that maps known Odoo error strings to structured responses. See SPEC-L2/10a for the complete database.

**REQ-10-12**: The pattern database MUST be extensible — new patterns can be added without modifying core error handling code:

```python
@dataclass
class ErrorPattern:
    pattern: str                    # Regex pattern to match against error message
    category: str                   # Error category
    code: str                       # Error code
    message_template: str           # Template with {placeholders} for extracted groups
    suggestion_template: str        # Suggestion template
    extract_fields: dict[str, int]  # Named regex group → group index mapping

ERROR_PATTERNS: list[ErrorPattern] = [
    ErrorPattern(
        pattern=r"Missing required fields?[:\s]+(['\w,\s]+)",
        category="validation",
        code="MISSING_REQUIRED_FIELD",
        message_template="Required field(s) {fields} missing on {model}",
        suggestion_template="Include {fields} in the values. Use odoo_core_fields_get to see field details.",
        extract_fields={"fields": 1},
    ),
    # ... more patterns in L2/10a
]
```

---

## 7. Traceback Translation

**REQ-10-13**: When the raw error includes a Python traceback (common in XML-RPC `faultString` and JSON-2 `debug` field), the error handler MUST:

1. Extract the final exception line (last line of the traceback).
2. Extract the exception class and message.
3. Discard the full traceback from the LLM-facing response (it's noise).
4. Store the full traceback in `original_error` for debugging.

**REQ-10-14**: The server MUST NOT include full Python tracebacks in tool responses to MCP clients. Only the classified error with suggestion is returned.

---

## 8. Retry Guidance

**REQ-10-15**: The `retry` field MUST be set according to:

| Category | Retry | Guidance |
|----------|-------|----------|
| `validation` | `true` | After fixing the input |
| `access` | `false` | Cannot be fixed by the LLM |
| `not_found` | `true` | After verifying the ID/model |
| `constraint` | `true` | After changing the conflicting value |
| `state` | `true` | After transitioning to the correct state |
| `wizard` | `true` | After completing the wizard |
| `connection` | `true` | After waiting (include `retry_after` in seconds) |
| `rate_limit` | `true` | After waiting (include `retry_after` in seconds) |
| `configuration` | `false` | Requires human intervention |
| `unknown` | `false` | Cannot determine |

---

## 9. MCP Error Codes

**REQ-10-16**: When returning errors through MCP's tool error mechanism, the server MUST use appropriate MCP error codes:

| MCP Error Code | When Used |
|---------------|-----------|
| `MethodNotFound` (-32601) | Unknown tool name |
| `InvalidParams` (-32602) | Invalid tool parameters (schema validation) |
| `InternalError` (-32603) | Unhandled server error |

**REQ-10-17**: For Odoo-specific errors (validation, access, etc.), the server MUST return them as **tool results with `isError: true`**, NOT as MCP protocol errors. This allows the LLM to see the structured error response and act on it:

```python
# In the tool handler:
try:
    result = await execute_odoo_operation(...)
    return result
except OdooError as e:
    error_response = error_handler.classify(e)
    return CallToolResult(
        content=[TextContent(text=json.dumps(error_response))],
        isError=True,
    )
```

---

## 10. Logging

**REQ-10-18**: All errors MUST be logged with:
- `warning` level for validation/state/not_found errors (user-recoverable).
- `error` level for access/connection/unknown errors (may require intervention).
- `debug` level for the full traceback/original error.

**REQ-10-19**: Error logs MUST include the operation context: model, method, args (sanitized — no passwords), and the classified error code.
