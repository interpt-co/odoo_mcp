"""Name Resolution & Shared Helpers.

Reusable utilities for workflow tools per REQ-05-02, REQ-05-36.
The name resolution pattern MUST NOT be duplicated in each tool.
"""

from __future__ import annotations

import logging
from typing import Any

from odoo_mcp.connection.manager import ConnectionManager

logger = logging.getLogger("odoo_mcp.helpers")


async def resolve_name(
    connection: ConnectionManager,
    model: str,
    id_value: int | None,
    name_value: str | None,
    field_name: str = "name",
) -> int | dict[str, Any]:
    """Resolve an entity by ID or name (REQ-05-36).

    Returns:
        int: The resolved record ID if exactly one match.
        dict: An error or disambiguation response if resolution fails.

    Resolution rules:
        1. If id_value is provided, use it directly.
        2. If name_value is provided, call name_search(name, limit=5).
        3. Exactly 1 match -> return ID.
        4. 0 matches -> return error dict with suggestion.
        5. 2+ matches -> return disambiguation dict (max 10).
    """
    if id_value is not None:
        return id_value

    if not name_value:
        return {
            "status": "error",
            "message": f"Either {field_name}_id or {field_name}_name must be provided.",
        }

    results = await connection.execute_kw(
        model,
        "name_search",
        [name_value],
        kwargs={"limit": 10},
    )

    if not results:
        return {
            "status": "error",
            "field": f"{field_name}_id",
            "message": (
                f"No {model} records match '{name_value}'. "
                f"Check the spelling or use odoo_core_search_read to find "
                f"the correct record."
            ),
        }

    if len(results) == 1:
        return results[0][0]

    # Multiple matches -> disambiguation (REQ-05-02)
    matches = [{"id": r[0], "name": r[1]} for r in results[:10]]
    return {
        "status": "disambiguation_needed",
        "field": f"{field_name}_id",
        "matches": matches,
        "message": (
            f"Multiple {model} records match '{name_value}'. "
            f"Please specify {field_name}_id."
        ),
    }


async def resolve_partner(
    connection: ConnectionManager,
    partner_id: int | None,
    partner_name: str | None,
) -> int | dict[str, Any]:
    """Resolve a partner (res.partner) by ID or name."""
    return await resolve_name(
        connection, "res.partner", partner_id, partner_name, "partner"
    )


async def resolve_product(
    connection: ConnectionManager,
    product_id: int | None,
    product_name: str | None,
) -> int | dict[str, Any]:
    """Resolve a product (product.product) by ID or name."""
    return await resolve_name(
        connection, "product.product", product_id, product_name, "product"
    )


async def resolve_order(
    connection: ConnectionManager,
    model: str,
    order_id: int | None,
    order_name: str | None,
) -> int | dict[str, Any]:
    """Resolve an order (sale.order, etc.) by ID or name/reference."""
    return await resolve_name(
        connection, model, order_id, order_name, "order"
    )
