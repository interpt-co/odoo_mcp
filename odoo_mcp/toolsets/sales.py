"""Sales Toolset.

Implements sales order workflows per SPEC-05 (REQ-05-01 through REQ-05-10, REQ-05-37).

sale.order states (v15-v16):
  draft (Quotation) -> sent -> [action_confirm] -> sale (Sales Order)
  sale -> [action_done] -> done (Locked)
  draft/sent/sale -> [action_cancel] -> cancel
  cancel -> [action_draft] -> draft (Reset to Draft)

sale.order states (v17+):
  draft (Quotation) -> sent -> [action_confirm] -> sale (Sales Order)
  sale -> [action_lock] -> sale (locked=True)
  draft/sent/sale -> [action_cancel] -> cancel
  cancel -> [action_draft] -> draft (Reset to Draft)
  Note: 'done' state was removed in v17; replaced by 'locked' boolean field.
"""

from __future__ import annotations

import logging
from typing import Any

from odoo_mcp.connection.manager import ConnectionManager
from odoo_mcp.toolsets.base import BaseToolset, ToolsetMetadata
from odoo_mcp.toolsets.formatting import format_many2one
from odoo_mcp.toolsets.helpers import resolve_partner, resolve_product, resolve_order

logger = logging.getLogger("odoo_mcp.toolsets.sales")

STATE_MACHINE_DOC = """
sale.order states (v15-v16):
  draft (Quotation) -> sent -> [action_confirm] -> sale (Sales Order)
  sale -> [action_done] -> done (Locked)
  draft/sent/sale -> [action_cancel] -> cancel
  cancel -> [action_draft] -> draft (Reset to Draft)

sale.order states (v17+):
  draft (Quotation) -> sent -> [action_confirm] -> sale (Sales Order)
  sale -> [action_lock] -> sale (locked=True)
  draft/sent/sale -> [action_cancel] -> cancel
  cancel -> [action_draft] -> draft (Reset to Draft)
  Note: 'done' state removed in v17; replaced by 'locked' boolean field.
"""


