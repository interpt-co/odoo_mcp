"""Wizard Execution Protocol.

Implements wizard detection, execution, known wizard catalog,
and unknown wizard handling per SPEC-L2-05a.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from odoo_mcp.connection.manager import ConnectionManager

logger = logging.getLogger("odoo_mcp.wizard")

MAX_WIZARD_CHAIN_DEPTH = 3


# ---------------------------------------------------------------------------
# Data classes (REQ-05a-11)
# ---------------------------------------------------------------------------

@dataclass
class WizardField:
    """Describes a single field in a wizard."""

    type: str
    required: bool = False
    description: str = ""
    relation: str | None = None
    selection: list[tuple[str, str]] | None = None
    default: Any = None


@dataclass
class KnownWizard:
    """Catalog entry for a known Odoo wizard."""

    model: str
    description: str
    source_model: str
    action_method: str
    fields: dict[str, WizardField]
    context_keys: list[str]
    alternative_actions: dict[str, str] | None = None
    min_odoo_version: int = 14
    max_odoo_version: int | None = None


# ---------------------------------------------------------------------------
# Known Wizard Catalog (REQ-05a-08)
# ---------------------------------------------------------------------------

KNOWN_WIZARDS: dict[str, KnownWizard] = {
    "account.payment.register": KnownWizard(
        model="account.payment.register",
        description="Register payment for invoices",
        source_model="account.move",
        action_method="action_create_payments",
        fields={
            "journal_id": WizardField(
                type="many2one",
                relation="account.journal",
                required=True,
                description="Payment journal (bank/cash)",
            ),
            "amount": WizardField(
                type="monetary",
                required=False,
                description="Payment amount. Default: full invoice amount.",
            ),
            "payment_date": WizardField(
                type="date",
                required=True,
                description="Payment date. Default: today.",
            ),
            "payment_method_line_id": WizardField(
                type="many2one",
                relation="account.payment.method.line",
                required=True,
                description="Payment method",
            ),
            "communication": WizardField(
                type="char",
                required=False,
                description="Payment memo/reference",
            ),
            "group_payment": WizardField(
                type="boolean",
                required=False,
                description="Group payments for same partner",
            ),
        },
        context_keys=["active_model", "active_ids"],
    ),
    "stock.immediate.transfer": KnownWizard(
        model="stock.immediate.transfer",
        description="Process all quantities immediately (no backorder). Only exists in v15-v16.",
        source_model="stock.picking",
        action_method="process",
        fields={
            "pick_ids": WizardField(
                type="many2many",
                relation="stock.picking",
                required=True,
                description="Pickings to process",
            ),
        },
        context_keys=["active_model", "active_ids", "button_validate_picking_ids"],
        max_odoo_version=16,
    ),
    "stock.backorder.confirmation": KnownWizard(
        model="stock.backorder.confirmation",
        description="Create backorder for remaining quantities",
        source_model="stock.picking",
        action_method="process",
        fields={
            "pick_ids": WizardField(
                type="many2many",
                relation="stock.picking",
                required=True,
            ),
            "backorder_confirmation_line_ids": WizardField(
                type="one2many",
                required=False,
            ),
        },
        context_keys=["active_model", "active_ids", "button_validate_picking_ids"],
        alternative_actions={
            "process": "Create backorder for remaining items",
            "process_cancel_backorder": "Process without backorder (ignore remaining)",
        },
    ),
    "sale.advance.payment.inv": KnownWizard(
        model="sale.advance.payment.inv",
        description="Create invoice from sales order",
        source_model="sale.order",
        action_method="create_invoices",
        fields={
            "advance_payment_method": WizardField(
                type="selection",
                required=True,
                selection=[
                    ("delivered", "Regular invoice (delivered quantities)"),
                    ("percentage", "Down payment (percentage)"),
                    ("fixed", "Down payment (fixed amount)"),
                ],
                description="Invoicing method",
            ),
            "amount": WizardField(
                type="float",
                required=False,
                description="Down payment amount (for percentage/fixed)",
            ),
        },
        context_keys=["active_model", "active_ids"],
    ),
    "crm.lead2opportunity.partner": KnownWizard(
        model="crm.lead2opportunity.partner",
        description="Convert a CRM lead into an opportunity",
        source_model="crm.lead",
        action_method="action_apply",
        fields={
            "name": WizardField(
                type="selection",
                required=True,
                selection=[
                    ("convert", "Convert to opportunity"),
                    ("merge", "Merge with existing opportunity"),
                ],
            ),
            "action": WizardField(
                type="selection",
                required=True,
                selection=[
                    ("create", "Create a new customer"),
                    ("exist", "Link to an existing customer"),
                    ("nothing", "Do not create a customer"),
                ],
            ),
            "partner_id": WizardField(
                type="many2one",
                relation="res.partner",
                required=False,
                description="Existing customer to link",
            ),
            "user_id": WizardField(
                type="many2one",
                relation="res.users",
                required=False,
                description="Salesperson",
            ),
            "team_id": WizardField(
                type="many2one",
                relation="crm.team",
                required=False,
                description="Sales team",
            ),
        },
        context_keys=["active_model", "active_id", "active_ids"],
    ),
    "account.move.reversal": KnownWizard(
        model="account.move.reversal",
        description="Create a credit note / reversal for an invoice",
        source_model="account.move",
        action_method="reverse_moves",
        fields={
            "reason": WizardField(
                type="char",
                required=False,
                description="Reason for reversal",
            ),
            "date": WizardField(
                type="date",
                required=True,
                description="Reversal date. Default: today.",
            ),
            "refund_method": WizardField(
                type="selection",
                required=True,
                selection=[
                    ("refund", "Partial refund - create credit note"),
                    ("cancel", "Full refund - create credit note and reconcile"),
                    (
                        "modify",
                        "Full refund - create credit note, reconcile, "
                        "and create new draft invoice",
                    ),
                ],
            ),
            "journal_id": WizardField(
                type="many2one",
                relation="account.journal",
                required=False,
            ),
        },
        context_keys=["active_model", "active_ids"],
    ),
}


# ---------------------------------------------------------------------------
# Wizard Detection (REQ-05a-02)
# ---------------------------------------------------------------------------

def is_wizard_action(result: Any) -> bool:
    """Check if an execute_kw result is a wizard action.

    A wizard action is an action dict with type 'ir.actions.act_window'
    and target 'new' (dialog).
    """
    if not isinstance(result, dict):
        return False
    return (
        result.get("type") == "ir.actions.act_window"
        and result.get("target") == "new"
    )


def get_wizard_model(action: dict[str, Any]) -> str | None:
    """Extract the wizard model name from an action dict."""
    if not is_wizard_action(action):
        return None
    return action.get("res_model")


def is_known_wizard(model: str) -> bool:
    """Check if a wizard model is in the known catalog."""
    return model in KNOWN_WIZARDS


def get_known_wizard(model: str) -> KnownWizard | None:
    """Retrieve catalog entry for a known wizard."""
    return KNOWN_WIZARDS.get(model)


# ---------------------------------------------------------------------------
# Wizard Execution Protocol (REQ-05a-04)
# ---------------------------------------------------------------------------

async def execute_wizard(
    connection: ConnectionManager,
    wizard_model: str,
    wizard_values: dict[str, Any],
    action_method: str,
    source_model: str | None = None,
    source_ids: list[int] | None = None,
    context_extra: dict[str, Any] | None = None,
) -> Any:
    """Execute an Odoo wizard following the standard lifecycle.

    1. Build context (active_model, active_ids, active_id)
    2. Get defaults via default_get
    3. Merge defaults with provided values
    4. Create wizard record
    5. Execute wizard action method
    6. Return result
    """
    # Step 1: Build context (REQ-05a-05, REQ-05a-06)
    context: dict[str, Any] = {}
    if source_model and source_ids:
        context["active_model"] = source_model
        context["active_ids"] = source_ids
        context["active_id"] = source_ids[0] if source_ids else False
    if context_extra:
        context.update(context_extra)

    # Step 2: Get defaults
    field_names = list(wizard_values.keys())
    # Also include fields from the known wizard catalog if available
    known = get_known_wizard(wizard_model)
    if known:
        for fname in known.fields:
            if fname not in field_names:
                field_names.append(fname)

    defaults = await connection.execute_kw(
        wizard_model,
        "default_get",
        [field_names],
        context=context,
    )

    # Step 3: Merge defaults with provided values
    merged_values = {**(defaults or {}), **wizard_values}

    # Step 4: Create wizard record
    wizard_id = await connection.execute_kw(
        wizard_model,
        "create",
        [merged_values],
        context=context,
    )

    # Step 5: Execute wizard action
    result = await connection.execute_kw(
        wizard_model,
        action_method,
        [[wizard_id]],
        context=context,
    )

    return result


# ---------------------------------------------------------------------------
# Wizard Result Handling (REQ-05a-07)
# ---------------------------------------------------------------------------

def classify_wizard_result(result: Any) -> str:
    """Classify a wizard execution result.

    Returns one of: 'complete', 'wizard_chain', 'close', 'report', 'url'
    """
    if result is None or isinstance(result, bool):
        return "complete"

    if not isinstance(result, dict):
        return "complete"

    action_type = result.get("type", "")

    if action_type == "ir.actions.act_window_close":
        return "close"

    if action_type == "ir.actions.act_window" and result.get("target") == "new":
        return "wizard_chain"

    if action_type == "ir.actions.report":
        return "report"

    if action_type == "ir.actions.act_url":
        return "url"

    # Any other action dict (e.g., redirect to a view)
    if action_type:
        return "complete"

    return "complete"


async def handle_wizard_result(
    connection: ConnectionManager,
    result: Any,
    depth: int = 0,
) -> dict[str, Any]:
    """Handle the result of a wizard execution, including chains.

    Wizard chains are followed up to MAX_WIZARD_CHAIN_DEPTH to prevent
    infinite loops (REQ-05a-07).
    """
    result_type = classify_wizard_result(result)

    if result_type == "complete" or result_type == "close":
        return {
            "status": "success",
            "result_type": result_type,
            "message": "Operation completed successfully.",
        }

    if result_type == "report":
        return {
            "status": "success",
            "result_type": "report",
            "report_action": result,
            "message": "Report generated.",
        }

    if result_type == "url":
        return {
            "status": "success",
            "result_type": "url",
            "url": result.get("url", ""),
            "message": "External URL action returned.",
        }

    if result_type == "wizard_chain":
        if depth >= MAX_WIZARD_CHAIN_DEPTH:
            return {
                "status": "error",
                "message": (
                    f"Wizard chain exceeded maximum depth of "
                    f"{MAX_WIZARD_CHAIN_DEPTH}. Stopping to prevent "
                    f"infinite loop."
                ),
                "wizard_action": result,
            }

        next_model = result.get("res_model", "")
        if not next_model:
            return {
                "status": "error",
                "message": "Wizard chain action has no res_model.",
                "wizard_action": result,
            }

        # REQ-05a-03: Check if the chained wizard is known
        if is_known_wizard(next_model):
            known = KNOWN_WIZARDS[next_model]
            logger.info(
                "Auto-handling chained wizard %s (depth %d)",
                next_model,
                depth + 1,
            )
            chain_result = await execute_wizard(
                connection=connection,
                wizard_model=next_model,
                wizard_values={},
                action_method=known.action_method,
            )
            return await handle_wizard_result(
                connection, chain_result, depth=depth + 1
            )

        # Unknown chained wizard - return details to LLM
        return await build_unknown_wizard_response(connection, next_model, result)

    return {"status": "success", "result_type": "unknown"}


# ---------------------------------------------------------------------------
# Unknown Wizard Handling (REQ-05a-09, REQ-05a-10)
# ---------------------------------------------------------------------------

async def build_unknown_wizard_response(
    connection: ConnectionManager,
    wizard_model: str,
    action: dict[str, Any],
    source_model: str | None = None,
    source_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Build a structured response for an unknown wizard.

    Attempts to discover the wizard's fields via fields_get (REQ-05a-10).
    """
    wizard_fields: dict[str, Any] = {}
    try:
        raw_fields = await connection.execute_kw(
            wizard_model, "fields_get", [], kwargs={"attributes": ["type", "required", "string", "relation", "selection"]}
        )
        if isinstance(raw_fields, dict):
            for fname, finfo in raw_fields.items():
                if fname.startswith("__") or fname in (
                    "id",
                    "create_uid",
                    "create_date",
                    "write_uid",
                    "write_date",
                    "display_name",
                ):
                    continue
                wizard_fields[fname] = {
                    "type": finfo.get("type", "unknown"),
                    "required": finfo.get("required", False),
                    "label": finfo.get("string", fname),
                }
                if finfo.get("relation"):
                    wizard_fields[fname]["relation"] = finfo["relation"]
                if finfo.get("selection"):
                    wizard_fields[fname]["selection"] = finfo["selection"]
    except Exception:
        logger.warning("Could not fetch fields_get for wizard %s", wizard_model)

    context_hint: dict[str, Any] = {}
    if source_model:
        context_hint["active_model"] = source_model
    if source_ids:
        context_hint["active_ids"] = source_ids
        context_hint["active_id"] = source_ids[0] if source_ids else False

    return {
        "wizard_required": True,
        "wizard_model": wizard_model,
        "wizard_action": {
            "type": action.get("type", "ir.actions.act_window"),
            "res_model": wizard_model,
            "target": action.get("target", "new"),
            "view_mode": action.get("view_mode", "form"),
        },
        "wizard_fields": wizard_fields,
        "instructions": (
            f"This operation requires a wizard. To complete it: "
            f"1) Create a wizard record using odoo_core_create with "
            f"model='{wizard_model}' and the required field values. "
            f"2) Execute the wizard using odoo_core_execute with "
            f"model='{wizard_model}', method='<action_method>' "
            f"(check available methods), and args=[[wizard_id]]."
        ),
        "context_hint": context_hint,
    }


# ---------------------------------------------------------------------------
# High-level wizard encounter handler (REQ-05a-03)
# ---------------------------------------------------------------------------

async def handle_wizard_encounter(
    connection: ConnectionManager,
    result: Any,
    source_model: str | None = None,
    source_ids: list[int] | None = None,
) -> dict[str, Any] | None:
    """Handle a wizard encountered during a workflow tool execution.

    Returns None if the result is not a wizard action.
    Returns a dict response if it is a wizard (either auto-handled or guidance).
    """
    if not is_wizard_action(result):
        return None

    wizard_model = get_wizard_model(result)
    if not wizard_model:
        return None

    # Known wizard -> handle automatically
    if is_known_wizard(wizard_model):
        known = KNOWN_WIZARDS[wizard_model]
        logger.info("Auto-handling known wizard: %s", wizard_model)
        wizard_result = await execute_wizard(
            connection=connection,
            wizard_model=wizard_model,
            wizard_values={},
            action_method=known.action_method,
            source_model=source_model,
            source_ids=source_ids,
        )
        return await handle_wizard_result(connection, wizard_result)

    # Unknown wizard -> return structured guidance
    return await build_unknown_wizard_response(
        connection, wizard_model, result, source_model, source_ids
    )
