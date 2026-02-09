# 05 — Business Workflow Tools

| Field        | Value                              |
|-------------|-------------------------------------|
| Document ID | SPEC-05                             |
| Title       | Business Workflow Tools              |
| Status      | Draft                               |
| Depends On  | SPEC-03, SPEC-04                    |
| Referenced By | —                                  |
| Sub-Specs   | L2/05a (Wizard Protocol)            |

---

## 1. Overview

This document specifies the workflow toolsets — higher-level tools that combine multiple Odoo API calls into business-meaningful operations. Unlike core tools (SPEC-04) that map 1:1 to Odoo ORM methods, workflow tools encode business logic (e.g., "create a sales order with lines and confirm it").

Each workflow toolset corresponds to an Odoo module and is only available when that module is installed.

---

## 2. Design Principles

1. **Business-level abstraction**: Tools match how users think about operations, not how the API works.
2. **Complete operations**: A workflow tool performs all steps needed for a business action (e.g., create order + add lines + confirm).
3. **Smart defaults**: Tools fill in sensible defaults where possible (e.g., current date, default warehouse).
4. **Safe by default**: Destructive steps (posting, validating) require explicit confirmation parameters.
5. **Composable**: Workflow tools can call core tools internally — they are convenience wrappers.

---

## 3. Sales Toolset (`sales`)

**Required module**: `sale`

### 3.1 odoo_sales_create_order

**REQ-05-01**: Create a sales order with optional order lines in a single operation.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "partner_id": {
      "type": "integer",
      "description": "Customer ID (res.partner). Use odoo_core_search_read to find the customer first."
    },
    "partner_name": {
      "type": "string",
      "description": "Alternative to partner_id: customer name. Will be searched via name_search. If multiple matches, returns them for disambiguation."
    },
    "lines": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "product_id": { "type": "integer", "description": "Product ID" },
          "product_name": { "type": "string", "description": "Alternative: product name for search" },
          "quantity": { "type": "number", "default": 1 },
          "price_unit": { "type": "number", "description": "Unit price override. If omitted, uses product's sale price." },
          "discount": { "type": "number", "description": "Discount percentage (0-100)" },
          "name": { "type": "string", "description": "Line description override" }
        }
      },
      "description": "Order lines. Each line needs either product_id or product_name."
    },
    "date_order": { "type": "string", "description": "Order date (YYYY-MM-DD). Default: today." },
    "pricelist_id": { "type": "integer", "description": "Pricelist ID. Default: customer's pricelist." },
    "warehouse_id": { "type": "integer", "description": "Warehouse ID. Default: default warehouse." },
    "note": { "type": "string", "description": "Internal note" },
    "confirm": { "type": "boolean", "default": false, "description": "If true, also confirm the order (action_confirm)" }
  },
  "required": ["partner_id"]
}
```

**REQ-05-02**: The tool MUST resolve `partner_name` to `partner_id` via `name_search` if `partner_id` is not provided. If multiple matches are found, return them as disambiguation options without creating the order:

```json
{
  "status": "disambiguation_needed",
  "field": "partner_id",
  "matches": [
    {"id": 1, "name": "Acme Corp"},
    {"id": 2, "name": "Acme Industries"}
  ],
  "message": "Multiple customers match 'Acme'. Please specify partner_id."
}
```

**REQ-05-03**: The tool MUST resolve `product_name` in order lines using the same disambiguation pattern.

**REQ-05-04**: On success:
```json
{
  "id": 42,
  "name": "SO042",
  "state": "draft",
  "partner": {"id": 1, "name": "Acme Corp"},
  "lines": [
    {"id": 101, "product": "Widget A", "quantity": 5, "price_unit": 10.0, "subtotal": 50.0}
  ],
  "amount_total": 50.0,
  "confirmed": false,
  "message": "Created sales order SO042 with 1 line(s)"
}
```

### 3.2 odoo_sales_confirm_order

**REQ-05-05**: Confirm a draft sales order.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "order_id": { "type": "integer", "description": "Sales order ID" },
    "order_name": { "type": "string", "description": "Alternative: order reference (e.g., 'SO042')" }
  }
}
```

