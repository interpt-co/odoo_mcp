# 04 — Core CRUD Tools

| Field        | Value                              |
|-------------|-------------------------------------|
| Document ID | SPEC-04                             |
| Title       | Core CRUD Tools                     |
| Status      | Draft                               |
| Depends On  | SPEC-02, SPEC-03                    |
| Referenced By | SPEC-05, SPEC-08                  |
| Sub-Specs   | L2/04a (Domain Syntax)              |

---

## 1. Overview

This document specifies the core toolset — the foundational CRUD tools that work on **any** Odoo model regardless of installed modules. These tools are always available and form the building blocks that higher-level workflow toolsets build upon.

---

## 2. Tool Summary

| Tool Name | Method | Annotations | Description |
|-----------|--------|------------|-------------|
| `odoo_core_search_read` | `search_read` | readOnly | Search records and return field values |
| `odoo_core_read` | `read` | readOnly | Read specific records by ID |
| `odoo_core_create` | `create` | — | Create new record(s) |
| `odoo_core_write` | `write` | — | Update existing record(s) |
| `odoo_core_unlink` | `unlink` | destructive | Delete record(s) |
| `odoo_core_count` | `search_count` | readOnly | Count records matching a domain |
| `odoo_core_fields_get` | `fields_get` | readOnly | Get field definitions for a model |
| `odoo_core_execute` | `execute_kw` | — | Execute any model method |
| `odoo_core_name_get` | `name_get` | readOnly | Get display names for record IDs |
| `odoo_core_default_get` | `default_get` | readOnly | Get default values for a model's fields |
| `odoo_core_list_toolsets` | — | readOnly | List available toolsets (see SPEC-03) |
| `odoo_core_list_models` | — | readOnly | List available Odoo models |

---

## 3. Tool Specifications

### 3.1 odoo_core_search_read

**REQ-04-01**: The `odoo_core_search_read` tool MUST search for records matching a domain filter and return specified fields.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "model": {
      "type": "string",
      "description": "Odoo model name (e.g., 'res.partner', 'sale.order')"
    },
    "domain": {
      "type": "array",
      "description": "Search filter in Odoo domain format. Examples: [['state', '=', 'draft']], [['name', 'ilike', 'acme']]. See domain syntax reference. Default: [] (all records)",
      "default": []
    },
    "fields": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Field names to return. Default: ['id', 'name', 'display_name']. Use ['*'] for all fields (expensive).",
      "default": ["id", "name", "display_name"]
    },
    "limit": {
      "type": "integer",
      "description": "Maximum number of records to return. Default: 80. Max: 500.",
      "default": 80,
      "minimum": 1,
      "maximum": 500
    },
    "offset": {
      "type": "integer",
      "description": "Number of records to skip (for pagination). Default: 0.",
      "default": 0,
      "minimum": 0
    },
    "order": {
      "type": "string",
      "description": "Sort order. Examples: 'name asc', 'create_date desc', 'state asc, name asc'. Default: server default (usually 'id asc')."
    },
    "context": {
      "type": "object",
      "description": "Additional Odoo context parameters (e.g., {'lang': 'pt_PT', 'active_test': false})"
    }
  },
  "required": ["model"]
}
```

**REQ-04-02**: Before executing, the tool MUST:
1. Validate the model name against the safety allowlist/blocklist (SPEC-11).
2. Validate the requested fields against the field blocklist (SPEC-11).
3. Enforce the maximum limit (500) even if the caller requests more.
4. If `fields` is `['*']`, replace it with `None` in the API call (Odoo returns all fields when fields is not specified).

**REQ-04-03**: The tool MUST return results in this format:

```json
{
  "records": [
    {
      "id": 1,
      "name": "Acme Corp",
      "display_name": "Acme Corp"
    }
  ],
  "count": 1,
  "model": "res.partner",
  "limit": 80,
  "offset": 0,
  "has_more": false
}
```

**REQ-04-04**: The `has_more` field MUST be `true` if the number of returned records equals the limit (indicating there may be more records). This helps the LLM decide whether to paginate.

**REQ-04-05**: Many2one fields MUST be returned as objects `{"id": 1, "name": "Display Name"}` instead of the raw Odoo format `[1, "Display Name"]`. This normalization MUST happen in the response formatting layer.

### 3.2 odoo_core_read

**REQ-04-06**: The `odoo_core_read` tool MUST read specific records by their IDs.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "model": {
      "type": "string",
      "description": "Odoo model name"
    },
    "ids": {
      "type": "array",
      "items": { "type": "integer" },
      "description": "Record IDs to read. Maximum 100 IDs per call.",
      "minItems": 1,
      "maxItems": 100
    },
    "fields": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Field names to return. Default: all stored fields.",
      "default": []
    },
    "context": {
      "type": "object",
      "description": "Additional Odoo context parameters"
    }
  },
  "required": ["model", "ids"]
}
```

