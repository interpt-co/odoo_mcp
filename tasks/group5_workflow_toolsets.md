# Group 5: Business Workflow Toolsets & Wizard Protocol

| Field | Value |
|-------|-------|
| Branch | `feat/workflow-toolsets` |
| Focus | Wizard protocol, name resolution, all domain-specific workflow toolsets |
| Spec Docs | SPEC-05, SPEC-09, L2/05a |
| Requirements | REQ-05-01 through REQ-05-37, REQ-05a-01 through REQ-05a-11, REQ-09-01 through REQ-09-26 |

## Files Owned

```
odoo_mcp/toolsets/wizard.py
odoo_mcp/toolsets/helpers.py
odoo_mcp/toolsets/sales.py
odoo_mcp/toolsets/accounting.py
odoo_mcp/toolsets/inventory.py
odoo_mcp/toolsets/crm.py
odoo_mcp/toolsets/helpdesk.py
odoo_mcp/toolsets/project.py
odoo_mcp/toolsets/chatter.py
odoo_mcp/toolsets/attachments.py
odoo_mcp/toolsets/reports.py
tests/test_workflows/__init__.py
tests/test_workflows/test_wizard.py
tests/test_workflows/test_helpers.py
tests/test_workflows/test_sales.py
tests/test_workflows/test_accounting.py
tests/test_workflows/test_inventory.py
tests/test_workflows/test_crm.py
tests/test_workflows/test_chatter.py
tests/test_workflows/test_attachments.py
tests/test_workflows/test_reports.py
```

## Interface Dependencies (from other groups, available after merge)

- **OdooProtocol/ConnectionManager** (Group 1): For API calls
- **OdooMcpConfig** (Group 1): For mode, safety settings
- **ErrorHandler** (Group 2): For error classification
- **SafetyConfig/enforce_mode** (Group 2): For mode enforcement
- **ModelRegistry** (Group 3): For field info, model existence
- **BaseToolset** (Group 4): Abstract base class to extend
- **ToolsetMetadata** (Group 4): Metadata dataclass
- **formatting utilities** (Group 4): Response normalization

## Post-Merge Integration

After merging all 5 branches, update `odoo_mcp/toolsets/__init__.py` to add all workflow toolsets to `ALL_TOOLSETS`:

```python
from .sales import SalesToolset
from .accounting import AccountingToolset
from .inventory import InventoryToolset
from .crm import CrmToolset
from .helpdesk import HelpdeskToolset
from .project import ProjectToolset
from .chatter import ChatterToolset
from .attachments import AttachmentsToolset
from .reports import ReportsToolset

ALL_TOOLSETS = [
    CoreToolset,
    SalesToolset,
    AccountingToolset,
    InventoryToolset,
    CrmToolset,
    HelpdeskToolset,
    ProjectToolset,
    ChatterToolset,
    AttachmentsToolset,
    ReportsToolset,
]
```

---

## Task 5.1: Wizard Execution Protocol

**Complexity**: Large

**Description**: Implement the wizard detection, execution, and known wizard catalog.

**Spec References**: REQ-05-34, REQ-05-35, REQ-05a-01 through REQ-05a-11

**Files to Create**:
- `odoo_mcp/toolsets/wizard.py`
- `tests/test_workflows/test_wizard.py`

**Implementation Details**:
1. Wizard detection (REQ-05a-02):
   ```python
   def is_wizard_action(result: Any) -> bool:
       # Check: isinstance(result, dict)
       # Check: type == 'ir.actions.act_window' and target == 'new'
   ```
2. Wizard execution protocol (REQ-05a-04):
   ```python
   async def execute_wizard(
       connection, wizard_model, wizard_values,
       action_method, source_model=None, source_ids=None,
   ) -> Any:
       # 1. Build context (active_model, active_ids, active_id)
       # 2. Get defaults via default_get
       # 3. Merge defaults with provided values
       # 4. Create wizard record
       # 5. Execute wizard action method
       # 6. Return result
   ```
3. Context passing (REQ-05a-05, REQ-05a-06):
   - `active_model`, `active_id`, `active_ids`, `active_domain`, `default_*`
4. Result handling (REQ-05a-07):
   - None/True/False -> operation complete
   - Action dict (form) -> may be another wizard (chain)
   - Action dict (close) -> `ir.actions.act_window_close` -> complete
   - Action dict (report) -> report generated
   - Action dict (URL) -> external URL
   - Wizard chains: max depth 3 to prevent infinite loops
