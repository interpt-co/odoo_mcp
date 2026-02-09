# L2/05a — Wizard Execution Protocol

| Field        | Value                              |
|-------------|-------------------------------------|
| Document ID | SPEC-L2-05a                         |
| Title       | Wizard Execution Protocol            |
| Status      | Draft                               |
| Parent      | SPEC-05 (Workflow Tools)            |

---

## 1. Overview

Odoo wizards (TransientModel) are temporary records that implement multi-step business operations. Many critical operations (registering payments, confirming stock transfers, merging duplicates) can only be performed through wizards. This document specifies how the MCP server detects, creates, executes, and handles wizard interactions.

---

## 2. Wizard Lifecycle

**REQ-05a-01**: A wizard interaction follows this lifecycle:

```
1. TRIGGER     → A button/action returns an action dict pointing to a TransientModel
2. CREATE      → Create a wizard record with required context and defaults
3. POPULATE    → Fill in wizard fields (some have defaults from context)
4. EXECUTE     → Call the wizard's action method (e.g., action_create_payments)
5. RESULT      → Handle the result (action dict, record ID, or None)
6. CLEANUP     → Transient records auto-delete (Odoo handles this)
```

---

## 3. Wizard Detection

**REQ-05a-02**: A wizard is detected when an `execute_kw` call returns an **action dictionary** with `res_model` pointing to a TransientModel:

```python
def is_wizard_action(result: Any) -> bool:
    """Check if an execute_kw result is a wizard action."""
    if not isinstance(result, dict):
        return False
    return (
        result.get('type') == 'ir.actions.act_window'
        and result.get('target') == 'new'  # Wizards open in "new" (dialog) target
        # Additional check: query ir.model to confirm transient
    )
```

**REQ-05a-03**: When a workflow tool encounters a wizard action, it MUST:
1. Check the known wizard catalog (REQ-05a-08) for the wizard model.
2. If known: handle automatically using the cataloged procedure.
3. If unknown: return the wizard details to the LLM for manual handling.

---

## 4. Wizard Execution Protocol

**REQ-05a-04**: The standard wizard execution sequence:

```python
async def execute_wizard(
    connection: OdooProtocol,
    wizard_model: str,
    wizard_values: dict,
    action_method: str,
    source_model: str | None = None,
    source_ids: list[int] | None = None,
) -> Any:
    """Execute an Odoo wizard."""

    # Step 1: Build context
    context = {}
    if source_model and source_ids:
        context['active_model'] = source_model
        context['active_ids'] = source_ids
        context['active_id'] = source_ids[0] if source_ids else False

    # Step 2: Get defaults
    defaults = await connection.execute_kw(
        wizard_model, 'default_get',
        [list(wizard_values.keys())],
        context=context,
    )

    # Step 3: Merge defaults with provided values
    merged_values = {**defaults, **wizard_values}

    # Step 4: Create wizard record
    wizard_id = await connection.execute_kw(
        wizard_model, 'create',
        [merged_values],
        context=context,
    )

    # Step 5: Execute wizard action
    result = await connection.execute_kw(
        wizard_model, action_method,
        [[wizard_id]],
        context=context,
    )

    return result
```

---

## 5. Context Passing

**REQ-05a-05**: The context passed to wizard creation is critical. Most wizards rely on these context keys:

| Context Key | Type | Description |
|------------|------|-------------|
| `active_model` | string | Source model name (e.g., `'account.move'`) |
| `active_id` | int | ID of the primary source record |
| `active_ids` | list[int] | IDs of all selected source records |
| `active_domain` | list | Domain used to select source records (rare) |
| `default_*` | any | Pre-filled wizard field values (e.g., `default_journal_id`) |

**REQ-05a-06**: When a workflow tool triggers a wizard, it MUST pass the correct context. The context is typically built from the tool's input parameters:

```python
# Example: Registering payment for invoices
context = {
    'active_model': 'account.move',
    'active_ids': invoice_ids,
    'active_id': invoice_ids[0],
}
```

---

## 6. Wizard Result Handling

**REQ-05a-07**: Wizard action methods can return several types of results:

| Result Type | How to Detect | How to Handle |
|------------|---------------|---------------|
| `None`/`True`/`False` | Not a dict | Operation complete. Refresh source records. |
| Action dict (form view) | `type == 'ir.actions.act_window'` | May be another wizard (chain) or a view to display. |
| Action dict (close) | `type == 'ir.actions.act_window_close'` | Dialog should close. Operation complete. |
| Action dict (report) | `type == 'ir.actions.report'` | A report was generated. |
| Action dict (URL) | `type == 'ir.actions.act_url'` | External URL to open. |

For wizard chains (result is another wizard action), the server MUST:
1. Check if the next wizard is in the known catalog.
2. If yes, execute it automatically.
3. If no, return the chain details to the LLM.
4. Maximum chain depth: 3 (to prevent infinite loops).

---

## 7. Known Wizard Catalog

**REQ-05a-08**: The server MUST maintain a catalog of known wizards with their parameters and execution procedures:

### 7.1 account.payment.register (Payment Registration)

```python
KnownWizard(
    model='account.payment.register',
    description='Register payment for invoices',
    source_model='account.move',
    action_method='action_create_payments',
    fields={
        'journal_id': WizardField(type='many2one', relation='account.journal', required=True, description='Payment journal (bank/cash)'),
        'amount': WizardField(type='monetary', required=False, description='Payment amount. Default: full invoice amount.'),
        'payment_date': WizardField(type='date', required=True, description='Payment date. Default: today.'),
        'payment_method_line_id': WizardField(type='many2one', relation='account.payment.method.line', required=True, description='Payment method'),
        'communication': WizardField(type='char', required=False, description='Payment memo/reference'),
        'group_payment': WizardField(type='boolean', required=False, description='Group payments for same partner'),
    },
    context_keys=['active_model', 'active_ids'],
)
```

### 7.2 stock.immediate.transfer (Immediate Transfer)

```python
KnownWizard(
    model='stock.immediate.transfer',
    description='Process all quantities immediately (no backorder)',
    source_model='stock.picking',
    action_method='process',
    fields={
        'pick_ids': WizardField(type='many2many', relation='stock.picking', required=True, description='Pickings to process'),
    },
    context_keys=['active_model', 'active_ids', 'button_validate_picking_ids'],
)
```

### 7.3 stock.backorder.confirmation (Backorder Confirmation)

```python
KnownWizard(
    model='stock.backorder.confirmation',
    description='Create backorder for remaining quantities',
    source_model='stock.picking',
    action_method='process',  # or process_cancel_backorder
    fields={
        'pick_ids': WizardField(type='many2many', relation='stock.picking', required=True),
        'backorder_confirmation_line_ids': WizardField(type='one2many', required=False),
    },
    context_keys=['active_model', 'active_ids', 'button_validate_picking_ids'],
    alternative_actions={
        'process': 'Create backorder for remaining items',
        'process_cancel_backorder': 'Process without backorder (ignore remaining)',
    },
)
```

### 7.4 sale.advance.payment.inv (Create Invoice from SO)

```python
KnownWizard(
    model='sale.advance.payment.inv',
    description='Create invoice from sales order',
    source_model='sale.order',
    action_method='create_invoices',
    fields={
        'advance_payment_method': WizardField(
            type='selection',
            required=True,
            selection=[
                ('delivered', 'Regular invoice (delivered quantities)'),
                ('percentage', 'Down payment (percentage)'),
                ('fixed', 'Down payment (fixed amount)'),
            ],
            description='Invoicing method',
        ),
        'amount': WizardField(type='float', required=False, description='Down payment amount (for percentage/fixed)'),
    },
    context_keys=['active_model', 'active_ids'],
)
```