**REQ-04-07**: If any requested ID does not exist, the tool MUST:
- For XML-RPC: Odoo raises `MissingError`. The tool MUST catch this and return the records that do exist plus a `missing_ids` list.
- For JSON-2: Same behavior — catch the error, return available records.

Response format:
```json
{
  "records": [{"id": 1, "name": "Acme Corp"}],
  "missing_ids": [999]
}
```

### 3.3 odoo_core_create

**REQ-04-08**: The `odoo_core_create` tool MUST create one or more new records.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "model": {
      "type": "string",
      "description": "Odoo model name"
    },
    "values": {
      "type": "object",
      "description": "Field values for the new record. For relational fields, see domain syntax reference for command format."
    },
    "context": {
      "type": "object",
      "description": "Additional Odoo context parameters"
    }
  },
  "required": ["model", "values"]
}
```

**REQ-04-09**: The tool MUST check the operation mode (SPEC-11):
- `readonly` mode → reject with error "Create operations are not allowed in readonly mode"
- `restricted` mode → check model against write allowlist
- `full` mode → allow

**REQ-04-10**: On success, return:
```json
{
  "id": 42,
  "model": "res.partner",
  "message": "Created res.partner record with ID 42"
}
```

**REQ-04-11**: On validation error, the error handler (SPEC-10) MUST translate the Odoo error into actionable guidance. Example:
```json
{
  "error": "validation_error",
  "message": "Required field 'name' is missing",
  "field": "name",
  "suggestion": "Include 'name' in the values. For res.partner, 'name' is the contact/company name."
}
```

### 3.4 odoo_core_write

**REQ-04-12**: The `odoo_core_write` tool MUST update existing records.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "model": {
      "type": "string",
      "description": "Odoo model name"
    },
    "ids": {
      "type": "array",
      "items": { "type": "integer" },
      "description": "Record IDs to update",
      "minItems": 1,
      "maxItems": 100
    },
    "values": {
      "type": "object",
      "description": "Field values to update. Only specified fields are changed."
    },
    "context": {
      "type": "object",
      "description": "Additional Odoo context parameters"
    }
  },
  "required": ["model", "ids", "values"]
}
```

**REQ-04-13**: The tool MUST check the operation mode (same as create, SPEC-11).

**REQ-04-14**: The tool MUST validate that fields being written are not in the field blocklist and are not readonly (unless the context explicitly allows it).

**REQ-04-15**: On success, return:
```json
{
  "success": true,
  "model": "res.partner",
  "ids": [42, 43],
  "message": "Updated 2 res.partner record(s)"
}
```

### 3.5 odoo_core_unlink

**REQ-04-16**: The `odoo_core_unlink` tool MUST delete records.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "model": {
      "type": "string",
      "description": "Odoo model name"
    },
    "ids": {
      "type": "array",
      "items": { "type": "integer" },
      "description": "Record IDs to delete",
      "minItems": 1,
      "maxItems": 50
    },
    "context": {
      "type": "object"
    }
  },
  "required": ["model", "ids"]
}
```

**REQ-04-17**: The tool MUST:
- Check operation mode: only allowed in `full` mode (not `readonly` or `restricted`).
- Check the model against the safety blocklist.
- Log the deletion in the audit log (SPEC-11).

**REQ-04-18**: The tool annotation MUST set `destructiveHint: true`.

**REQ-04-19**: On success, return:
```json
{
  "success": true,
  "model": "res.partner",
  "deleted_ids": [42, 43],
  "message": "Deleted 2 res.partner record(s)"
}
```

### 3.6 odoo_core_count

**REQ-04-20**: The `odoo_core_count` tool MUST return the count of records matching a domain.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "model": {
      "type": "string",
      "description": "Odoo model name"
    },
    "domain": {
      "type": "array",
      "description": "Search filter in Odoo domain format. Default: [] (count all records)",
      "default": []
    },
    "context": {
      "type": "object"
    }
  },
  "required": ["model"]
}
```