5. Known wizard catalog (REQ-05a-08):
   Define `KnownWizard` dataclass (REQ-05a-11):
   ```python
   @dataclass
   class WizardField:
       type: str
       required: bool = False
       description: str = ""
       relation: str | None = None
       selection: list[tuple[str, str]] | None = None
       default: Any = None

   @dataclass
   class KnownWizard:
       model: str
       description: str
       source_model: str
       action_method: str
       fields: dict[str, WizardField]
       context_keys: list[str]
       alternative_actions: dict[str, str] | None = None
       min_odoo_version: int = 14
       max_odoo_version: int | None = None
   ```
   Catalog entries:
   - `account.payment.register` — Payment registration
   - `stock.immediate.transfer` — Immediate transfer
   - `stock.backorder.confirmation` — Backorder confirmation
   - `sale.advance.payment.inv` — Create invoice from SO
   - `crm.lead2opportunity.partner` — Convert lead to opportunity
   - `account.move.reversal` — Invoice reversal / credit note
6. Unknown wizard handling (REQ-05a-09, REQ-05a-10):
   - Return structured response with wizard_model, wizard_fields (from fields_get), instructions for LLM, context_hint
7. Wizard encounter in workflow tools (REQ-05a-03):
   - Known wizard -> handle automatically
   - Unknown wizard -> return details to LLM

**Acceptance Criteria**:
- Wizard detection works for action dicts
- Standard wizard lifecycle (create, populate, execute) works
- All 6 known wizards have complete catalog entries
- Wizard chains limited to depth 3
- Unknown wizards return structured guidance
- Tests cover wizard lifecycle with mocked data

---

## Task 5.2: Name Resolution & Shared Helpers

**Complexity**: Small

**Description**: Implement the reusable name resolution pattern and shared utilities for workflow tools.

**Spec References**: REQ-05-02, REQ-05-36

**Files to Create**:
- `odoo_mcp/toolsets/helpers.py`
- `tests/test_workflows/test_helpers.py`

**Implementation Details**:
1. Name resolution pattern (REQ-05-36):
   ```python
   async def resolve_name(
       connection, model, id_value, name_value, field_name="name",
   ) -> int | dict:
       """
       Resolve an entity by ID or name.
       Returns: int (resolved ID) or dict (disambiguation/error response)
       """
   ```
   - If `_id` provided -> use directly
   - If `_name` provided -> call `name_search(name, limit=5)`
   - Exactly 1 match -> return ID
   - 0 matches -> return error dict with suggestion
   - 2+ matches -> return disambiguation dict (max 10 entries with IDs and display names)
2. Disambiguation response format (REQ-05-02):
   ```json
   {
     "status": "disambiguation_needed",
     "field": "partner_id",
     "matches": [{"id": 1, "name": "Acme Corp"}, {"id": 2, "name": "Acme Industries"}],
     "message": "Multiple customers match 'Acme'. Please specify partner_id."
   }
   ```
3. This is a REUSABLE utility (REQ-05-36 says it MUST NOT be duplicated)
4. Additional helpers:
   - `resolve_product(connection, id_value, name_value)` — product-specific resolution
   - `resolve_order(connection, model, id_value, name_value)` — order reference resolution

**Acceptance Criteria**:
- Single implementation used by all workflow tools
- Correct behavior for 0, 1, and 2+ matches
- Disambiguation includes IDs and display names
- Tests cover all resolution paths

---

## Task 5.3: Sales Toolset

**Complexity**: Large

**Description**: Implement the sales workflow toolset.

**Spec References**: REQ-05-01 through REQ-05-10, REQ-05-37

**Files to Create**:
- `odoo_mcp/toolsets/sales.py`
- `tests/test_workflows/test_sales.py`

**Implementation Details**:
1. `SalesToolset(BaseToolset)`:
   - Metadata: name="sales", required_modules=["sale"], depends_on=["core"]
2. `odoo_sales_create_order` (REQ-05-01 through REQ-05-04):
   - Input: partner_id OR partner_name, lines (product_id/product_name, quantity, price_unit, discount, name), date_order, pricelist_id, warehouse_id, note, confirm
   - Name resolution for partner and products
   - Create order with lines using (0, 0, values) syntax
   - Optionally confirm if `confirm=True`
   - Response: `{id, name, state, partner, lines, amount_total, confirmed, message}`
3. `odoo_sales_confirm_order` (REQ-05-05, REQ-05-06):
   - Input: order_id OR order_name
   - Call `action_confirm` on sale.order
   - Validate order is in draft/sent state first
