# 06 — MCP Resources & Prompts

| Field        | Value                              |
|-------------|-------------------------------------|
| Document ID | SPEC-06                             |
| Title       | MCP Resources & Prompts             |
| Status      | Draft                               |
| Depends On  | SPEC-01, SPEC-02, SPEC-07           |
| Referenced By | —                                  |

---

## 1. Overview

This document specifies the MCP resources and prompts exposed by the Odoo MCP server. Resources provide read-only access to Odoo metadata and record data via URIs. Prompts provide pre-built templates that help LLMs perform common operations correctly.

---

## 2. URI Scheme

**REQ-06-01**: All Odoo resources MUST use the `odoo://` URI scheme with this structure:

```
odoo://{category}/{path}
```

Categories:
- `model/` — Model metadata (fields, methods, states)
- `record/` — Record data
- `system/` — System information (version, modules, toolsets)
- `config/` — Server configuration metadata

---

## 3. Static Resources

### 3.1 System Information

**REQ-06-02**: `odoo://system/info` — Server and Odoo instance information.

```json
{
  "uri": "odoo://system/info",
  "name": "Odoo Instance Info",
  "mimeType": "application/json",
  "description": "Connection details, Odoo version, and server capabilities"
}
```

Response:
```json
{
  "server_version": "17.0",
  "server_edition": "enterprise",
  "database": "mycompany",
  "url": "https://mycompany.odoo.com",
  "protocol": "json2",
  "user": {"uid": 2, "name": "Admin"},
  "mcp_server_version": "0.1.0"
}
```

**REQ-06-03**: `odoo://system/modules` — Installed Odoo modules.

Response:
```json
{
  "modules": [
    {"name": "sale", "state": "installed", "shortdesc": "Sales"},
    {"name": "account", "state": "installed", "shortdesc": "Invoicing"}
  ],
  "count": 85
}
```

**REQ-06-04**: `odoo://system/toolsets` — Registered toolsets and their tools (mirrors the `odoo_core_list_toolsets` tool output).

### 3.2 Configuration

**REQ-06-05**: `odoo://config/safety` — Current safety configuration (operation mode, allowed/blocked models).

Response:
```json
{
  "operation_mode": "restricted",
  "model_allowlist": ["sale.order", "res.partner"],
  "model_blocklist": [],
  "rate_limit": {"calls_per_minute": 60}
}
```

---

## 4. Resource Templates

Resource templates allow dynamic URI construction with parameters.

### 4.1 Model Metadata

**REQ-06-06**: `odoo://model/{model_name}/fields` — Field definitions for a specific model.

```json
{
  "uriTemplate": "odoo://model/{model_name}/fields",
  "name": "Model Fields",
  "mimeType": "application/json",
  "description": "Field definitions for an Odoo model. Example: odoo://model/sale.order/fields"
}
```

**REQ-06-07**: `odoo://model/{model_name}/methods` — Available methods (action_*, button_*) for a model.

Response:
```json
{
  "model": "sale.order",
  "methods": [
    {
      "name": "action_confirm",
      "description": "Confirm the quotation into a sales order",
      "accepts_kwargs": false
    },
    {
      "name": "action_cancel",
      "description": "Cancel the sales order",
      "accepts_kwargs": false
    }
  ]
}
```

**REQ-06-08**: `odoo://model/{model_name}/states` — State machine / workflow for models with a `state` field.

Response:
```json
{
  "model": "sale.order",
  "state_field": "state",
  "states": [
    {"value": "draft", "label": "Quotation"},
    {"value": "sent", "label": "Quotation Sent"},
    {"value": "sale", "label": "Sales Order"},
    {"value": "done", "label": "Locked"},
    {"value": "cancel", "label": "Cancelled"}
  ],
  "transitions": [
    {"from": "draft", "to": "sale", "method": "action_confirm"},
    {"from": "draft", "to": "cancel", "method": "action_cancel"},
    {"from": "sale", "to": "done", "method": "action_done"},
    {"from": "cancel", "to": "draft", "method": "action_draft"}
  ]
}
```

### 4.2 Record Data

**REQ-06-09**: `odoo://record/{model_name}/{record_id}` — Read a specific record.

```json
{
  "uriTemplate": "odoo://record/{model_name}/{record_id}",
  "name": "Odoo Record",
  "mimeType": "application/json",
  "description": "Read a specific Odoo record by model and ID"
}
```

**REQ-06-10**: The resource MUST return the record's key fields (determined by the registry, SPEC-07). Binary fields MUST be excluded. The response MUST use the same normalization as tool responses (REQ-04-35).