**REQ-04-21**: Return:
```json
{
  "model": "sale.order",
  "domain": [["state", "=", "draft"]],
  "count": 15
}
```

### 3.7 odoo_core_fields_get

**REQ-04-22**: The `odoo_core_fields_get` tool MUST return field definitions for a model.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "model": {
      "type": "string",
      "description": "Odoo model name"
    },
    "attributes": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Field attributes to return. Default: ['string', 'type', 'required', 'readonly', 'help', 'selection', 'relation']. Use ['*'] for all attributes.",
      "default": ["string", "type", "required", "readonly", "help", "selection", "relation"]
    },
    "context": {
      "type": "object"
    }
  },
  "required": ["model"]
}
```

**REQ-04-23**: The response MUST be formatted for LLM consumption — not the raw Odoo output. Each field MUST include a concise summary:

```json
{
  "model": "sale.order",
  "fields": {
    "name": {
      "label": "Order Reference",
      "type": "char",
      "required": true,
      "readonly": true,
      "help": "Unique reference for this sales order"
    },
    "partner_id": {
      "label": "Customer",
      "type": "many2one",
      "required": true,
      "readonly": false,
      "relation": "res.partner",
      "help": "Customer for this sales order"
    },
    "state": {
      "label": "Status",
      "type": "selection",
      "required": false,
      "readonly": true,
      "selection": [
        ["draft", "Quotation"],
        ["sent", "Quotation Sent"],
        ["sale", "Sales Order"],
        ["done", "Locked"],
        ["cancel", "Cancelled"]
      ]
    }
  },
  "field_count": 3
}
```

**REQ-04-24**: Fields in the blocklist (SPEC-11) MUST be excluded from the response.

### 3.8 odoo_core_execute

**REQ-04-25**: The `odoo_core_execute` tool MUST execute any callable method on an Odoo model. This is the generic "escape hatch" for operations not covered by specific tools.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "model": {
      "type": "string",
      "description": "Odoo model name"
    },
    "method": {
      "type": "string",
      "description": "Method to call (e.g., 'action_confirm', 'button_validate', 'copy')"
    },
    "args": {
      "type": "array",
      "description": "Positional arguments. First argument is typically a list of record IDs.",
      "default": []
    },
    "kwargs": {
      "type": "object",
      "description": "Keyword arguments passed to the method.",
      "default": {}
    },
    "context": {
      "type": "object"
    }
  },
  "required": ["model", "method"]
}
```

**REQ-04-26**: The tool MUST validate:
1. Methods starting with `_` are REJECTED (Odoo convention: private methods cannot be called via RPC).
2. The method name is checked against the method blocklist (SPEC-11).
3. The operation mode is checked: `readonly` mode rejects all non-read methods.
4. Known methods that do NOT accept kwargs (from the `NO_KWARGS_METHODS` set) MUST have kwargs stripped:

```python
NO_KWARGS_METHODS = {
    "action_cancel", "action_confirm", "action_draft", "action_done",
    "action_lock", "action_unlock", "button_validate", "button_draft",
    "button_cancel", "button_confirm", "action_post", "action_open",
    "action_set_draft", "action_quotation_send", "action_view_invoice",
    "copy", "name_get", "name_search", "read", "search", "search_read",
    "search_count", "fields_get", "default_get", "onchange",
}
```

**REQ-04-27**: If the method returns an action dictionary (common for button methods), the response MUST include a summary:

```json
{
  "result_type": "action",
  "action": {
    "type": "ir.actions.act_window",
    "res_model": "stock.picking",
    "res_id": 42,
    "view_mode": "form",
    "summary": "Opens stock.picking form view for record 42"
  }
}
```

If the method returns a simple value, return it directly:
```json
{
  "result_type": "value",
  "result": true
}
```

### 3.9 odoo_core_name_get