class SalesToolset(BaseToolset):
    """Sales order workflow tools."""

    def metadata(self) -> ToolsetMetadata:
        return ToolsetMetadata(
            name="sales",
            description="Sales order workflows",
            required_modules=["sale"],
            depends_on=["core"],
        )

    async def register_tools(
        self, server: Any, connection: ConnectionManager, **kwargs: Any
    ) -> list[str]:
        """Register sales tools with the MCP server."""

        @server.tool()
        async def odoo_sales_create_order(
            partner_id: int | None = None,
            partner_name: str | None = None,
            lines: list[dict[str, Any]] | None = None,
            date_order: str | None = None,
            pricelist_id: int | None = None,
            warehouse_id: int | None = None,
            note: str | None = None,
            confirm: bool = False,
        ) -> dict[str, Any]:
            """Create a sales order with optional order lines.

            Accepts partner_id or partner_name (resolved via name_search).
            Lines accept product_id or product_name, quantity, price_unit, discount, name.
            Set confirm=True to also confirm the order.

            sale.order states:
              draft (Quotation) -> sent -> [action_confirm] -> sale (Sales Order)
              v15-v16: sale -> [action_done] -> done (Locked)
              v17+: sale -> [action_lock] -> sale (locked=True)
              draft/sent/sale -> [action_cancel] -> cancel
              cancel -> [action_draft] -> draft (Reset to Draft)
            """
            # Resolve partner
            resolved = await resolve_partner(connection, partner_id, partner_name)
            if isinstance(resolved, dict):
                return resolved
            partner_id = resolved

            # Build order values
            order_vals: dict[str, Any] = {"partner_id": partner_id}
            if date_order:
                order_vals["date_order"] = date_order
            if pricelist_id:
                order_vals["pricelist_id"] = pricelist_id
            if warehouse_id:
                order_vals["warehouse_id"] = warehouse_id
            if note:
                order_vals["note"] = note

            # Resolve and build order lines (REQ-05-03)
            if lines:
                order_lines = []
                for line in lines:
                    line_vals: dict[str, Any] = {}

                    # Resolve product
                    prod_resolved = await resolve_product(
                        connection,
                        line.get("product_id"),
                        line.get("product_name"),
                    )
                    if isinstance(prod_resolved, dict):
                        return prod_resolved
                    line_vals["product_id"] = prod_resolved

                    if "quantity" in line:
                        line_vals["product_uom_qty"] = line["quantity"]
                    if "price_unit" in line:
                        line_vals["price_unit"] = line["price_unit"]
                    if "discount" in line:
                        line_vals["discount"] = line["discount"]
                    if "name" in line:
                        line_vals["name"] = line["name"]

                    order_lines.append((0, 0, line_vals))

                order_vals["order_line"] = order_lines

            # Create order
            order_id = await connection.execute_kw(
                "sale.order", "create", [order_vals]
            )

            # Optionally confirm
            confirmed = False
            if confirm:
                await connection.execute_kw(
                    "sale.order", "action_confirm", [[order_id]]
                )
                confirmed = True

            # Read back order details (REQ-05-04)
            orders = await connection.search_read(
                "sale.order",
                [("id", "=", order_id)],
                fields=[
                    "name",
                    "state",
                    "partner_id",
                    "amount_total",
                    "order_line",
                ],
            )
            order = orders[0] if orders else {}

            # Read lines
            line_ids = order.get("order_line", [])
            result_lines = []
            if line_ids:
                result_lines_data = await connection.search_read(
                    "sale.order.line",
                    [("id", "in", line_ids)],
                    fields=[
                        "id",
                        "product_id",
                        "product_uom_qty",
                        "price_unit",
                        "price_subtotal",
                    ],
                )
                for rl in result_lines_data:
                    prod = format_many2one(rl.get("product_id"))
                    result_lines.append({
                        "id": rl["id"],
                        "product": prod["name"] if prod else "",
                        "quantity": rl.get("product_uom_qty", 0),
                        "price_unit": rl.get("price_unit", 0),
                        "subtotal": rl.get("price_subtotal", 0),
                    })

            return {
                "id": order_id,
                "name": order.get("name", ""),
                "state": order.get("state", "draft"),
                "partner": format_many2one(order.get("partner_id")),
                "lines": result_lines,
                "amount_total": order.get("amount_total", 0),
                "confirmed": confirmed,
                "message": (
                    f"Created sales order {order.get('name', '')} "
                    f"with {len(result_lines)} line(s)"
                ),
            }

        @server.tool()
        async def odoo_sales_confirm_order(
            order_id: int | None = None,
            order_name: str | None = None,
        ) -> dict[str, Any]:
            """Confirm a draft sales order (action_confirm).

            The order must be in 'draft' or 'sent' state.

            sale.order states:
              draft (Quotation) -> [action_confirm] -> sale (Sales Order)
            """
            resolved = await resolve_order(
                connection, "sale.order", order_id, order_name
            )
            if isinstance(resolved, dict):
                return resolved
            order_id = resolved

            # Validate state (REQ-05-06)
            orders = await connection.search_read(
                "sale.order",
                [("id", "=", order_id)],
                fields=["name", "state"],
            )
            if not orders:
                return {"status": "error", "message": f"Sale order {order_id} not found."}

            order = orders[0]
            if order["state"] not in ("draft", "sent"):
                return {
                    "status": "error",
                    "message": (
                        f"Cannot confirm order {order['name']}: "
                        f"current state is '{order['state']}'. "
                        f"Only 'draft' or 'sent' orders can be confirmed."
                    ),
                }

            await connection.execute_kw(
                "sale.order", "action_confirm", [[order_id]]
            )

            return {
                "id": order_id,
                "name": order["name"],
                "state": "sale",
                "message": f"Order {order['name']} confirmed successfully.",
            }

        @server.tool()
        async def odoo_sales_cancel_order(
            order_id: int | None = None,
            order_name: str | None = None,
        ) -> dict[str, Any]:
            """Cancel a sales order (action_cancel).

            May fail if there are related pickings or invoices that prevent cancellation.

            sale.order states:
              draft/sale -> [action_cancel] -> cancel
            """
            resolved = await resolve_order(
                connection, "sale.order", order_id, order_name
            )
            if isinstance(resolved, dict):
                return resolved
            order_id = resolved

            orders = await connection.search_read(
                "sale.order",
                [("id", "=", order_id)],
                fields=["name", "state"],
            )
            if not orders:
                return {"status": "error", "message": f"Sale order {order_id} not found."}

            order = orders[0]

            try:
                await connection.execute_kw(
                    "sale.order", "action_cancel", [[order_id]]
                )
            except Exception as exc:
                return {
                    "status": "error",
                    "message": (
                        f"Cannot cancel order {order['name']}: {exc}. "
                        f"This may be because the order has related "
                        f"deliveries or invoices that prevent cancellation."
                    ),
                }

            return {
                "id": order_id,
                "name": order["name"],
                "state": "cancel",
                "message": f"Order {order['name']} cancelled successfully.",
            }

        @server.tool()
        async def odoo_sales_get_order(
            order_id: int | None = None,
            order_name: str | None = None,
            include_lines: bool = True,
            include_deliveries: bool = False,
            include_invoices: bool = False,
        ) -> dict[str, Any]:
            """Retrieve a sales order with full details.

            Optionally includes order lines, deliveries, and invoices.

            sale.order states:
              draft (Quotation) -> sent -> sale (Sales Order)
              v15-v16: sale -> done (Locked)
              v17+: sale with locked=True (check 'locked' field)
              Any -> cancel
            """
            resolved = await resolve_order(
                connection, "sale.order", order_id, order_name
            )
            if isinstance(resolved, dict):
                return resolved
            order_id = resolved

            orders = await connection.search_read(
                "sale.order",
                [("id", "=", order_id)],
                fields=[
                    "name",
                    "state",
                    "locked",
                    "partner_id",
                    "date_order",
                    "amount_untaxed",
                    "amount_tax",
                    "amount_total",
                    "order_line",
                    "invoice_ids",
                    "picking_ids",
                    "note",
                ],
            )
            if not orders:
                return {"status": "error", "message": f"Sale order {order_id} not found."}

            order = orders[0]
            result: dict[str, Any] = {
                "id": order_id,
                "name": order.get("name", ""),
                "state": order.get("state", ""),
                "locked": order.get("locked", False),
                "partner": format_many2one(order.get("partner_id")),
                "date_order": order.get("date_order", ""),
                "amount_untaxed": order.get("amount_untaxed", 0),
                "amount_tax": order.get("amount_tax", 0),
                "amount_total": order.get("amount_total", 0),
                "note": order.get("note", ""),
            }

            # Lines (REQ-05-10)
            if include_lines:
                line_ids = order.get("order_line", [])
                if line_ids:
                    lines_data = await connection.search_read(
                        "sale.order.line",
                        [("id", "in", line_ids)],
                        fields=[
                            "id",
                            "product_id",
                            "name",
                            "product_uom_qty",
                            "price_unit",
                            "discount",
                            "price_subtotal",
                        ],
                    )
                    result["lines"] = [
                        {
                            "id": ln["id"],
                            "product": format_many2one(ln.get("product_id")),
                            "description": ln.get("name", ""),
                            "quantity": ln.get("product_uom_qty", 0),
                            "price_unit": ln.get("price_unit", 0),
                            "discount": ln.get("discount", 0),
                            "subtotal": ln.get("price_subtotal", 0),
                        }
                        for ln in lines_data
                    ]
                else:
                    result["lines"] = []

            # Deliveries
            if include_deliveries:
                picking_ids = order.get("picking_ids", [])
                if picking_ids:
                    pickings = await connection.search_read(
                        "stock.picking",
                        [("id", "in", picking_ids)],
                        fields=["id", "name", "state", "scheduled_date"],
                    )
                    result["deliveries"] = pickings
                else:
                    result["deliveries"] = []

            # Invoices
            if include_invoices:
                invoice_ids = order.get("invoice_ids", [])
                if invoice_ids:
                    invoices = await connection.search_read(
                        "account.move",
                        [("id", "in", invoice_ids)],
                        fields=["id", "name", "state", "amount_total"],
                    )
                    result["invoices"] = invoices
                else:
                    result["invoices"] = []

            return result

        return [
            "odoo_sales_create_order",
            "odoo_sales_confirm_order",
            "odoo_sales_cancel_order",
            "odoo_sales_get_order",
        ]
