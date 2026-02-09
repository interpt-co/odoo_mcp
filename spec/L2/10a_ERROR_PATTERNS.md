# L2/10a — Error Pattern Database

| Field        | Value                              |
|-------------|-------------------------------------|
| Document ID | SPEC-L2-10a                         |
| Title       | Error Pattern Database               |
| Status      | Draft                               |
| Parent      | SPEC-10 (Error Handling)            |

---

## 1. Overview

This document contains the complete error pattern database — a mapping of known Odoo error messages to structured, LLM-friendly responses. Each pattern includes a regex for matching, an error classification, a message template, and an actionable suggestion.

---

## 2. Pattern Format

**REQ-10a-01**: Each error pattern follows this structure:

```python
@dataclass
class ErrorPattern:
    id: str                         # Unique pattern ID (e.g., "VAL-001")
    pattern: str                    # Regex to match against error message
    error_class: str | None         # Odoo exception class to match (optional, narrows matching)
    category: str                   # Error category (from SPEC-10 REQ-10-01)
    code: str                       # Error code
    message_template: str           # Message template with {placeholders}
    suggestion_template: str        # Suggestion template with {placeholders}
    extract_groups: dict[str, str]  # Named regex groups to extract
```

---

## 3. Validation Error Patterns

### 3.1 Missing Required Fields

```python
ErrorPattern(
    id="VAL-001",
    pattern=r"(?:Missing required|Required) fields?[:\s]*['\"]?(\w+(?:\.\w+)?)['\"]?",
    error_class="odoo.exceptions.ValidationError",
    category="validation",
    code="MISSING_REQUIRED_FIELD",
    message_template="Required field '{field}' is missing",
    suggestion_template="Include '{field}' in the values. Use odoo_core_fields_get with model='{model}' to see field details and requirements.",
    extract_groups={"field": "group1"},
)

ErrorPattern(
    id="VAL-001b",
    pattern=r"null value in column \"(\w+)\".*violates not-null constraint",
    error_class=None,
    category="validation",
    code="MISSING_REQUIRED_FIELD",
    message_template="Required field '{field}' cannot be empty (database constraint)",
    suggestion_template="Include a value for '{field}'. This field is required at the database level.",
    extract_groups={"field": "group1"},
)
```

### 3.2 Invalid Field Values

```python
ErrorPattern(
    id="VAL-002",
    pattern=r"Invalid field '(\w+)' on model '([\w.]+)'",
    error_class=None,
    category="validation",
    code="INVALID_FIELD",
    message_template="Field '{field}' does not exist on model '{model}'",
    suggestion_template="Use odoo_core_fields_get with model='{model}' to see available fields. The field '{field}' may be misspelled or not available in this Odoo version.",
    extract_groups={"field": "group1", "model": "group2"},
)

ErrorPattern(
    id="VAL-003",
    pattern=r"Wrong value for (\w+):\s*'([^']*)'",
    error_class="odoo.exceptions.ValidationError",
    category="validation",
    code="WRONG_VALUE",
    message_template="Invalid value '{value}' for field '{field}'",
    suggestion_template="Check the valid values for '{field}'. Use odoo_core_fields_get to see the field type and constraints.",
    extract_groups={"field": "group1", "value": "group2"},
)

ErrorPattern(
    id="VAL-004",
    pattern=r"Expected singleton.*got (\d+) records",
    error_class="ValueError",
    category="validation",
    code="SINGLETON_EXPECTED",
    message_template="Expected a single record but got {count} records",
    suggestion_template="The operation expects exactly one record. Narrow your selection to a single record ID.",
    extract_groups={"count": "group1"},
)
```

### 3.3 Selection Field Errors

```python
ErrorPattern(
    id="VAL-005",
    pattern=r"Selection '(\w+)' invalid for field '(\w+)' on model '([\w.]+)'",
    error_class=None,
    category="validation",
    code="INVALID_SELECTION",
    message_template="Value '{value}' is not valid for selection field '{field}' on {model}",
    suggestion_template="Use odoo_core_fields_get with model='{model}' to see valid selection values for '{field}'.",
    extract_groups={"value": "group1", "field": "group2", "model": "group3"},
)
```