**REQ-05-06**: The tool MUST call `action_confirm` on the sale.order. If the order is not in `draft` or `sent` state, return an error with the current state.

### 3.3 odoo_sales_cancel_order

**REQ-05-07**: Cancel a sales order.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "order_id": { "type": "integer" },
    "order_name": { "type": "string" }
  }
}
```

**REQ-05-08**: Calls `action_cancel`. If the order has pickings or invoices that prevent cancellation, the error handler MUST explain the situation.

### 3.4 odoo_sales_get_order

**REQ-05-09**: Retrieve a sales order with all its details (lines, related documents).

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "order_id": { "type": "integer" },
    "order_name": { "type": "string" },
    "include_lines": { "type": "boolean", "default": true },
    "include_deliveries": { "type": "boolean", "default": false },
    "include_invoices": { "type": "boolean", "default": false }
  }
}
```

**REQ-05-10**: The response MUST include a structured summary with related document counts and states.

---

## 4. Accounting Toolset (`accounting`)

**Required module**: `account`

### 4.1 odoo_accounting_create_invoice

**REQ-05-11**: Create a customer or vendor invoice.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "move_type": {
      "type": "string",
      "enum": ["out_invoice", "out_refund", "in_invoice", "in_refund"],
      "description": "out_invoice=Customer Invoice, out_refund=Credit Note, in_invoice=Vendor Bill, in_refund=Vendor Credit Note",
      "default": "out_invoice"
    },
    "partner_id": { "type": "integer", "description": "Partner (customer/vendor) ID" },
    "partner_name": { "type": "string" },
    "lines": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "product_id": { "type": "integer" },
          "product_name": { "type": "string" },
          "quantity": { "type": "number", "default": 1 },
          "price_unit": { "type": "number" },
          "name": { "type": "string", "description": "Line label (required if no product)" },
          "account_id": { "type": "integer", "description": "Account ID (auto-determined from product if omitted)" },
          "tax_ids": { "type": "array", "items": { "type": "integer" }, "description": "Tax IDs to apply" }
        }
      }
    },
    "invoice_date": { "type": "string", "description": "Invoice date (YYYY-MM-DD). Default: today." },
    "journal_id": { "type": "integer", "description": "Accounting journal. Default: auto-selected." },
    "currency_id": { "type": "integer", "description": "Currency. Default: company currency." },
    "ref": { "type": "string", "description": "Payment reference / vendor bill number" },
    "post": { "type": "boolean", "default": false, "description": "If true, also post (validate) the invoice" }
  },
  "required": ["partner_id"]
}
```

**REQ-05-12**: Invoice lines MUST be created using the `(0, 0, values)` command syntax on the `invoice_line_ids` field.

**REQ-05-13**: The response MUST include the invoice number, total amounts (untaxed, tax, total), and the state.

### 4.2 odoo_accounting_post_invoice

**REQ-05-14**: Post (validate) a draft invoice.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "invoice_id": { "type": "integer" },
    "invoice_name": { "type": "string", "description": "Invoice reference for search" }
  }
}
```

**REQ-05-15**: Calls `action_post`. If the invoice has validation errors (missing tax, unbalanced), the error handler MUST explain each issue.

### 4.3 odoo_accounting_register_payment

**REQ-05-16**: Register a payment for one or more invoices. This involves creating and executing a payment wizard.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "invoice_ids": {
      "type": "array",
      "items": { "type": "integer" },
      "description": "Invoice IDs to pay"
    },
    "amount": { "type": "number", "description": "Payment amount. Default: full amount due." },
    "journal_id": { "type": "integer", "description": "Payment journal (bank/cash). Default: first bank journal." },
    "payment_date": { "type": "string", "description": "Payment date (YYYY-MM-DD). Default: today." },
    "payment_method": { "type": "string", "description": "Payment method code. Default: 'manual'." }
  },
  "required": ["invoice_ids"]
}
```

**REQ-05-17**: This tool uses the wizard protocol (SPEC-L2/05a) to execute `account.payment.register`.

---

## 5. Inventory Toolset (`inventory`)

**Required module**: `stock`

### 5.1 odoo_inventory_get_stock

**REQ-05-18**: Get current stock levels for products.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "product_id": { "type": "integer" },
    "product_name": { "type": "string" },
    "location_id": { "type": "integer", "description": "Specific location. Default: all locations." },
    "warehouse_id": { "type": "integer" }
  }
}
```

