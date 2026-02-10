"""Inventory Toolset.

Implements stock/warehouse workflows per SPEC-05 (REQ-05-18 through REQ-05-22).

stock.picking states:
  draft -> [action_confirm] -> waiting/confirmed -> [action_assign] -> assigned
  assigned -> [button_validate] -> done
  Any -> [action_cancel] -> cancel

  'waiting' = waiting for another operation (e.g. upstream picking).
  'confirmed' = waiting for stock availability.

Wizard notes:
  - stock.immediate.transfer: only exists in v15-v16 (removed in v17).
  - stock.backorder.confirmation: exists in all versions.
"""

from __future__ import annotations

import logging
from typing import Any

from odoo_mcp.connection.manager import ConnectionManager
from odoo_mcp.toolsets.base import BaseToolset, ToolsetMetadata
from odoo_mcp.toolsets.formatting import format_many2one
from odoo_mcp.toolsets.helpers import resolve_product, resolve_name
from odoo_mcp.toolsets.wizard import (
    is_wizard_action,
    get_wizard_model,
    is_known_wizard,
    execute_wizard,
    handle_wizard_result,
    build_unknown_wizard_response,
    KNOWN_WIZARDS,
)

logger = logging.getLogger("odoo_mcp.toolsets.inventory")


class InventoryToolset(BaseToolset):
    """Inventory and warehouse workflow tools."""

    def metadata(self) -> ToolsetMetadata:
        return ToolsetMetadata(
            name="inventory",
            description="Stock moves and warehouse operations",
            required_modules=["stock"],
            depends_on=["core"],
        )

    async def register_tools(
        self, server: Any, connection: ConnectionManager, **kwargs: Any
    ) -> list[str]:

        @server.tool()
        async def odoo_inventory_get_stock(
            product_id: int | None = None,
            product_name: str | None = None,
            location_id: int | None = None,
            warehouse_id: int | None = None,
        ) -> dict[str, Any]:
            """Get current stock levels for a product (REQ-05-18, REQ-05-19).

            Queries stock.quant and returns quantity per location.
            """
            resolved = await resolve_product(connection, product_id, product_name)
            if isinstance(resolved, dict):
                return resolved
            product_id = resolved

            # Read product name
            products = await connection.search_read(
                "product.product",
                [("id", "=", product_id)],
                fields=["display_name"],
            )
            product_display = products[0]["display_name"] if products else ""

            # Build domain for stock.quant
            domain: list[Any] = [("product_id", "=", product_id)]
            if location_id:
                domain.append(("location_id", "=", location_id))
            if warehouse_id:
                # Filter by warehouse's stock location
                warehouses = await connection.search_read(
                    "stock.warehouse",
                    [("id", "=", warehouse_id)],
                    fields=["lot_stock_id"],
                )
                if warehouses:
                    wh_loc = warehouses[0].get("lot_stock_id")
                    if wh_loc:
                        loc_id = wh_loc[0] if isinstance(wh_loc, (list, tuple)) else wh_loc
                        domain.append(("location_id", "child_of", loc_id))

            quants = await connection.search_read(
                "stock.quant",
                domain,
                fields=[
                    "location_id",
                    "quantity",
                    "reserved_quantity",
                ],
            )

            stock_entries = []
            total_available = 0.0
            for q in quants:
                qty = q.get("quantity", 0)
                reserved = q.get("reserved_quantity", 0)
                available = qty - reserved
                total_available += available
                stock_entries.append({
                    "location": format_many2one(q.get("location_id")),
                    "quantity": qty,
                    "reserved_quantity": reserved,
                    "available_quantity": available,
                })

            return {
                "product": {"id": product_id, "name": product_display},
                "stock": stock_entries,
                "total_available": total_available,
            }

        @server.tool()
        async def odoo_inventory_validate_picking(
            picking_id: int | None = None,
            picking_name: str | None = None,
            force_qty: bool = False,
        ) -> dict[str, Any]:
            """Validate (process) a stock picking (REQ-05-20, REQ-05-21).

            Calls button_validate. Handles stock.immediate.transfer (v15-v16 only)
            and stock.backorder.confirmation wizards automatically via the
            wizard protocol.

            stock.picking states:
              draft -> waiting/confirmed -> assigned -> [button_validate] -> done
            """
            resolved = await resolve_name(
                connection, "stock.picking", picking_id, picking_name, "picking"
            )
            if isinstance(resolved, dict):
                return resolved
            picking_id = resolved

            pickings = await connection.search_read(
                "stock.picking",
                [("id", "=", picking_id)],
                fields=["name", "state"],
            )
            if not pickings:
                return {"status": "error", "message": f"Picking {picking_id} not found."}

            picking = pickings[0]

            try:
                result = await connection.execute_kw(
                    "stock.picking",
                    "button_validate",
                    [[picking_id]],
                    context={"button_validate_picking_ids": [picking_id]},
                )
            except Exception as exc:
                return {
                    "status": "error",
                    "message": f"Failed to validate picking {picking['name']}: {exc}",
                }

            # Handle wizard responses (REQ-05-21)
            if is_wizard_action(result):
                wizard_model = get_wizard_model(result)

                if wizard_model == "stock.immediate.transfer":
                    # Auto-process immediate transfer
                    try:
                        wiz_result = await execute_wizard(
                            connection=connection,
                            wizard_model="stock.immediate.transfer",
                            wizard_values={},
                            action_method="process",
                            source_model="stock.picking",
                            source_ids=[picking_id],
                            context_extra={
                                "button_validate_picking_ids": [picking_id]
                            },
                        )
                        final = await handle_wizard_result(connection, wiz_result)
                        return {
                            "id": picking_id,
                            "name": picking["name"],
                            "state": "done",
                            "message": f"Picking {picking['name']} validated (immediate transfer).",
                            "wizard_handled": "stock.immediate.transfer",
                            **final,
                        }
                    except Exception as exc:
                        return {
                            "status": "error",
                            "message": f"Immediate transfer wizard failed: {exc}",
                        }

                elif wizard_model == "stock.backorder.confirmation":
                    action_method = (
                        "process" if force_qty else "process_cancel_backorder"
                    )
                    try:
                        wiz_result = await execute_wizard(
                            connection=connection,
                            wizard_model="stock.backorder.confirmation",
                            wizard_values={},
                            action_method=action_method,
                            source_model="stock.picking",
                            source_ids=[picking_id],
                            context_extra={
                                "button_validate_picking_ids": [picking_id]
                            },
                        )
                        final = await handle_wizard_result(connection, wiz_result)
                        backorder_msg = (
                            "Backorder created for remaining items."
                            if force_qty
                            else "Remaining quantities ignored (no backorder)."
                        )
                        return {
                            "id": picking_id,
                            "name": picking["name"],
                            "state": "done",
                            "message": (
                                f"Picking {picking['name']} validated. "
                                f"{backorder_msg}"
                            ),
                            "wizard_handled": "stock.backorder.confirmation",
                            **final,
                        }
                    except Exception as exc:
                        return {
                            "status": "error",
                            "message": f"Backorder confirmation wizard failed: {exc}",
                        }

                else:
                    # Unknown wizard
                    return await build_unknown_wizard_response(
                        connection,
                        wizard_model or "",
                        result,
                        "stock.picking",
                        [picking_id],
                    )

            return {
                "id": picking_id,
                "name": picking["name"],
                "state": "done",
                "message": f"Picking {picking['name']} validated successfully.",
            }

        @server.tool()
        async def odoo_inventory_create_transfer(
            picking_type_name: str | None = None,
            location_src_id: int | None = None,
            location_dest_id: int | None = None,
            lines: list[dict[str, Any]] | None = None,
            scheduled_date: str | None = None,
            validate: bool = False,
        ) -> dict[str, Any]:
            """Create an internal stock transfer (REQ-05-22).

            picking_type_name: 'internal', 'incoming', or 'outgoing'.
            Lines need product_id or product_name and quantity.
            Set validate=True to validate immediately.
            """
            if not lines:
                return {"status": "error", "message": "lines is required."}

            # Resolve picking type
            type_code_map = {
                "internal": "internal",
                "incoming": "incoming",
                "outgoing": "outgoing",
            }
            type_code = type_code_map.get(picking_type_name or "internal", "internal")

            picking_types = await connection.search_read(
                "stock.picking.type",
                [("code", "=", type_code)],
                fields=["id", "name", "default_location_src_id", "default_location_dest_id"],
                limit=1,
            )
            if not picking_types:
                return {
                    "status": "error",
                    "message": f"No picking type found for code '{type_code}'.",
                }

            pt = picking_types[0]
            src_loc = location_src_id
            dest_loc = location_dest_id

            if not src_loc and pt.get("default_location_src_id"):
                src_val = pt["default_location_src_id"]
                src_loc = src_val[0] if isinstance(src_val, (list, tuple)) else src_val
            if not dest_loc and pt.get("default_location_dest_id"):
                dest_val = pt["default_location_dest_id"]
                dest_loc = dest_val[0] if isinstance(dest_val, (list, tuple)) else dest_val

            if not src_loc or not dest_loc:
                return {
                    "status": "error",
                    "message": "location_src_id and location_dest_id are required.",
                }

            # Build move lines
            move_lines = []
            for line in lines:
                prod_resolved = await resolve_product(
                    connection, line.get("product_id"), line.get("product_name")
                )
                if isinstance(prod_resolved, dict):
                    return prod_resolved

                # Get product UOM
                products = await connection.search_read(
                    "product.product",
                    [("id", "=", prod_resolved)],
                    fields=["display_name", "uom_id"],
                )
                uom_id = None
                prod_name = ""
                if products:
                    prod_name = products[0].get("display_name", "")
                    uom_val = products[0].get("uom_id")
                    if isinstance(uom_val, (list, tuple)):
                        uom_id = uom_val[0]
                    else:
                        uom_id = uom_val

                move_vals: dict[str, Any] = {
                    "name": prod_name or f"Product {prod_resolved}",
                    "product_id": prod_resolved,
                    "product_uom_qty": line.get("quantity", 1),
                    "location_id": src_loc,
                    "location_dest_id": dest_loc,
                }
                if uom_id:
                    move_vals["product_uom"] = uom_id

                move_lines.append((0, 0, move_vals))

            picking_vals: dict[str, Any] = {
                "picking_type_id": pt["id"],
                "location_id": src_loc,
                "location_dest_id": dest_loc,
                "move_ids_without_package": move_lines,
            }
            if scheduled_date:
                picking_vals["scheduled_date"] = scheduled_date

            picking_id = await connection.execute_kw(
                "stock.picking", "create", [picking_vals]
            )

            # Confirm the picking
            await connection.execute_kw(
                "stock.picking", "action_confirm", [[picking_id]]
            )

            # Optionally validate
            if validate:
                validate_result = await odoo_inventory_validate_picking(
                    picking_id=picking_id, force_qty=False
                )
                if validate_result.get("status") == "error":
                    return validate_result

            # Read back
            picks = await connection.search_read(
                "stock.picking",
                [("id", "=", picking_id)],
                fields=["name", "state"],
            )
            pick = picks[0] if picks else {}

            return {
                "id": picking_id,
                "name": pick.get("name", ""),
                "state": pick.get("state", ""),
                "lines_count": len(lines),
                "message": f"Transfer {pick.get('name', '')} created with {len(lines)} line(s).",
            }

        return [
            "odoo_inventory_get_stock",
            "odoo_inventory_validate_picking",
            "odoo_inventory_create_transfer",
        ]