### 3.4 Type Errors

```python
ErrorPattern(
    id="VAL-006",
    pattern=r"(?:expected|Expected)\s+(\w+).*?(?:got|received)\s+(\w+)",
    error_class="TypeError",
    category="validation",
    code="TYPE_MISMATCH",
    message_template="Type mismatch: expected {expected_type}, got {actual_type}",
    suggestion_template="Check the field type. Many2one fields expect an integer (record ID), not a string or list.",
    extract_groups={"expected_type": "group1", "actual_type": "group2"},
)

ErrorPattern(
    id="VAL-007",
    pattern=r"Invalid literal for int\(\) with base 10: '([^']*)'",
    error_class="ValueError",
    category="validation",
    code="INVALID_INTEGER",
    message_template="Cannot convert '{value}' to integer",
    suggestion_template="The field expects an integer value. If this is a Many2one field, use the record's integer ID, not its name.",
    extract_groups={"value": "group1"},
)
```

---

## 4. Access Error Patterns

```python
ErrorPattern(
    id="ACC-001",
    pattern=r"Access Denied",
    error_class="odoo.exceptions.AccessDenied",
    category="access",
    code="ACCESS_DENIED",
    message_template="Access denied. Authentication credentials are invalid or expired.",
    suggestion_template="Check the username and password/API key. The session may have expired.",
    extract_groups={},
)

ErrorPattern(
    id="ACC-002",
    pattern=r"(?:You are not allowed to|Sorry, you are not allowed to)\s+(\w+)\s+(?:this|this type of|the)\s+([\w. ]+)",
    error_class="odoo.exceptions.AccessError",
    category="access",
    code="OPERATION_NOT_ALLOWED",
    message_template="You do not have permission to {operation} on {resource}",
    suggestion_template="The current user lacks the required Odoo permissions for this operation. Contact an administrator to grant the necessary access rights.",
    extract_groups={"operation": "group1", "resource": "group2"},
)

ErrorPattern(
    id="ACC-003",
    pattern=r"Record rule.*prevented.*?([\w.]+)",
    error_class="odoo.exceptions.AccessError",
    category="access",
    code="RECORD_RULE_VIOLATION",
    message_template="Access to this record is restricted by security rules on {model}",
    suggestion_template="The current user cannot access this specific record due to Odoo record rules. Try accessing a different record or contact an administrator.",
    extract_groups={"model": "group1"},
)

ErrorPattern(
    id="ACC-004",
    pattern=r"Access to model '([\w.]+)' is not allowed",
    error_class="odoo.exceptions.AccessError",
    category="access",
    code="MODEL_ACCESS_DENIED",
    message_template="No access to model '{model}'",
    suggestion_template="The current user does not have access to the '{model}' model. This model may require specific Odoo groups/permissions.",
    extract_groups={"model": "group1"},
)
```

---

## 5. Not Found Error Patterns

```python
ErrorPattern(
    id="NF-001",
    pattern=r"Record does not exist or has been deleted.*?([\w.]+)\((\d+(?:,\s*\d+)*)\)",
    error_class="odoo.exceptions.MissingError",
    category="not_found",
    code="RECORD_NOT_FOUND",
    message_template="Record(s) {ids} not found in model {model}",
    suggestion_template="The record(s) with ID(s) {ids} do not exist in '{model}'. They may have been deleted. Use odoo_core_search_read to find valid records.",
    extract_groups={"model": "group1", "ids": "group2"},
)

ErrorPattern(
    id="NF-002",
    pattern=r"(?:does not exist|doesn't exist|unknown model)[:\s]*'?([\w.]+)'?",
    error_class=None,
    category="not_found",
    code="MODEL_NOT_FOUND",
    message_template="Model '{model}' does not exist",
    suggestion_template="The model '{model}' is not available. It may require a module that isn't installed. Use odoo_core_list_models to see available models.",
    extract_groups={"model": "group1"},
)
```

---

## 6. Constraint Error Patterns