4. `odoo_sales_cancel_order` (REQ-05-07, REQ-05-08):
   - Input: order_id OR order_name
   - Call `action_cancel`
   - Handle errors from pickings/invoices that prevent cancellation
5. `odoo_sales_get_order` (REQ-05-09, REQ-05-10):
   - Input: order_id OR order_name, include_lines, include_deliveries, include_invoices
   - Return structured summary with related document counts/states
6. State machine documentation in tool descriptions (REQ-05-37):
   ```
   sale.order states:
     draft → [action_confirm] → sale
     draft → [action_cancel] → cancel
     sale → [action_done] → done
     sale → [action_cancel] → cancel
     cancel → [action_draft] → draft
   ```
7. Mode enforcement: create/confirm/cancel hidden in readonly mode

**Acceptance Criteria**:
- All 4 sales tools registered
- Name resolution works for partner and products
- Lines created with correct (0, 0, values) syntax
- State validation before state-changing operations
- Error messages explain business logic issues
- State machine documented in descriptions

---

## Task 5.4: Accounting Toolset

**Complexity**: Large

**Description**: Implement the accounting workflow toolset.

**Spec References**: REQ-05-11 through REQ-05-17

**Files to Create**:
- `odoo_mcp/toolsets/accounting.py`
- `tests/test_workflows/test_accounting.py`

**Implementation Details**:
1. `AccountingToolset(BaseToolset)`:
   - Metadata: name="accounting", required_modules=["account"], depends_on=["core"]
2. `odoo_accounting_create_invoice` (REQ-05-11 through REQ-05-13):
   - Input: move_type (out_invoice/out_refund/in_invoice/in_refund), partner_id/partner_name, lines (product_id/product_name, quantity, price_unit, name, account_id, tax_ids), invoice_date, journal_id, currency_id, ref, post
   - Lines via `(0, 0, values)` on `invoice_line_ids` field (REQ-05-12)
   - Response: invoice number, amounts (untaxed, tax, total), state (REQ-05-13)
3. `odoo_accounting_post_invoice` (REQ-05-14, REQ-05-15):
   - Input: invoice_id OR invoice_name
   - Call `action_post`
   - Handle validation errors: missing tax, unbalanced entries
4. `odoo_accounting_register_payment` (REQ-05-16, REQ-05-17):
   - Input: invoice_ids, amount, journal_id, payment_date, payment_method
   - Uses wizard protocol: `account.payment.register` wizard
   - Context: `active_model='account.move'`, `active_ids=invoice_ids`
   - Auto-selects first bank journal if not specified
5. All tools handle mode enforcement
6. State machine for account.move in descriptions

**Acceptance Criteria**:
- All 3 accounting tools registered
- Invoice lines created correctly
- Payment wizard protocol works end-to-end
- Validation error explanations are helpful
- Tests cover invoice lifecycle

---

## Task 5.5: Inventory Toolset

**Complexity**: Medium

**Description**: Implement the inventory/warehouse workflow toolset.

**Spec References**: REQ-05-18 through REQ-05-22

**Files to Create**:
- `odoo_mcp/toolsets/inventory.py`
- `tests/test_workflows/test_inventory.py`

**Implementation Details**:
1. `InventoryToolset(BaseToolset)`:
   - Metadata: name="inventory", required_modules=["stock"], depends_on=["core"]
2. `odoo_inventory_get_stock` (REQ-05-18, REQ-05-19):
   - Input: product_id/product_name, location_id, warehouse_id
   - Query `stock.quant`
   - Response: product info, stock per location (quantity, reserved, available), total_available
3. `odoo_inventory_validate_picking` (REQ-05-20, REQ-05-21):
   - Input: picking_id/picking_name, force_qty
   - Call `button_validate`
   - Handle wizards automatically:
     - `stock.immediate.transfer` — process all immediately
     - `stock.backorder.confirmation` — create backorder or cancel remaining
   - Use wizard protocol from Task 5.1
4. `odoo_inventory_create_transfer` (REQ-05-22):
   - Input: picking_type_name, location_src_id, location_dest_id, lines (product_id/name, quantity), scheduled_date, validate
   - Create `stock.picking` with `stock.move` lines
   - Optionally validate immediately

**Acceptance Criteria**:
- All 3 inventory tools registered
- Stock quant query returns correct availability
- Picking validation handles wizards transparently
- Transfer creation works with product name resolution

---

## Task 5.6: CRM Toolset

**Complexity**: Medium

**Description**: Implement the CRM workflow toolset.

**Spec References**: REQ-05-23 through REQ-05-26

