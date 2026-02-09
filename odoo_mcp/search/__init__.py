"""Search package — progressive deep search, domain builder, name_search utility."""

from __future__ import annotations

from typing import Any


async def name_search(
    connection: Any,
    model: str,
    name: str,
    operator: str = "ilike",
    limit: int = 5,
    domain: list | None = None,
) -> list[dict[str, Any]]:
    """Search for records by name using Odoo's native ``name_search`` (REQ-08-16/17).

    Wraps ``execute_kw(model, 'name_search', ...)`` and normalises the result
    from ``[[id, name], ...]`` to ``[{"id": id, "name": name}, ...]``.
    """
    args = domain or []
    results = await connection.execute_kw(
        model,
        "name_search",
        [name],
        {"args": args, "operator": operator, "limit": limit},
    )
    return [{"id": r[0], "name": r[1]} for r in (results or [])]


__all__ = ["name_search"]
