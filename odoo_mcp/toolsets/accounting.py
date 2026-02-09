"""Accounting Toolset.

Implements invoice and payment workflows per SPEC-05 (REQ-05-11 through REQ-05-17).

account.move states:
  draft -> [action_post] -> posted
  posted -> [button_draft] -> draft (Reset to Draft)
  posted -> [button_cancel] -> cancel (if allowed)
"""

from __future__ import annotations

import logging
from typing import Any

from odoo_mcp.connection.manager import ConnectionManager
from odoo_mcp.toolsets.base import BaseToolset, ToolsetMetadata
from odoo_mcp.toolsets.formatting import format_many2one
from odoo_mcp.toolsets.helpers import resolve_partner, resolve_product, resolve_order
from odoo_mcp.toolsets.wizard import execute_wizard

logger = logging.getLogger("odoo_mcp.toolsets.accounting")


class AccountingToolset(BaseToolset):
    """Accounting invoice and payment workflow tools."""

    def metadata(self) -> ToolsetMetadata:
        return ToolsetMetadata(
            name="accounting",
            description="Invoice and payment workflows",
            required_modules=["account"],
            depends_on=["core"],
        )

    def register_tools(
        self, server: Any, connection: ConnectionManager
    ) -> list[str]:

        @server.tool()
        async def odoo_accounting_create_invoice(
            move_type: str = "out_invoice",
            partner_id: int | None = None,
            partner_name: str | None = None,
            lines: list[dict[str, Any]] | None = None,
            invoice_date: str | None = None,
            journal_id: int | None = None,
            currency_id: int | None = None,
            ref: str | None = None,
            post: bool = False,
        ) -> dict[str, Any]:
            """Create a customer or vendor invoice (REQ-05-11).

            move_type: out_invoice (Customer Invoice), out_refund (Credit Note),
                       in_invoice (Vendor Bill), in_refund (Vendor Credit Note).
            Lines use (0, 0, values) on invoice_line_ids (REQ-05-12).
            Set post=True to also post (validate) the invoice.

            account.move states:
              draft -> [action_post] -> posted
              posted -> [button_draft] -> draft
            """
            resolved = await resolve_partner(connection, partner_id, partner_name)
            if isinstance(resolved, dict):
                return resolved
            partner_id = resolved

            move_vals: dict[str, Any] = {
                "move_type": move_type,
                "partner_id": partner_id,
            }
            if invoice_date:
                move_vals["invoice_date"] = invoice_date
            if journal_id:
                move_vals["journal_id"] = journal_id
            if currency_id:
                move_vals["currency_id"] = currency_id
            if ref:
                move_vals["ref"] = ref

            # Build invoice lines (REQ-05-12)
            if lines:
                inv_lines = []
                for line in lines:
                    line_vals: dict[str, Any] = {}

                    if line.get("product_id") or line.get("product_name"):
                        prod_resolved = await resolve_product(
                            connection,
                            line.get("product_id"),
                            line.get("product_name"),
                        )
                        if isinstance(prod_resolved, dict):
                            return prod_resolved
                        line_vals["product_id"] = prod_resolved

                    if "quantity" in line:
                        line_vals["quantity"] = line["quantity"]
                    if "price_unit" in line:
                        line_vals["price_unit"] = line["price_unit"]
                    if "name" in line:
                        line_vals["name"] = line["name"]
                    if "account_id" in line:
                        line_vals["account_id"] = line["account_id"]
                    if "tax_ids" in line:
                        line_vals["tax_ids"] = [(6, 0, line["tax_ids"])]

                    inv_lines.append((0, 0, line_vals))

                move_vals["invoice_line_ids"] = inv_lines

            invoice_id = await connection.execute_kw(
                "account.move", "create", [move_vals]
            )

            # Optionally post
            posted = False
            if post:
                try:
                    await connection.execute_kw(
                        "account.move", "action_post", [[invoice_id]]
                    )
                    posted = True
                except Exception as exc:
                    logger.warning("Failed to post invoice %d: %s", invoice_id, exc)

            # Read back (REQ-05-13)
            invoices = await connection.search_read(
                "account.move",
                [("id", "=", invoice_id)],
                fields=[
                    "name",
                    "state",
                    "partner_id",
                    "amount_untaxed",
                    "amount_tax",
                    "amount_total",
                    "move_type",
                ],
            )
            inv = invoices[0] if invoices else {}

            return {
                "id": invoice_id,
                "name": inv.get("name", ""),
                "state": inv.get("state", "draft"),
                "move_type": inv.get("move_type", move_type),
                "partner": format_many2one(inv.get("partner_id")),
                "amount_untaxed": inv.get("amount_untaxed", 0),
                "amount_tax": inv.get("amount_tax", 0),
                "amount_total": inv.get("amount_total", 0),
                "posted": posted,
                "message": f"Created invoice {inv.get('name', '')}",
            }

        @server.tool()
        async def odoo_accounting_post_invoice(
            invoice_id: int | None = None,
            invoice_name: str | None = None,
        ) -> dict[str, Any]:
            """Post (validate) a draft invoice (REQ-05-14).

            Calls action_post. Handles validation errors (missing tax,
            unbalanced entries) with explanatory messages (REQ-05-15).

            account.move states:
              draft -> [action_post] -> posted
            """
            resolved = await resolve_order(
                connection, "account.move", invoice_id, invoice_name
            )
            if isinstance(resolved, dict):
                return resolved
            invoice_id = resolved

            invoices = await connection.search_read(
                "account.move",
                [("id", "=", invoice_id)],
                fields=["name", "state"],
            )
            if not invoices:
                return {"status": "error", "message": f"Invoice {invoice_id} not found."}

            inv = invoices[0]
            if inv["state"] != "draft":
                return {
                    "status": "error",
                    "message": (
                        f"Cannot post invoice {inv['name']}: "
                        f"current state is '{inv['state']}'. "
                        f"Only draft invoices can be posted."
                    ),
                }

            try:
                await connection.execute_kw(
                    "account.move", "action_post", [[invoice_id]]
                )
            except Exception as exc:
                error_msg = str(exc)
                suggestion = ""
                if "tax" in error_msg.lower():
                    suggestion = (
                        " Ensure all invoice lines have the correct taxes applied."
                    )
                elif "balance" in error_msg.lower() or "unbalanced" in error_msg.lower():
                    suggestion = (
                        " The journal entry is unbalanced. Check that debit "
                        "and credit amounts match."
                    )
                return {
                    "status": "error",
                    "message": f"Failed to post invoice {inv['name']}: {error_msg}.{suggestion}",
                }

            return {
                "id": invoice_id,
                "name": inv["name"],
                "state": "posted",
                "message": f"Invoice {inv['name']} posted successfully.",
            }

        @server.tool()
        async def odoo_accounting_register_payment(
            invoice_ids: list[int] | None = None,
            amount: float | None = None,
            journal_id: int | None = None,
            payment_date: str | None = None,
            payment_method: str | None = None,
        ) -> dict[str, Any]:
            """Register a payment for one or more invoices (REQ-05-16).

            Uses the account.payment.register wizard via the wizard protocol
            (REQ-05-17). Auto-selects the first bank journal if not specified.

            Context: active_model='account.move', active_ids=invoice_ids
            """
            if not invoice_ids:
                return {"status": "error", "message": "invoice_ids is required."}

            wizard_values: dict[str, Any] = {}
            if amount is not None:
                wizard_values["amount"] = amount
            if journal_id is not None:
                wizard_values["journal_id"] = journal_id
            if payment_date:
                wizard_values["payment_date"] = payment_date

            try:
                result = await execute_wizard(
                    connection=connection,
                    wizard_model="account.payment.register",
                    wizard_values=wizard_values,
                    action_method="action_create_payments",
                    source_model="account.move",
                    source_ids=invoice_ids,
                )
            except Exception as exc:
                return {
                    "status": "error",
                    "message": f"Payment registration failed: {exc}",
                }

            return {
                "status": "success",
                "invoice_ids": invoice_ids,
                "message": (
                    f"Payment registered for {len(invoice_ids)} invoice(s)."
                ),
                "result": result,
            }

        return [
            "odoo_accounting_create_invoice",
            "odoo_accounting_post_invoice",
            "odoo_accounting_register_payment",
        ]
