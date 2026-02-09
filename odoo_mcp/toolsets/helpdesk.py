"""Helpdesk Toolset.

Implements helpdesk ticket workflows per SPEC-05 (REQ-05-27 through REQ-05-29).
Enterprise only - requires 'helpdesk' module.
"""

from __future__ import annotations

import logging
from typing import Any

from odoo_mcp.connection.manager import ConnectionManager
from odoo_mcp.toolsets.base import BaseToolset, ToolsetMetadata
from odoo_mcp.toolsets.formatting import format_many2one, strip_html
from odoo_mcp.toolsets.helpers import resolve_partner, resolve_name

logger = logging.getLogger("odoo_mcp.toolsets.helpdesk")


class HelpdeskToolset(BaseToolset):
    """Helpdesk ticket management tools (Enterprise)."""

    def metadata(self) -> ToolsetMetadata:
        return ToolsetMetadata(
            name="helpdesk",
            description="Ticket management (Enterprise)",
            required_modules=["helpdesk"],
            depends_on=["core"],
        )

    def register_tools(
        self, server: Any, connection: ConnectionManager
    ) -> list[str]:

        @server.tool()
        async def odoo_helpdesk_create_ticket(
            name: str = "",
            partner_id: int | None = None,
            partner_name: str | None = None,
            team_id: int | None = None,
            user_id: int | None = None,
            description: str | None = None,
            priority: str = "0",
            tag_ids: list[int] | None = None,
        ) -> dict[str, Any]:
            """Create a helpdesk ticket (REQ-05-27).

            priority: '0'=Low, '1'=Medium, '2'=High, '3'=Urgent.
            """
            if not name:
                return {"status": "error", "message": "name is required."}

            vals: dict[str, Any] = {
                "name": name,
                "priority": priority,
            }

            if partner_id or partner_name:
                resolved = await resolve_partner(connection, partner_id, partner_name)
                if isinstance(resolved, dict):
                    return resolved
                vals["partner_id"] = resolved

            if team_id:
                vals["team_id"] = team_id
            if user_id:
                vals["user_id"] = user_id
            if description:
                vals["description"] = description
            if tag_ids:
                vals["tag_ids"] = [(6, 0, tag_ids)]

            ticket_id = await connection.execute_kw(
                "helpdesk.ticket", "create", [vals]
            )

            tickets = await connection.search_read(
                "helpdesk.ticket",
                [("id", "=", ticket_id)],
                fields=["name", "stage_id", "partner_id", "user_id", "team_id", "priority"],
            )
            ticket = tickets[0] if tickets else {}

            return {
                "id": ticket_id,
                "name": ticket.get("name", name),
                "stage": format_many2one(ticket.get("stage_id")),
                "partner": format_many2one(ticket.get("partner_id")),
                "assigned_to": format_many2one(ticket.get("user_id")),
                "team": format_many2one(ticket.get("team_id")),
                "priority": ticket.get("priority", priority),
                "message": f"Created ticket '{name}'.",
            }

        @server.tool()
        async def odoo_helpdesk_get_ticket(
            ticket_id: int | None = None,
            ticket_name: str | None = None,
            include_messages: bool = True,
            include_attachments: bool = False,
            message_limit: int = 20,
        ) -> dict[str, Any]:
            """Retrieve a helpdesk ticket with full details (REQ-05-28).

            Optionally includes messages and attachments.
            """
            resolved = await resolve_name(
                connection, "helpdesk.ticket", ticket_id, ticket_name, "ticket"
            )
            if isinstance(resolved, dict):
                return resolved
            ticket_id = resolved

            tickets = await connection.search_read(
                "helpdesk.ticket",
                [("id", "=", ticket_id)],
                fields=[
                    "name",
                    "description",
                    "stage_id",
                    "partner_id",
                    "user_id",
                    "team_id",
                    "priority",
                    "create_date",
                ],
            )
            if not tickets:
                return {"status": "error", "message": f"Ticket {ticket_id} not found."}

            ticket = tickets[0]
            result: dict[str, Any] = {
                "id": ticket_id,
                "name": ticket.get("name", ""),
                "description": ticket.get("description", ""),
                "stage": format_many2one(ticket.get("stage_id")),
                "partner": format_many2one(ticket.get("partner_id")),
                "assigned_to": format_many2one(ticket.get("user_id")),
                "team": format_many2one(ticket.get("team_id")),
                "priority": ticket.get("priority", "0"),
                "created_at": ticket.get("create_date", ""),
            }

            if include_messages:
                messages = await connection.search_read(
                    "mail.message",
                    [
                        ("model", "=", "helpdesk.ticket"),
                        ("res_id", "=", ticket_id),
                        ("message_type", "in", ["email", "comment"]),
                    ],
                    fields=["id", "body", "author_id", "date", "message_type", "email_from"],
                    limit=message_limit,
                    order="date desc",
                )
                result["messages"] = [
                    {
                        "id": m["id"],
                        "date": m.get("date", ""),
                        "author": format_many2one(m.get("author_id")),
                        "type": m.get("message_type", ""),
                        "body": strip_html(m.get("body", "")),
                        "email_from": m.get("email_from", ""),
                    }
                    for m in messages
                ]

            if include_attachments:
                attachments = await connection.search_read(
                    "ir.attachment",
                    [
                        ("res_model", "=", "helpdesk.ticket"),
                        ("res_id", "=", ticket_id),
                    ],
                    fields=["id", "name", "mimetype", "file_size"],
                    order="create_date desc",
                )
                result["attachments"] = attachments

            return result

        @server.tool()
        async def odoo_helpdesk_assign_ticket(
            ticket_id: int = 0,
            user_id: int | None = None,
            team_id: int | None = None,
        ) -> dict[str, Any]:
            """Assign a ticket to a user and/or team (REQ-05-29)."""
            if not ticket_id:
                return {"status": "error", "message": "ticket_id is required."}

            vals: dict[str, Any] = {}
            if user_id is not None:
                vals["user_id"] = user_id
            if team_id is not None:
                vals["team_id"] = team_id

            if not vals:
                return {"status": "error", "message": "Provide user_id and/or team_id."}

            await connection.execute_kw(
                "helpdesk.ticket", "write", [[ticket_id], vals]
            )

            tickets = await connection.search_read(
                "helpdesk.ticket",
                [("id", "=", ticket_id)],
                fields=["name", "user_id", "team_id"],
            )
            ticket = tickets[0] if tickets else {}

            return {
                "id": ticket_id,
                "name": ticket.get("name", ""),
                "assigned_to": format_many2one(ticket.get("user_id")),
                "team": format_many2one(ticket.get("team_id")),
                "message": f"Ticket assigned successfully.",
            }

        return [
            "odoo_helpdesk_create_ticket",
            "odoo_helpdesk_get_ticket",
            "odoo_helpdesk_assign_ticket",
        ]