**Files to Create**:
- `odoo_mcp/toolsets/crm.py`
- `tests/test_workflows/test_crm.py`

**Implementation Details**:
1. `CrmToolset(BaseToolset)`:
   - Metadata: name="crm", required_modules=["crm"], depends_on=["core"]
2. `odoo_crm_create_lead` (REQ-05-23):
   - Input: name, partner_id/partner_name, email_from, phone, type (lead/opportunity), expected_revenue, team_id, user_id, stage_id, description, tag_ids
   - Create `crm.lead` record
3. `odoo_crm_move_stage` (REQ-05-24):
   - Input: lead_id, stage_id/stage_name
   - Write `stage_id` on `crm.lead`
   - Resolve stage by name if needed
4. `odoo_crm_convert_to_opportunity` (REQ-05-25, REQ-05-26):
   - Input: lead_id, partner_id, user_id, team_id
   - Uses `crm.lead2opportunity.partner` wizard via wizard protocol
   - Handle partner creation/linking options

**Acceptance Criteria**:
- All 3 CRM tools registered
- Lead creation works with and without partner
- Stage resolution by name works
- Lead-to-opportunity conversion uses wizard correctly

---

## Task 5.7: Helpdesk Toolset

**Complexity**: Small

**Description**: Implement the helpdesk ticket toolset (Enterprise).

**Spec References**: REQ-05-27 through REQ-05-29

**Files to Create**:
- `odoo_mcp/toolsets/helpdesk.py`

**Implementation Details**:
1. `HelpdeskToolset(BaseToolset)`:
   - Metadata: name="helpdesk", required_modules=["helpdesk"], depends_on=["core"]
2. `odoo_helpdesk_create_ticket` (REQ-05-27):
   - Input: name, partner_id/partner_name, team_id, user_id, description, priority (0-3), tag_ids
3. `odoo_helpdesk_get_ticket` (REQ-05-28):
   - Input: ticket_id/ticket_name, include_messages, include_attachments, message_limit
   - Return full ticket details with optional messages and attachments
4. `odoo_helpdesk_assign_ticket` (REQ-05-29):
   - Input: ticket_id, user_id, team_id
   - Write user_id and/or team_id

**Acceptance Criteria**:
- All 3 helpdesk tools registered
- Only available when `helpdesk` module installed (Enterprise)
- Ticket details include messages when requested

---

## Task 5.8: Project Toolset

**Complexity**: Small

**Description**: Implement the project management toolset.

**Spec References**: REQ-05-30 through REQ-05-33

**Files to Create**:
- `odoo_mcp/toolsets/project.py`

**Implementation Details**:
1. `ProjectToolset(BaseToolset)`:
   - Metadata: name="project", required_modules=["project"], depends_on=["core"]
2. `odoo_project_create_task` (REQ-05-30):
   - Input: name, project_id/project_name, user_ids, description, date_deadline, priority (0/1), parent_id, tag_ids
3. `odoo_project_move_stage` (REQ-05-31):
   - Input: task_id, stage_id/stage_name
   - Write `stage_id` on `project.task`
4. `odoo_project_log_timesheet` (REQ-05-32, REQ-05-33):
   - Input: task_id, hours, description, date, user_id
   - Create `account.analytic.line` record linked to task
   - Requires `hr_timesheet` module

**Acceptance Criteria**:
- All 3 project tools registered
- Task creation supports project name resolution
- Timesheet logging creates correct analytic line
- Timesheet tool notes `hr_timesheet` module requirement

---

## Task 5.9: Chatter Toolset

**Complexity**: Medium

**Description**: Implement the messaging/activity toolset.

**Spec References**: REQ-09-01 through REQ-09-10

**Files to Create**:
- `odoo_mcp/toolsets/chatter.py`
- `tests/test_workflows/test_chatter.py`

**Implementation Details**:
1. `ChatterToolset(BaseToolset)`:
   - Metadata: name="chatter", required_modules=["mail"], depends_on=["core"]
2. `odoo_chatter_get_messages` (REQ-09-01 through REQ-09-03):
   - Input: model, record_id, limit (max 100, default 20), message_types (default: email, comment), strip_html (default true)
   - Query `mail.message` with domain: model, res_id, message_type
   - Response: messages with id, date, author, type, subject, body, email_from
   - HTML stripping when enabled
3. `odoo_chatter_post_message` (REQ-09-04 through REQ-09-06):
   - Input: model, record_id, body, message_type (comment/notification), subtype, partner_ids
   - Call `message_post` with body wrapped in `<p>` tags
   - Auto-select subtype: `mail.mt_comment` for comments, `mail.mt_note` for notes
   - Mode check: not allowed in readonly
