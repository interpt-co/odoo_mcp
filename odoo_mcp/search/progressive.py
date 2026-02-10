"""Progressive deep search engine — 5-level search strategy.

Implements REQ-08-01 through REQ-08-13.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..toolsets.formatting import normalize_records
from .domain import build_multi_word_ilike_domain

logger = logging.getLogger("odoo_mcp.search.progressive")


# ---------------------------------------------------------------------------
# Model search configuration (REQ-08-04)
# ---------------------------------------------------------------------------

@dataclass
class ModelSearchConfig:
    model: str
    name_field: str
    search_fields: list[str]
    deep_search_fields: list[str]
    default_fields: list[str]
    has_chatter: bool
    related_models: list[str] = field(default_factory=list)


# Default configs (REQ-08-05)
SEARCH_CONFIGS: dict[str, ModelSearchConfig] = {
    "res.partner": ModelSearchConfig(
        model="res.partner",
        name_field="name",
        search_fields=["name", "display_name"],
        deep_search_fields=["email", "phone", "mobile", "vat", "ref", "website", "comment", "street", "city"],
        default_fields=["id", "name", "email", "phone", "is_company", "city", "country_id"],
        has_chatter=True,
        related_models=["sale.order", "account.move", "crm.lead", "helpdesk.ticket"],
    ),
    "sale.order": ModelSearchConfig(
        model="sale.order",
        name_field="name",
        search_fields=["name", "client_order_ref"],
        deep_search_fields=["note", "origin"],
        default_fields=["id", "name", "partner_id", "state", "amount_total", "date_order"],
        has_chatter=True,
        related_models=["res.partner"],
    ),
    "account.move": ModelSearchConfig(
        model="account.move",
        name_field="name",
        search_fields=["name", "ref", "payment_reference"],
        deep_search_fields=["narration"],
        default_fields=["id", "name", "partner_id", "move_type", "state", "amount_total", "invoice_date"],
        has_chatter=True,
        related_models=["res.partner"],
    ),
    "crm.lead": ModelSearchConfig(
        model="crm.lead",
        name_field="name",
        search_fields=["name", "contact_name", "partner_name"],
        deep_search_fields=["email_from", "phone", "description"],
        default_fields=["id", "name", "partner_id", "stage_id", "expected_revenue", "user_id"],
        has_chatter=True,
        related_models=["res.partner"],
    ),
    "helpdesk.ticket": ModelSearchConfig(
        model="helpdesk.ticket",
        name_field="name",
        search_fields=["name"],
        deep_search_fields=["description"],
        default_fields=["id", "name", "partner_id", "stage_id", "user_id", "team_id", "priority"],
        has_chatter=True,
        related_models=["res.partner"],
    ),
    "product.product": ModelSearchConfig(
        model="product.product",
        name_field="name",
        search_fields=["name", "default_code"],
        deep_search_fields=["barcode", "description", "description_sale"],
        default_fields=["id", "name", "default_code", "list_price", "qty_available", "type"],
        has_chatter=False,
        related_models=[],
    ),
    "project.task": ModelSearchConfig(
        model="project.task",
        name_field="name",
        search_fields=["name"],
        deep_search_fields=["description"],
        default_fields=["id", "name", "project_id", "stage_id", "user_ids", "date_deadline", "priority"],
        has_chatter=True,
        related_models=["project.project"],
    ),
    "stock.picking": ModelSearchConfig(
        model="stock.picking",
        name_field="name",
        search_fields=["name", "origin"],
        deep_search_fields=["note"],
        default_fields=["id", "name", "partner_id", "state", "picking_type_id", "scheduled_date"],
        has_chatter=True,
        related_models=["res.partner"],
    ),
}

# Fallback config (REQ-08-06)
_FALLBACK = ModelSearchConfig(
    model="",
    name_field="name",
    search_fields=["name"],
    deep_search_fields=[],
    default_fields=["id", "name"],
    has_chatter=False,
    related_models=[],
)


def _get_config(model: str) -> ModelSearchConfig:
    if model in SEARCH_CONFIGS:
        return SEARCH_CONFIGS[model]
    cfg = ModelSearchConfig(
        model=model,
        name_field=_FALLBACK.name_field,
        search_fields=list(_FALLBACK.search_fields),
        deep_search_fields=list(_FALLBACK.deep_search_fields),
        default_fields=list(_FALLBACK.default_fields),
        has_chatter=_FALLBACK.has_chatter,
        related_models=list(_FALLBACK.related_models),
    )
    return cfg


# ---------------------------------------------------------------------------
# Search log entry
# ---------------------------------------------------------------------------

@dataclass
class SearchLogEntry:
    level: int
    strategy: str
    model: str
    results_found: int


# ---------------------------------------------------------------------------
# ProgressiveSearch
# ---------------------------------------------------------------------------

class ProgressiveSearch:
    """5-level progressive search engine (REQ-08-01)."""

    def __init__(self, connection: Any, config: Any) -> None:
        self._conn = connection
        self._config = config

    async def search(
        self,
        query: str,
        model: str | None = None,
        max_depth: int = 3,
        limit: int = 20,
        fields: list[str] | None = None,
        exhaustive: bool = False,
    ) -> dict[str, Any]:
        max_depth = max(1, min(max_depth, 5))
        limit = max(1, min(limit, 100))

        models_to_search = [model] if model else list(SEARCH_CONFIGS.keys())
        all_results: dict[str, list[dict]] = {}
        search_log: list[dict] = []
        strategies_used: set[str] = set()
        depth_reached = 0

        for m in models_to_search:
            cfg = _get_config(m)
            result_fields = fields or cfg.default_fields

            model_results: list[dict] = []

            for level in range(1, max_depth + 1):
                depth_reached = max(depth_reached, level)

                records, strategy = await self._search_level(
                    level, m, cfg, query, result_fields, limit,
                )
                found = len(records)
                search_log.append({
                    "level": level,
                    "strategy": strategy,
                    "model": m,
                    "results_found": found,
                })
                strategies_used.add(strategy)

                if records:
                    # Deduplicate by ID
                    existing_ids = {r["id"] for r in model_results}
                    for r in records:
                        if r["id"] not in existing_ids:
                            model_results.append(r)
                            existing_ids.add(r["id"])

                # Stop on results (REQ-08-02) unless exhaustive
                if model_results and not exhaustive:
                    break

            if model_results:
                all_results[m] = model_results[:limit]

        total_results = sum(len(v) for v in all_results.values())
        suggestions = self._generate_suggestions(
            query, all_results, search_log, strategies_used,
        )

        return {
            "query": query,
            "results": all_results,
            "search_log": search_log,
            "depth_reached": depth_reached,
            "total_results": total_results,
            "strategies_used": sorted(strategies_used),
            "suggestions": suggestions,
        }

    # ------------------------------------------------------------------
    # Level dispatching
    # ------------------------------------------------------------------

    async def _search_level(
        self,
        level: int,
        model: str,
        cfg: ModelSearchConfig,
        query: str,
        fields: list[str],
        limit: int,
    ) -> tuple[list[dict], str]:
        """Execute a single search level. Returns ``(records, strategy_name)``."""
        if level == 1:
            return await self._level1_exact(model, cfg, query, fields, limit), "exact_match"
        if level == 2:
            return await self._level2_ilike(model, cfg, query, fields, limit), "standard_ilike"
        if level == 3:
            return await self._level3_extended(model, cfg, query, fields, limit), "extended_fields"
        if level == 4:
            return await self._level4_related(model, cfg, query, fields, limit), "related_models"
        if level == 5:
            return await self._level5_chatter(model, cfg, query, fields, limit), "chatter_search"
        return [], "unknown"

    # ------------------------------------------------------------------
    # Level implementations
    # ------------------------------------------------------------------

    async def _level1_exact(
        self, model: str, cfg: ModelSearchConfig, query: str,
        fields: list[str], limit: int,
    ) -> list[dict]:
        """Level 1 — Exact match on name field (REQ-08-07)."""
        domain = [(cfg.name_field, "=", query)]
        return await self._do_search(model, domain, fields, limit)

    async def _level2_ilike(
        self, model: str, cfg: ModelSearchConfig, query: str,
        fields: list[str], limit: int,
    ) -> list[dict]:
        """Level 2 — Standard ilike (REQ-08-08)."""
        domain = build_multi_word_ilike_domain(cfg.search_fields, query)
        if not domain:
            return []
        return await self._do_search(model, domain, fields, limit)

    async def _level3_extended(
        self, model: str, cfg: ModelSearchConfig, query: str,
        fields: list[str], limit: int,
    ) -> list[dict]:
        """Level 3 — Extended fields ilike (REQ-08-09)."""
        if not cfg.deep_search_fields:
            return []

        # Verify fields exist on the model (best-effort)
        valid_fields = await self._verify_fields(model, cfg.deep_search_fields)
        if not valid_fields:
            return []

        domain = build_multi_word_ilike_domain(valid_fields, query)
        if not domain:
            return []
        return await self._do_search(model, domain, fields, limit)

    async def _level4_related(
        self, model: str, cfg: ModelSearchConfig, query: str,
        fields: list[str], limit: int,
    ) -> list[dict]:
        """Level 4 — Related model search (REQ-08-10)."""
        if not cfg.related_models:
            return []

        all_records: list[dict] = []
        for related_model in cfg.related_models:
            related_cfg = _get_config(related_model)

            # Search query in related model
            domain = build_multi_word_ilike_domain(related_cfg.search_fields, query)
            if not domain:
                continue

            try:
                related_results = await self._do_search(
                    related_model, domain, ["id", "is_company", "parent_id"], limit,
                )
            except Exception:
                continue

            if not related_results:
                continue

            # Extract IDs and expand (company→contacts, individual→parent+siblings)
            related_ids = [r["id"] for r in related_results]
            expanded_ids = await self._expand_partner_ids(
                related_model, related_results, related_ids,
            )

            if not expanded_ids:
                continue

            # Determine the link field (e.g. partner_id for res.partner)
            link_field = self._guess_link_field(model, related_model)
            if not link_field:
                continue

            search_domain = [(link_field, "in", expanded_ids)]
            records = await self._do_search(model, search_domain, fields, limit)
            all_records.extend(records)

        return all_records

    async def _level5_chatter(
        self, model: str, cfg: ModelSearchConfig, query: str,
        fields: list[str], limit: int,
    ) -> list[dict]:
        """Level 5 — Chatter / mail.message search (REQ-08-11)."""
        if not cfg.has_chatter:
            return []

        message_domain = [
            ("model", "=", model),
            ("body", "ilike", query),
            ("message_type", "in", ["email", "comment"]),
        ]

        try:
            messages = await self._do_search(
                "mail.message", message_domain, ["res_id"], limit,
            )
        except Exception:
            return []

        if not messages:
            return []

        record_ids = list({m["res_id"] for m in messages if m.get("res_id")})
        if not record_ids:
            return []

        try:
            records = await self._conn.execute_kw(
                model, "read", [record_ids[:limit]],
                {"fields": fields},
            )
            return normalize_records(records or [])
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _do_search(
        self, model: str, domain: list, fields: list[str], limit: int,
    ) -> list[dict]:
        try:
            result = await self._conn.execute_kw(
                model, "search_read", [domain],
                {"fields": fields, "limit": limit},
            )
            return normalize_records(result or [])
        except Exception as exc:
            logger.debug("Search failed on %s: %s", model, exc)
            return []

    async def _verify_fields(self, model: str, field_names: list[str]) -> list[str]:
        """Return subset of *field_names* that actually exist on *model*."""
        try:
            info = await self._conn.execute_kw(
                model, "fields_get", [],
                {"attributes": ["type"]},
            )
            existing = set(info.keys()) if info else set()
            return [f for f in field_names if f in existing]
        except Exception:
            return list(field_names)  # best-effort: try all

    async def _expand_partner_ids(
        self,
        related_model: str,
        related_results: list[dict],
        related_ids: list[int],
    ) -> list[int]:
        """Expand partner IDs: companies→children, individuals→parent+siblings."""
        if related_model != "res.partner":
            return related_ids

        expanded: set[int] = set(related_ids)

        for r in related_results:
            rid = r.get("id")
            is_company = r.get("is_company", False)
            parent_id = r.get("parent_id")

            if is_company:
                # Include child contacts
                try:
                    children = await self._conn.execute_kw(
                        "res.partner", "search",
                        [[("parent_id", "=", rid)]],
                        {"limit": 100},
                    )
                    expanded.update(children or [])
                except Exception:
                    pass
            else:
                # Include parent + siblings
                pid = None
                if isinstance(parent_id, dict):
                    pid = parent_id.get("id")
                elif isinstance(parent_id, (list, tuple)) and parent_id:
                    pid = parent_id[0]
                elif isinstance(parent_id, int):
                    pid = parent_id

                if pid:
                    expanded.add(pid)
                    try:
                        siblings = await self._conn.execute_kw(
                            "res.partner", "search",
                            [[("parent_id", "=", pid)]],
                            {"limit": 100},
                        )
                        expanded.update(siblings or [])
                    except Exception:
                        pass

        return list(expanded)

    @staticmethod
    def _guess_link_field(model: str, related_model: str) -> str | None:
        """Guess the foreign-key field on *model* that points to *related_model*."""
        # Common patterns
        link_map = {
            "res.partner": "partner_id",
            "project.project": "project_id",
            "sale.order": "order_id",
            "account.move": "move_id",
        }
        return link_map.get(related_model)

    # ------------------------------------------------------------------
    # Suggestions (REQ-08-13)
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_suggestions(
        query: str,
        results: dict[str, list[dict]],
        search_log: list[dict],
        strategies_used: set[str],
    ) -> list[str]:
        suggestions: list[str] = []

        if not results:
            suggestions.append(
                f"No results found for '{query}'. Try broader search terms "
                "or search a different model."
            )
            suggestions.append(
                "Use odoo_core_search_read with an ilike domain to search specific fields."
            )
            return suggestions

        # Summarise what was found
        models_found = list(results.keys())
        if "res.partner" in results:
            partners = results["res.partner"]
            if partners:
                pid = partners[0].get("id")
                pname = partners[0].get("name", query)
                suggestions.append(
                    f"Found partner '{pname}'."
                )
                suggestions.append(
                    f"Use odoo_core_search_read with domain [['partner_id', '=', {pid}]] "
                    "to find more related records."
                )

        if "related_models" in strategies_used:
            suggestions.append(
                "Results include records found via related model expansion."
            )

        if "chatter_search" in strategies_used:
            suggestions.append(
                "Some results matched via chatter message content, not record fields."
            )

        if len(models_found) > 1:
            suggestions.append(
                f"Results found across models: {', '.join(models_found)}."
            )

        return suggestions