**REQ-04-28**: The `odoo_core_name_get` tool MUST return display names for record IDs.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "model": {
      "type": "string",
      "description": "Odoo model name"
    },
    "ids": {
      "type": "array",
      "items": { "type": "integer" },
      "description": "Record IDs",
      "minItems": 1,
      "maxItems": 200
    }
  },
  "required": ["model", "ids"]
}
```

**REQ-04-29**: Return:
```json
{
  "model": "res.partner",
  "names": [
    {"id": 1, "name": "Acme Corporation"},
    {"id": 2, "name": "John Smith"}
  ]
}
```

### 3.10 odoo_core_default_get

**REQ-04-30**: The `odoo_core_default_get` tool MUST return default values for a model's fields.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "model": {
      "type": "string",
      "description": "Odoo model name"
    },
    "fields": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Field names to get defaults for. Empty list = all fields with defaults.",
      "default": []
    },
    "context": {
      "type": "object"
    }
  },
  "required": ["model"]
}
```

**REQ-04-31**: Return:
```json
{
  "model": "sale.order",
  "defaults": {
    "state": "draft",
    "company_id": 1,
    "currency_id": 1,
    "date_order": "2025-02-09"
  }
}
```

### 3.11 odoo_core_list_models

**REQ-04-32**: The `odoo_core_list_models` tool MUST list available Odoo models with basic metadata.

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "filter": {
      "type": "string",
      "description": "Filter models by name pattern (e.g., 'sale', 'account.move'). Matches with ilike."
    },
    "transient": {
      "type": "boolean",
      "description": "Include transient models (wizards). Default: false.",
      "default": false
    }
  }
}
```

**REQ-04-33**: Return:
```json
{
  "models": [
    {
      "model": "sale.order",
      "name": "Sales Order",
      "transient": false,
      "field_count": 85,
      "access": "read,write,create"
    }
  ],
  "count": 1
}
```

**REQ-04-34**: Models in the safety blocklist MUST be excluded. The tool MUST only return models the authenticated user has at least read access to (checked via `check_access_rights`).

---

## 4. Response Formatting

**REQ-04-35**: All tool responses MUST normalize Odoo's raw data format:

| Odoo Raw Format | Normalized Format |
|----------------|-------------------|
| `[1, "Name"]` (Many2one) | `{"id": 1, "name": "Name"}` |
| `False` (empty Many2one) | `null` |
| `False` (empty string field) | `""` |
| `False` (empty date field) | `null` |
| `[1, 2, 3]` (One2many/Many2many IDs) | `[1, 2, 3]` (no change) |
| HTML content in text fields | Stripped to plain text (configurable, default: strip) |

**REQ-04-36**: Binary fields (type `binary`) MUST NOT be returned in search_read or read results by default. They MUST be explicitly requested and returned as base64 strings. The tool MUST warn in the description that binary fields should be requested individually.

**REQ-04-37**: All datetime fields MUST be returned in ISO 8601 format. Odoo returns datetimes as `"2025-02-09 14:30:00"` (no timezone, always UTC). The server MUST append `Z` to indicate UTC: `"2025-02-09T14:30:00Z"`.

---

## 5. Domain Syntax Help

**REQ-04-38**: The `odoo_core_search_read` and `odoo_core_count` tool descriptions MUST include a concise domain syntax reference in the tool description:

```
Domain syntax: List of conditions in Odoo domain format.
Each condition is a tuple: [field, operator, value]
Operators: =, !=, >, >=, <, <=, like, ilike, in, not in, child_of, parent_of
Logical: Use '|' for OR, '&' for AND (default), '!' for NOT — in prefix notation.
Examples:
  [] → all records
  [['state', '=', 'draft']] → records where state is draft
  [['name', 'ilike', 'acme']] → records where name contains 'acme' (case-insensitive)
  [['amount', '>=', 1000], ['state', '=', 'posted']] → AND (both conditions)
  ['|', ['state', '=', 'draft'], ['state', '=', 'sent']] → OR (either condition)
  [['partner_id.country_id.code', '=', 'PT']] → related field traversal
See L2/04a for complete domain reference.
```

This inline help is critical for LLM usability — the LLM needs domain syntax information at tool invocation time.