4. `odoo_chatter_get_activities` (REQ-09-07, REQ-09-08):
   - Input: model, record_id
   - Query `mail.activity` for the record
   - Return: activities with type, summary, note, deadline, user, state
5. `odoo_chatter_schedule_activity` (REQ-09-09, REQ-09-10):
   - Input: model, record_id, activity_type (email/call/meeting/todo/upload_document), summary, note, date_deadline, user_id
   - Resolve activity_type string to `mail.activity.type` ID via XML ID mapping
   - Create `mail.activity` record

**Acceptance Criteria**:
- All 4 chatter tools registered
- Message retrieval with HTML stripping works
- Message posting respects mode restrictions
- Activity type resolution from friendly names works
- Tests cover message retrieval and posting

---

## Task 5.10: Attachments Toolset

**Complexity**: Medium

**Description**: Implement the file attachment toolset.

**Spec References**: REQ-09-11 through REQ-09-21

**Files to Create**:
- `odoo_mcp/toolsets/attachments.py`
- `tests/test_workflows/test_attachments.py`

**Implementation Details**:
1. `AttachmentsToolset(BaseToolset)`:
   - Metadata: name="attachments", required_modules=[] (ir.attachment is always available), depends_on=["core"]
2. `odoo_attachments_list` (REQ-09-11 through REQ-09-13):
   - Input: model, record_id
   - Query `ir.attachment` for the record
   - Response: attachments with id, name, mimetype, file_size, file_size_human, created_at, created_by
3. `odoo_attachments_get_content` (REQ-09-14 through REQ-09-16):
   - Input: attachment_id, as_text (default false)
   - Safety limits (REQ-09-15):
     - Max size: 12 MB (configurable)
     - Text MIME types: `text/plain`, `text/csv`, `text/html`, `text/xml`, `application/json`, `application/xml`, `application/xhtml+xml`
     - Oversized: return metadata only + warning
   - Text response: `{id, name, mimetype, file_size, content, encoding: "text"}`
   - Binary response: `{id, name, mimetype, file_size, content_base64, encoding: "base64"}`
4. `odoo_attachments_upload` (REQ-09-17 through REQ-09-19):
   - Input: model, record_id, name, content_base64, mimetype (auto-detect from name if omitted)
   - Create `ir.attachment` with `datas` field
   - Mode check: not allowed in readonly
5. `odoo_attachments_delete` (REQ-09-20, REQ-09-21):
   - Input: attachment_id
   - Only allowed in `full` mode
   - Annotation: `destructiveHint=True`

**Acceptance Criteria**:
- All 4 attachment tools registered
- Size limit enforced for downloads
- Text vs binary content detection works
- MIME type auto-detection works
- Upload mode restriction works
- Delete only in full mode

---

## Task 5.11: Reports Toolset

**Complexity**: Medium

**Description**: Implement the PDF report generation toolset.

**Spec References**: REQ-09-22 through REQ-09-26

**Files to Create**:
- `odoo_mcp/toolsets/reports.py`
- `tests/test_workflows/test_reports.py`

**Implementation Details**:
1. `ReportsToolset(BaseToolset)`:
   - Metadata: name="reports", required_modules=[] (reports always available), depends_on=["core"]
2. `odoo_reports_generate` (REQ-09-22 through REQ-09-24):
   - Input: report_name, record_ids (max 20), context
   - Protocol-specific generation (REQ-09-23):
     - **XML-RPC (Odoo 14-16)**: Use `/xmlrpc/2/report` endpoint `render_report`
     - **JSON-RPC (Odoo 17-18)**: Use `ir.actions.report._render_qweb_pdf`
     - **JSON-2 (Odoo 19+)**: Use `ir.actions.report._render_qweb_pdf`
   - Response: `{report_name, record_ids, format: "pdf", content_base64, file_name, size, size_human}`
   - Annotation: `readOnlyHint=True` (reports don't modify data)
3. `odoo_reports_list` (REQ-09-25, REQ-09-26):
   - Input: model
   - Query `ir.actions.report` for the model
   - Response: `{model, reports: [{name, report_name, report_type}]}`

**Acceptance Criteria**:
- Both report tools registered
- Report generation works for XML-RPC and JSON-RPC/JSON-2
- Report list correctly queries available reports for a model
- PDF content returned as base64
- File name generated from report context
- Tests with mocked report data