### 7.5 crm.lead2opportunity.partner (Convert Lead to Opportunity)

```python
KnownWizard(
    model='crm.lead2opportunity.partner',
    description='Convert a CRM lead into an opportunity',
    source_model='crm.lead',
    action_method='action_apply',
    fields={
        'name': WizardField(type='selection', required=True, selection=[
            ('convert', 'Convert to opportunity'),
            ('merge', 'Merge with existing opportunity'),
        ]),
        'action': WizardField(type='selection', required=True, selection=[
            ('create', 'Create a new customer'),
            ('exist', 'Link to an existing customer'),
            ('nothing', 'Do not create a customer'),
        ]),
        'partner_id': WizardField(type='many2one', relation='res.partner', required=False, description='Existing customer to link'),
        'user_id': WizardField(type='many2one', relation='res.users', required=False, description='Salesperson'),
        'team_id': WizardField(type='many2one', relation='crm.team', required=False, description='Sales team'),
    },
    context_keys=['active_model', 'active_id', 'active_ids'],
)
```

### 7.6 account.move.reversal (Invoice Reversal / Credit Note)

```python
KnownWizard(
    model='account.move.reversal',
    description='Create a credit note / reversal for an invoice',
    source_model='account.move',
    action_method='reverse_moves',
    fields={
        'reason': WizardField(type='char', required=False, description='Reason for reversal'),
        'date': WizardField(type='date', required=True, description='Reversal date. Default: today.'),
        'refund_method': WizardField(type='selection', required=True, selection=[
            ('refund', 'Partial refund - create credit note'),
            ('cancel', 'Full refund - create credit note and reconcile'),
            ('modify', 'Full refund - create credit note, reconcile, and create new draft invoice'),
        ]),
        'journal_id': WizardField(type='many2one', relation='account.journal', required=False),
    },
    context_keys=['active_model', 'active_ids'],
)
```

---

## 8. Unknown Wizard Handling

**REQ-05a-09**: When an unknown wizard is encountered, the server MUST return a structured response:

```json
{
  "wizard_required": true,
  "wizard_model": "custom.wizard.model",
  "wizard_action": {
    "type": "ir.actions.act_window",
    "res_model": "custom.wizard.model",
    "target": "new",
    "view_mode": "form"
  },
  "wizard_fields": {
    "field_a": {"type": "char", "required": true, "label": "Field A"},
    "field_b": {"type": "many2one", "required": false, "relation": "res.partner"}
  },
  "instructions": "This operation requires a wizard. To complete it: 1) Create a wizard record using odoo_core_create with model='custom.wizard.model' and the required field values. 2) Execute the wizard using odoo_core_execute with model='custom.wizard.model', method='action_apply' (check available methods), and args=[[wizard_id]].",
  "context_hint": {
    "active_model": "source.model",
    "active_ids": [1, 2, 3]
  }
}
```

**REQ-05a-10**: The server MUST attempt to discover the wizard's fields via `fields_get` to populate the `wizard_fields` section, even for unknown wizards.

---

## 9. Wizard Data Classes

**REQ-05a-11**: Internal data structures for the wizard catalog:

```python
@dataclass
class WizardField:
    type: str                               # Odoo field type
    required: bool = False
    description: str = ""
    relation: str | None = None             # For relational fields
    selection: list[tuple[str, str]] | None = None  # For selection fields
    default: Any = None

@dataclass
class KnownWizard:
    model: str                              # Wizard model name
    description: str                        # Human-readable description
    source_model: str                       # Model that triggers this wizard
    action_method: str                      # Main action method to call
    fields: dict[str, WizardField]          # Wizard fields
    context_keys: list[str]                 # Required context keys
    alternative_actions: dict[str, str] | None = None  # Other callable methods
    min_odoo_version: int = 14              # Minimum version
    max_odoo_version: int | None = None     # Maximum version
```