### 4.3 Record Listing

**REQ-06-11**: `odoo://record/{model_name}?domain={domain}&limit={limit}` — Search and list records.

The `domain` parameter MUST be URL-encoded JSON. Example:
```
odoo://record/sale.order?domain=[["state","=","draft"]]&limit=10
```

**REQ-06-12**: The maximum `limit` for resource listings is 100. Default is 20.

---

## 5. Resource Subscriptions

**REQ-06-13**: The server MUST support resource subscriptions (MCP `resources/subscribe`). When a client subscribes to a resource, the server MUST send `notifications/resources/updated` when the underlying data changes.

**REQ-06-14**: Change detection MUST use polling with a configurable interval (default: 60 seconds). The server MUST track the `write_date` of subscribed records and notify only when it changes.

**REQ-06-15**: The following resources support subscriptions:
- `odoo://record/{model_name}/{record_id}` — Individual record changes
- `odoo://system/info` — Connection state changes

**REQ-06-16**: The server MUST limit the number of active subscriptions to 50 per client to prevent excessive polling load.

---

## 6. Prompts

MCP prompts are pre-built templates that help LLMs perform operations correctly. They include system context, tool usage guidance, and examples.

### 6.1 Static Prompts

**REQ-06-17**: `odoo_overview` — System overview prompt.

```json
{
  "name": "odoo_overview",
  "description": "Get an overview of the connected Odoo instance, available tools, and how to use them"
}
```

Response template:
```
You are connected to an Odoo {version} ({edition}) instance at {url}.
Database: {database}
User: {username} (uid: {uid})

Available toolsets: {toolset_list}
Total tools: {tool_count}

Key models available: {model_list}

To get started:
- Use odoo_core_search_read to search for records
- Use odoo_core_fields_get to understand a model's structure
- Use workflow tools (e.g., odoo_sales_create_order) for business operations
- Use odoo_core_list_models to discover available models
```

**REQ-06-18**: `odoo_domain_help` — Domain syntax reference prompt.

```json
{
  "name": "odoo_domain_help",
  "description": "Reference guide for Odoo domain filter syntax"
}
```

The response MUST include the complete domain syntax reference from SPEC-L2/04a in a format optimized for LLM context.

### 6.2 Parameterized Prompts

**REQ-06-19**: `odoo_model_guide` — Context-aware guide for working with a specific model.

```json
{
  "name": "odoo_model_guide",
  "description": "Get a guide for working with a specific Odoo model",
  "arguments": [
    {
      "name": "model_name",
      "description": "The Odoo model name (e.g., 'sale.order')",
      "required": true
    }
  ]
}
```

Response template (dynamically generated from registry):
```
# Guide: {model_name} ({model_description})

## Fields
{field_summary — grouped by required, key fields, other}

## States
{state_machine if model has state field}

## Common Operations
- Search: odoo_core_search_read with model="{model_name}"
- Create: {create tool if available, else odoo_core_create}
- Key filters: {common domain patterns for this model}

## Related Models
{list of related models via Many2one/One2many}

## Tips
{model-specific tips from registry}
```

**REQ-06-20**: `odoo_create_record` — Prompt for creating a record on any model.

```json
{
  "name": "odoo_create_record",
  "description": "Get guidance for creating a record on a specific model",
  "arguments": [
    {
      "name": "model_name",
      "description": "The Odoo model name",
      "required": true
    }
  ]
}
```

Response includes:
- Required fields with types and descriptions
- Default values
- Example values for common fields
- Related field resolution guidance (e.g., "for partner_id, first search res.partner")

**REQ-06-21**: `odoo_search_help` — Prompt for constructing search queries.

```json
{
  "name": "odoo_search_help",
  "description": "Get help constructing a search query for a model",
  "arguments": [
    {
      "name": "model_name",
      "description": "The Odoo model name",
      "required": true
    },
    {
      "name": "query",
      "description": "What you're looking for (natural language)",
      "required": true
    }
  ]
}
```

Response includes a suggested domain filter, recommended fields, and the tool call to execute.

---

## 7. Resource Access Control

**REQ-06-22**: Resources MUST respect the same safety configuration as tools (SPEC-11):
- Models in the blocklist MUST NOT be accessible via resources.
- In `readonly` mode, only read resources are available (no mutation resources).
- Field blocklists apply to resource responses.

**REQ-06-23**: Resources MUST respect Odoo's access control. If the authenticated user does not have read access to a model, the resource MUST return an appropriate error, not an empty response.
