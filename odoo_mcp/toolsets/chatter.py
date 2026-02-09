"""Chatter Toolset.

Implements messaging and activity workflows per SPEC-09 (REQ-09-01 through REQ-09-10).
"""

from __future__ import annotations

import logging
from typing import Any

from odoo_mcp.connection.manager import ConnectionManager
from odoo_mcp.toolsets.base import BaseToolset, ToolsetMetadata
from odoo_mcp.toolsets.formatting import format_many2one, strip_html

logger = logging.getLogger("odoo_mcp.toolsets.chatter")

# Activity type XML ID mapping (REQ-09-10)
ACTIVITY_TYPE_MAP: dict[str, str] = {
    "email": "mail.mail_activity_data_email",
    "call": "mail.mail_activity_data_call",
    "meeting": "mail.mail_activity_data_meeting",
    "todo": "mail.mail_activity_data_todo",
    "upload_document": "mail.mail_activity_data_upload_document",
}


class ChatterToolset(BaseToolset):
    """Messaging and activity tools."""

    def metadata(self) -> ToolsetMetadata:
        return ToolsetMetadata(
            name="chatter",
            description="Messaging and activity tools",
            required_modules=["mail"],
            depends_on=["core"],
        )

    def register_tools(
        self, server: Any, connection: ConnectionManager
    ) -> list[str]:

        @server.tool()
        async def odoo_chatter_get_messages(
            model: str = "",
            record_id: int = 0,
            limit: int = 20,
            message_types: list[str] | None = None,
            strip_html_content: bool = True,
        ) -> dict[str, Any]:
            """Retrieve messages from a record's chatter (REQ-09-01 to REQ-09-03).

            model: Odoo model name (must have chatter, e.g. 'sale.order').
            message_types: Filter by type. Default: ['email', 'comment'].
            limit: Max 100, default 20.
            """
            if not model or not record_id:
                return {"status": "error", "message": "model and record_id are required."}

            if limit > 100:
                limit = 100

            if message_types is None:
                message_types = ["email", "comment"]

            # REQ-09-02
            domain: list[Any] = [
                ("model", "=", model),
                ("res_id", "=", record_id),
                ("message_type", "in", message_types),
            ]

            messages = await connection.search_read(
                "mail.message",
                domain,
                fields=[
                    "id",
                    "body",
                    "author_id",
                    "date",
                    "message_type",
                    "subtype_id",
                    "email_from",
                    "subject",
                ],
                order="date desc",
                limit=limit,
            )

            # Count total for has_more
            total_count = len(messages)

            # REQ-09-03
            result_messages = []
            for m in messages:
                body = m.get("body", "")
                if strip_html_content and body:
                    body = strip_html(body)

                result_messages.append({
                    "id": m["id"],
                    "date": m.get("date", ""),
                    "author": format_many2one(m.get("author_id")),
                    "type": m.get("message_type", ""),
                    "subject": m.get("subject") or None,
                    "body": body,
                    "email_from": m.get("email_from", ""),
                })

            return {
                "model": model,
                "record_id": record_id,
                "messages": result_messages,
                "count": len(result_messages),
                "has_more": total_count >= limit,
            }

        @server.tool()
        async def odoo_chatter_post_message(
            model: str = "",
            record_id: int = 0,
            body: str = "",
            message_type: str = "comment",
            subtype: str | None = None,
            partner_ids: list[int] | None = None,
        ) -> dict[str, Any]:
            """Post a message to a record's chatter (REQ-09-04 to REQ-09-06).

            message_type: 'comment' (visible in chatter) or 'notification' (internal note).
            Not allowed in readonly mode (REQ-09-06).
            """
            if not model or not record_id:
                return {"status": "error", "message": "model and record_id are required."}
            if not body:
                return {"status": "error", "message": "body is required."}

            # REQ-09-05
            subtype_xmlid = subtype or (
                "mail.mt_comment"
                if message_type == "comment"
                else "mail.mt_note"
            )

            result = await connection.execute_kw(
                model,
                "message_post",
                [record_id],
                kwargs={
                    "body": f"<p>{body}</p>",
                    "message_type": message_type,
                    "subtype_xmlid": subtype_xmlid,
                    "partner_ids": partner_ids or [],
                },
            )

            return {
                "model": model,
                "record_id": record_id,
                "message_id": result,
                "message": "Message posted successfully.",
            }

        @server.tool()
        async def odoo_chatter_get_activities(
            model: str = "",
            record_id: int = 0,
        ) -> dict[str, Any]:
            """Retrieve scheduled activities for a record (REQ-09-07, REQ-09-08).
            """
            if not model or not record_id:
                return {"status": "error", "message": "model and record_id are required."}

            # REQ-09-08
            domain: list[Any] = [
                ("res_model", "=", model),
                ("res_id", "=", record_id),
            ]

            activities = await connection.search_read(
                "mail.activity",
                domain,
                fields=[
                    "id",
                    "activity_type_id",
                    "summary",
                    "note",
                    "date_deadline",
                    "user_id",
                    "state",
                ],
                order="date_deadline asc",
            )

            return {
                "model": model,
                "record_id": record_id,
                "activities": [
                    {
                        "id": a["id"],
                        "type": format_many2one(a.get("activity_type_id")),
                        "summary": a.get("summary", ""),
                        "note": a.get("note", ""),
                        "deadline": a.get("date_deadline", ""),
                        "user": format_many2one(a.get("user_id")),
                        "state": a.get("state", ""),
                    }
                    for a in activities
                ],
                "count": len(activities),
            }

        @server.tool()
        async def odoo_chatter_schedule_activity(
            model: str = "",
            record_id: int = 0,
            activity_type: str = "todo",
            summary: str = "",
            note: str | None = None,
            date_deadline: str | None = None,
            user_id: int | None = None,
        ) -> dict[str, Any]:
            """Schedule a new activity on a record (REQ-09-09, REQ-09-10).

            activity_type: 'email', 'call', 'meeting', 'todo', 'upload_document'.
            Maps to mail.activity.type via XML ID.
            """
            if not model or not record_id:
                return {"status": "error", "message": "model and record_id are required."}
            if not summary:
                return {"status": "error", "message": "summary is required."}

            # Resolve activity_type string to ID (REQ-09-10)
            xml_id = ACTIVITY_TYPE_MAP.get(activity_type)
            if not xml_id:
                return {
                    "status": "error",
                    "message": (
                        f"Unknown activity_type '{activity_type}'. "
                        f"Valid types: {', '.join(ACTIVITY_TYPE_MAP.keys())}."
                    ),
                }

            # Resolve XML ID to record ID
            try:
                type_id = await connection.execute_kw(
                    "ir.model.data",
                    "xmlid_to_res_id",
                    [xml_id],
                )
            except Exception:
                # Fallback: search by name
                type_records = await connection.search_read(
                    "mail.activity.type",
                    [("res_model_id", "=", False)],
                    fields=["id", "name"],
                    limit=20,
                )
                type_id = None
                for tr in type_records:
                    if tr.get("name", "").lower() == activity_type.lower():
                        type_id = tr["id"]
                        break
                if not type_id and type_records:
                    type_id = type_records[0]["id"]

            if not type_id:
                return {
                    "status": "error",
                    "message": f"Could not resolve activity type '{activity_type}'.",
                }

            vals: dict[str, Any] = {
                "res_model_id": await _get_model_id(connection, model),
                "res_id": record_id,
                "activity_type_id": type_id,
                "summary": summary,
            }
            if note:
                vals["note"] = note
            if date_deadline:
                vals["date_deadline"] = date_deadline
            if user_id:
                vals["user_id"] = user_id

            activity_id = await connection.execute_kw(
                "mail.activity", "create", [vals]
            )

            return {
                "id": activity_id,
                "model": model,
                "record_id": record_id,
                "activity_type": activity_type,
                "summary": summary,
                "message": f"Activity '{summary}' scheduled.",
            }

        return [
            "odoo_chatter_get_messages",
            "odoo_chatter_post_message",
            "odoo_chatter_get_activities",
            "odoo_chatter_schedule_activity",
        ]


async def _get_model_id(connection: ConnectionManager, model_name: str) -> int:
    """Get the ir.model ID for a model name."""
    models = await connection.search_read(
        "ir.model",
        [("model", "=", model_name)],
        fields=["id"],
        limit=1,
    )
    if models:
        return models[0]["id"]
    raise ValueError(f"Model '{model_name}' not found in ir.model.")