**REQ-05-19**: The tool MUST query `stock.quant` and return:
```json
{
  "product": {"id": 5, "name": "Widget A"},
  "stock": [
    {
      "location": {"id": 8, "name": "WH/Stock"},
      "quantity": 100,
      "reserved_quantity": 10,
      "available_quantity": 90
    }
  ],
  "total_available": 90
}
```

### 5.2 odoo_inventory_validate_picking

**REQ-05-20**: Validate (process) a stock picking (delivery, receipt, internal transfer).

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "picking_id": { "type": "integer" },
    "picking_name": { "type": "string", "description": "Picking reference (e.g., 'WH/OUT/00042')" },
    "force_qty": { "type": "boolean", "default": false, "description": "If true, validate even with partial quantities (creates backorder)" }
  }
}
```

**REQ-05-21**: Calls `button_validate`. If quantities are incomplete, a wizard (`stock.backorder.confirmation` or `stock.immediate.transfer`) may be needed. The tool MUST handle these wizards automatically using the wizard protocol (SPEC-L2/05a).

### 5.3 odoo_inventory_create_transfer

**REQ-05-22**: Create an internal stock transfer.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "picking_type_name": {
      "type": "string",
      "description": "Transfer type: 'internal', 'incoming', 'outgoing'"
    },
    "location_src_id": { "type": "integer", "description": "Source location ID" },
    "location_dest_id": { "type": "integer", "description": "Destination location ID" },
    "lines": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "product_id": { "type": "integer" },
          "product_name": { "type": "string" },
          "quantity": { "type": "number" }
        }
      }
    },
    "scheduled_date": { "type": "string" },
    "validate": { "type": "boolean", "default": false }
  },
  "required": ["lines"]
}
```

---

## 6. CRM Toolset (`crm`)

**Required module**: `crm`

### 6.1 odoo_crm_create_lead

**REQ-05-23**: Create a CRM lead or opportunity.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "name": { "type": "string", "description": "Lead/opportunity title" },
    "partner_id": { "type": "integer" },
    "partner_name": { "type": "string", "description": "Contact name (creates lead without partner link)" },
    "email_from": { "type": "string" },
    "phone": { "type": "string" },
    "type": { "type": "string", "enum": ["lead", "opportunity"], "default": "lead" },
    "expected_revenue": { "type": "number" },
    "team_id": { "type": "integer", "description": "Sales team ID" },
    "user_id": { "type": "integer", "description": "Salesperson ID" },
    "stage_id": { "type": "integer" },
    "description": { "type": "string" },
    "tag_ids": { "type": "array", "items": { "type": "integer" } }
  },
  "required": ["name"]
}
```

### 6.2 odoo_crm_move_stage

**REQ-05-24**: Move a lead/opportunity to a different pipeline stage.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "lead_id": { "type": "integer" },
    "stage_id": { "type": "integer" },
    "stage_name": { "type": "string", "description": "Alternative: stage name for search" }
  },
  "required": ["lead_id"]
}
```

### 6.3 odoo_crm_convert_to_opportunity

**REQ-05-25**: Convert a lead to an opportunity.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "lead_id": { "type": "integer" },
    "partner_id": { "type": "integer", "description": "Link to existing partner. If omitted, creates new partner." },
    "user_id": { "type": "integer", "description": "Assign to salesperson" },
    "team_id": { "type": "integer" }
  },
  "required": ["lead_id"]
}
```

**REQ-05-26**: This uses the `crm.lead2opportunity.partner` wizard. The tool MUST handle this via the wizard protocol (SPEC-L2/05a).

---

## 7. Helpdesk Toolset (`helpdesk`)

**Required module**: `helpdesk` (Odoo Enterprise only)

### 7.1 odoo_helpdesk_create_ticket

**REQ-05-27**: Create a helpdesk ticket.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "name": { "type": "string", "description": "Ticket subject" },
    "partner_id": { "type": "integer" },
    "partner_name": { "type": "string" },
    "team_id": { "type": "integer" },
    "user_id": { "type": "integer", "description": "Assigned user" },
    "description": { "type": "string" },
    "priority": { "type": "string", "enum": ["0", "1", "2", "3"], "description": "0=Low, 1=Medium, 2=High, 3=Urgent" },
    "tag_ids": { "type": "array", "items": { "type": "integer" } }
  },
  "required": ["name"]
}
```