```python
ErrorPattern(
    id="CON-001",
    pattern=r"duplicate key value violates unique constraint \"(\w+)\".*?Key \((\w+)\)=\(([^)]+)\)",
    error_class="psycopg2.errors.UniqueViolation",
    category="constraint",
    code="UNIQUE_VIOLATION",
    message_template="A record with {field}='{value}' already exists (constraint: {constraint})",
    suggestion_template="A record with this value already exists. Either use a different value or search for the existing record using odoo_core_search_read.",
    extract_groups={"constraint": "group1", "field": "group2", "value": "group3"},
)

ErrorPattern(
    id="CON-002",
    pattern=r"check constraint \"(\w+)\".*?violat",
    error_class="psycopg2.errors.CheckViolation",
    category="constraint",
    code="CHECK_CONSTRAINT",
    message_template="Value violates check constraint '{constraint}'",
    suggestion_template="The value doesn't meet the database constraint '{constraint}'. Check the valid range of values for the field.",
    extract_groups={"constraint": "group1"},
)

ErrorPattern(
    id="CON-003",
    pattern=r"foreign key constraint \"(\w+)\".*?referenced.*?\"(\w+)\"",
    error_class="psycopg2.errors.ForeignKeyViolation",
    category="constraint",
    code="FK_VIOLATION",
    message_template="Foreign key constraint violation: referenced record in '{table}' not found",
    suggestion_template="The referenced record does not exist. Verify the ID is correct by searching in the related model.",
    extract_groups={"constraint": "group1", "table": "group2"},
)
```

---

## 7. State Error Patterns

```python
ErrorPattern(
    id="ST-001",
    pattern=r"(?:Cannot|can't|unable to)\s+(\w+).*?(?:in state|state)\s+'(\w+)'",
    error_class="odoo.exceptions.UserError",
    category="state",
    code="INVALID_STATE_TRANSITION",
    message_template="Cannot {action} when record is in state '{state}'",
    suggestion_template="The record is currently in state '{state}'. Check the valid state transitions using odoo://model/{model}/states resource.",
    extract_groups={"action": "group1", "state": "group2"},
)

ErrorPattern(
    id="ST-002",
    pattern=r"(?:Only|only)\s+(?:draft|quotation).*?can be (\w+)",
    error_class="odoo.exceptions.UserError",
    category="state",
    code="DRAFT_REQUIRED",
    message_template="Record must be in draft state to {action}",
    suggestion_template="Reset the record to draft first using odoo_core_execute with method='action_draft', then retry the operation.",
    extract_groups={"action": "group1"},
)

ErrorPattern(
    id="ST-003",
    pattern=r"(?:already|has been)\s+(?:confirmed|validated|posted|cancelled|done|locked)",
    error_class="odoo.exceptions.UserError",
    category="state",
    code="ALREADY_PROCESSED",
    message_template="The record has already been processed",
    suggestion_template="This operation has already been completed. Read the current record state to confirm.",
    extract_groups={},
)
```

---

## 8. User Error Patterns (Business Logic)

```python
ErrorPattern(
    id="BIZ-001",
    pattern=r"(?:No|no)\s+(?:account|journal).*?(?:configured|defined|found)",
    error_class="odoo.exceptions.UserError",
    category="validation",
    code="MISSING_ACCOUNTING_CONFIG",
    message_template="Missing accounting configuration",
    suggestion_template="The Odoo instance needs accounting configuration. An administrator should configure default accounts and journals in the Invoicing settings.",
    extract_groups={},
)

ErrorPattern(
    id="BIZ-002",
    pattern=r"(?:not enough|insufficient)\s+(?:stock|quantity|qty)",
    error_class="odoo.exceptions.UserError",
    category="validation",
    code="INSUFFICIENT_STOCK",
    message_template="Insufficient stock for this operation",
    suggestion_template="Check available stock with odoo_inventory_get_stock before attempting this operation.",
    extract_groups={},
)

ErrorPattern(
    id="BIZ-003",
    pattern=r"(?:order|invoice|picking).*?(?:has no|without any)\s+(?:lines?|items?)",
    error_class="odoo.exceptions.UserError",
    category="validation",
    code="MISSING_LINES",
    message_template="The document has no lines/items",
    suggestion_template="Add at least one line/item before confirming. Use odoo_core_write to add lines using the (0, 0, {values}) command syntax.",
    extract_groups={},
)

ErrorPattern(
    id="BIZ-004",
    pattern=r"The move.*?is already reconciled",
    error_class="odoo.exceptions.UserError",
    category="state",
    code="ALREADY_RECONCILED",
    message_template="The journal entry is already reconciled",
    suggestion_template="This payment/entry has already been reconciled. To modify it, you need to unreconcile first.",
    extract_groups={},
)

ErrorPattern(
    id="BIZ-005",
    pattern=r"(?:You can not|cannot)\s+(?:delete|remove|unlink).*?(?:posted|validated|confirmed)",
    error_class="odoo.exceptions.UserError",
    category="state",
    code="CANNOT_DELETE_PROCESSED",
    message_template="Cannot delete a processed/posted record",
    suggestion_template="Reset the record to draft first (using action_draft or action_cancel), then delete it.",
    extract_groups={},
)
```

