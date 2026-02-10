"""CRM Toolset.

Implements lead/opportunity workflows per SPEC-05 (REQ-05-23 through REQ-05-26).

crm.lead states:
  Lead types: lead, opportunity
  Pipeline stages determine the kanban position.
"""

from __future__ import annotations

import logging
from typing import Any

from odoo_mcp.connection.manager import ConnectionManager
from odoo_mcp.toolsets.base import BaseToolset, ToolsetMetadata
from odoo_mcp.toolsets.formatting import format_many2one
from odoo_mcp.toolsets.helpers import resolve_partner, resolve_name
from odoo_mcp.toolsets.wizard import execute_wizard

logger = logging.getLogger("odoo_mcp.toolsets.crm")


class CrmToolset(BaseToolset):
    """CRM lead and opportunity workflow tools."""

    def metadata(self) -> ToolsetMetadata:
        return ToolsetMetadata(
            name="crm",
            description="Lead and opportunity management",
            required_modules=["crm"],
            depends_on=["core"],
        )

    async def register_tools(
        self, server: Any, connection: ConnectionManager, **kwargs: Any
    ) -> list[str]:

        @server.tool()
        async def odoo_crm_create_lead(
            name: str = "",
            partner_id: int | None = None,
            partner_name: str | None = None,
            email_from: str | None = None,
            phone: str | None = None,
            type: str = "lead",
            expected_revenue: float | None = None,
            team_id: int | None = None,
            user_id: int | None = None,
            stage_id: int | None = None,
            description: str | None = None,
            tag_ids: list[int] | None = None,
        ) -> dict[str, Any]:
            """Create a CRM lead or opportunity (REQ-05-23).

            type: 'lead' or 'opportunity'.
            partner_id or partner_name to link an existing partner.
            """
            if not name:
                return {"status": "error", "message": "name is required."}

            vals: dict[str, Any] = {
                "name": name,
                "type": type,
            }

            if partner_id or partner_name:
                resolved = await resolve_partner(connection, partner_id, partner_name)
                if isinstance(resolved, dict):
                    return resolved
                vals["partner_id"] = resolved

            if email_from:
                vals["email_from"] = email_from
            if phone:
                vals["phone"] = phone
            if expected_revenue is not None:
                vals["expected_revenue"] = expected_revenue
            if team_id:
                vals["team_id"] = team_id
            if user_id:
                vals["user_id"] = user_id
            if stage_id:
                vals["stage_id"] = stage_id
            if description:
                vals["description"] = description
            if tag_ids:
                vals["tag_ids"] = [(6, 0, tag_ids)]

            lead_id = await connection.execute_kw(
                "crm.lead", "create", [vals]
            )

            leads = await connection.search_read(
                "crm.lead",
                [("id", "=", lead_id)],
                fields=["name", "type", "stage_id", "partner_id", "expected_revenue"],
            )
            lead = leads[0] if leads else {}

            return {
                "id": lead_id,
                "name": lead.get("name", name),
                "type": lead.get("type", type),
                "stage": format_many2one(lead.get("stage_id")),
                "partner": format_many2one(lead.get("partner_id")),
                "expected_revenue": lead.get("expected_revenue", 0),
                "message": f"Created {type} '{name}'.",
            }

        @server.tool()
        async def odoo_crm_move_stage(
            lead_id: int = 0,
            stage_id: int | None = None,
            stage_name: str | None = None,
        ) -> dict[str, Any]:
            """Move a lead/opportunity to a different pipeline stage (REQ-05-24).

            Accepts stage_id or stage_name for resolution.
            """
            if not lead_id:
                return {"status": "error", "message": "lead_id is required."}

            resolved_stage = await resolve_name(
                connection, "crm.stage", stage_id, stage_name, "stage"
            )
            if isinstance(resolved_stage, dict):
                return resolved_stage

            await connection.execute_kw(
                "crm.lead", "write", [[lead_id], {"stage_id": resolved_stage}]
            )

            leads = await connection.search_read(
                "crm.lead",
                [("id", "=", lead_id)],
                fields=["name", "stage_id"],
            )
            lead = leads[0] if leads else {}

            return {
                "id": lead_id,
                "name": lead.get("name", ""),
                "stage": format_many2one(lead.get("stage_id")),
                "message": f"Lead moved to stage '{format_many2one(lead.get('stage_id', {})) or {}}'.".replace("'{'", "'"),
            }

        @server.tool()
        async def odoo_crm_convert_to_opportunity(
            lead_id: int = 0,
            partner_id: int | None = None,
            user_id: int | None = None,
            team_id: int | None = None,
        ) -> dict[str, Any]:
            """Convert a lead to an opportunity (REQ-05-25, REQ-05-26).

            Uses the crm.lead2opportunity.partner wizard.
            If partner_id is provided, links to existing customer.
            Otherwise, creates a new customer.
            """
            if not lead_id:
                return {"status": "error", "message": "lead_id is required."}

            wizard_values: dict[str, Any] = {
                "name": "convert",
            }

            if partner_id:
                wizard_values["action"] = "exist"
                wizard_values["partner_id"] = partner_id
            else:
                wizard_values["action"] = "create"

            if user_id:
                wizard_values["user_id"] = user_id
            if team_id:
                wizard_values["team_id"] = team_id

            try:
                result = await execute_wizard(
                    connection=connection,
                    wizard_model="crm.lead2opportunity.partner",
                    wizard_values=wizard_values,
                    action_method="action_apply",
                    source_model="crm.lead",
                    source_ids=[lead_id],
                )
            except Exception as exc:
                return {
                    "status": "error",
                    "message": f"Lead-to-opportunity conversion failed: {exc}",
                }

            # Read back the updated lead
            leads = await connection.search_read(
                "crm.lead",
                [("id", "=", lead_id)],
                fields=["name", "type", "stage_id", "partner_id"],
            )
            lead = leads[0] if leads else {}

            return {
                "id": lead_id,
                "name": lead.get("name", ""),
                "type": lead.get("type", "opportunity"),
                "stage": format_many2one(lead.get("stage_id")),
                "partner": format_many2one(lead.get("partner_id")),
                "message": f"Lead converted to opportunity successfully.",
            }

        return [
            "odoo_crm_create_lead",
            "odoo_crm_move_stage",
            "odoo_crm_convert_to_opportunity",
        ]