### 7.2 odoo_helpdesk_get_ticket

**REQ-05-28**: Retrieve a helpdesk ticket with full details including messages and attachments.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "ticket_id": { "type": "integer" },
    "ticket_name": { "type": "string" },
    "include_messages": { "type": "boolean", "default": true },
    "include_attachments": { "type": "boolean", "default": false },
    "message_limit": { "type": "integer", "default": 20 }
  }
}
```

### 7.3 odoo_helpdesk_assign_ticket

**REQ-05-29**: Assign a ticket to a user and/or team.

---

## 8. Project Toolset (`project`)

**Required module**: `project`

### 8.1 odoo_project_create_task

**REQ-05-30**: Create a project task.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "name": { "type": "string", "description": "Task name" },
    "project_id": { "type": "integer" },
    "project_name": { "type": "string" },
    "user_ids": { "type": "array", "items": { "type": "integer" }, "description": "Assigned users" },
    "description": { "type": "string" },
    "date_deadline": { "type": "string" },
    "priority": { "type": "string", "enum": ["0", "1"], "description": "0=Normal, 1=Urgent" },
    "parent_id": { "type": "integer", "description": "Parent task ID (for subtasks)" },
    "tag_ids": { "type": "array", "items": { "type": "integer" } }
  },
  "required": ["name"]
}
```

### 8.2 odoo_project_move_stage

**REQ-05-31**: Move a task to a different kanban stage.

### 8.3 odoo_project_log_timesheet

**REQ-05-32**: Log a timesheet entry on a task.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "task_id": { "type": "integer" },
    "hours": { "type": "number", "description": "Hours spent" },
    "description": { "type": "string", "description": "Work description" },
    "date": { "type": "string", "description": "Date (YYYY-MM-DD). Default: today." },
    "user_id": { "type": "integer", "description": "Employee user. Default: current user." }
  },
  "required": ["task_id", "hours"]
}
```

**REQ-05-33**: This creates a record on `account.analytic.line` linked to the task. Requires the `hr_timesheet` module.

---

## 9. Wizard Handling

**REQ-05-34**: Many Odoo business operations trigger wizards (TransientModel). The wizard protocol is fully specified in SPEC-L2/05a. All workflow tools that encounter wizards MUST handle them transparently.

**REQ-05-35**: When a workflow tool encounters an unexpected wizard (not in the known wizard catalog), it MUST:
1. Return the wizard details to the LLM client.
2. Include instructions for how the LLM can complete the wizard using `odoo_core_execute`.
3. NOT silently skip or dismiss the wizard.

---

## 10. Name Resolution Pattern

**REQ-05-36**: All workflow tools that accept both `_id` and `_name` parameters MUST follow this resolution pattern:

1. If `_id` is provided, use it directly.
2. If `_name` is provided, call `name_search(name, limit=5)`.
3. If exactly 1 match → use it.
4. If 0 matches → return error with suggestion to check spelling or use `odoo_core_search_read`.
5. If 2+ matches → return disambiguation list (max 10) with IDs and display names.

This pattern MUST be implemented as a reusable utility method, not duplicated in each tool.

---

## 11. Workflow State Machines

**REQ-05-37**: Each workflow toolset MUST document the state transitions for its primary models in tool descriptions. Example for `sale.order`:

```
sale.order states:
  draft (Quotation) → [action_confirm] → sale (Sales Order)
  draft → [action_cancel] → cancel
  sale → [action_done] → done (Locked)
  sale → [action_cancel] → cancel (if no deliveries/invoices)
  cancel → [action_draft] → draft (Reset to Draft)
```

This information helps the LLM understand which operations are valid in which states.