---

## 9. Connection Error Patterns

```python
ErrorPattern(
    id="CONN-001",
    pattern=r"(?:Connection refused|connection refused|ECONNREFUSED)",
    error_class=None,
    category="connection",
    code="CONNECTION_REFUSED",
    message_template="Cannot connect to Odoo server",
    suggestion_template="The Odoo server at {url} is not responding. Check that the server is running and the URL is correct.",
    extract_groups={},
)

ErrorPattern(
    id="CONN-002",
    pattern=r"(?:timed out|timeout|ETIMEDOUT)",
    error_class=None,
    category="connection",
    code="TIMEOUT",
    message_template="Request timed out",
    suggestion_template="The Odoo server took too long to respond. The operation may still be processing. Wait a moment and check the result, or retry with a simpler query.",
    extract_groups={},
)

ErrorPattern(
    id="CONN-003",
    pattern=r"Session expired|session_expired|Invalid session",
    error_class=None,
    category="connection",
    code="SESSION_EXPIRED",
    message_template="Odoo session has expired",
    suggestion_template="The session needs to be refreshed. This should happen automatically. If the error persists, restart the MCP server.",
    extract_groups={},
)
```

---

## 10. Pattern Matching Implementation

**REQ-10a-02**: The error classifier MUST attempt pattern matching in this order:

1. Match by `error_class` first (narrowest match).
2. Then match by `pattern` regex against the error message.
3. If multiple patterns match, use the first match (patterns are ordered by specificity).
4. If no pattern matches, use the fallback classification from SPEC-10 REQ-10-05/06/07.

```python
def classify_error(
    error_message: str,
    error_class: str | None = None,
    model: str | None = None,
    method: str | None = None,
) -> ErrorResponse:
    """Classify an Odoo error using the pattern database."""

    for pattern in ERROR_PATTERNS:
        # Check error_class match (if specified in pattern)
        if pattern.error_class and error_class:
            if pattern.error_class not in error_class:
                continue

        # Check regex match
        match = re.search(pattern.pattern, error_message, re.IGNORECASE)
        if match:
            # Extract named groups
            groups = {}
            for name, group_ref in pattern.extract_groups.items():
                group_num = int(group_ref.replace("group", ""))
                groups[name] = match.group(group_num) if match.lastindex >= group_num else ""

            # Add context
            groups['model'] = model or groups.get('model', 'unknown')
            groups['method'] = method or ''

            return ErrorResponse(
                category=pattern.category,
                code=pattern.code,
                message=pattern.message_template.format(**groups),
                suggestion=pattern.suggestion_template.format(**groups),
                retry=pattern.category not in ('access', 'configuration'),
                original_error=error_message,
                details=groups,
            )

    # Fallback: no pattern matched
    return ErrorResponse(
        category="unknown",
        code="UNKNOWN_ERROR",
        message=f"Odoo error: {error_message[:200]}",
        suggestion="An unexpected error occurred. Check the error details and try a different approach.",
        retry=False,
        original_error=error_message,
    )
```

**REQ-10a-03**: The pattern database MUST be loadable from the patterns module. New patterns can be added by appending to the `ERROR_PATTERNS` list without modifying the classifier logic.
