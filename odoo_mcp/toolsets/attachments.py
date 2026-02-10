"""Attachments Toolset.

Implements file attachment operations per SPEC-09 (REQ-09-11 through REQ-09-21).
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
from pathlib import Path
from typing import Any

from odoo_mcp.connection.manager import ConnectionManager
from odoo_mcp.toolsets.base import BaseToolset, ToolsetMetadata
from odoo_mcp.toolsets.formatting import format_many2one, format_size_human

logger = logging.getLogger("odoo_mcp.toolsets.attachments")

# REQ-09-15: Text MIME types that can be decoded as text
TEXT_MIME_TYPES = {
    "text/plain",
    "text/csv",
    "text/html",
    "text/xml",
    "application/json",
    "application/xml",
    "application/xhtml+xml",
}

# Default max attachment size for download (REQ-09-15)
MAX_ATTACHMENT_SIZE_BYTES = 12 * 1024 * 1024  # 12 MB


class AttachmentsToolset(BaseToolset):
    """File attachment operations."""

    def metadata(self) -> ToolsetMetadata:
        return ToolsetMetadata(
            name="attachments",
            description="File attachment operations",
            required_modules=[],
            depends_on=["core"],
        )

    async def register_tools(
        self, server: Any, connection: ConnectionManager, **kwargs: Any
    ) -> list[str]:

        @server.tool()
        async def odoo_attachments_list(
            model: str = "",
            record_id: int = 0,
        ) -> dict[str, Any]:
            """List attachments for a record (REQ-09-11 to REQ-09-13).
            """
            if not model or not record_id:
                return {"status": "error", "message": "model and record_id are required."}

            # REQ-09-12
            domain: list[Any] = [
                ("res_model", "=", model),
                ("res_id", "=", record_id),
            ]

            attachments = await connection.search_read(
                "ir.attachment",
                domain,
                fields=["id", "name", "mimetype", "file_size", "create_date", "create_uid"],
                order="create_date desc",
            )

            # REQ-09-13
            result_attachments = []
            for att in attachments:
                result_attachments.append({
                    "id": att["id"],
                    "name": att.get("name", ""),
                    "mimetype": att.get("mimetype", ""),
                    "file_size": att.get("file_size", 0),
                    "file_size_human": format_size_human(att.get("file_size", 0)),
                    "created_at": att.get("create_date", ""),
                    "created_by": format_many2one(att.get("create_uid")),
                })

            return {
                "model": model,
                "record_id": record_id,
                "attachments": result_attachments,
                "count": len(result_attachments),
            }

        @server.tool()
        async def odoo_attachments_get_content(
            attachment_id: int = 0,
            as_text: bool = False,
            save_path: str = "",
        ) -> dict[str, Any]:
            """Download attachment content (REQ-09-14 to REQ-09-16).

            RECOMMENDED: For binary files (PDFs, ZIPs, images, etc.), always use
            save_path to write the file directly to disk. This avoids base64 data
            being passed through the conversation context, which can cause
            truncation and corruption. The file will be decoded and saved as a
            ready-to-use file at the given path.

            Parameters:
                attachment_id: The ID of the ir.attachment record.
                as_text: If True, decode text MIME types and return content as
                    a string (only works for text/plain, text/csv, etc.).
                save_path: Absolute filesystem path to save the file to (e.g.
                    "/tmp/report.pdf"). When provided, the binary content is
                    decoded from base64 and written directly to this path.
                    The response will contain the saved path instead of the
                    raw base64 data. Parent directories are created
                    automatically. This is the preferred method for any
                    non-text attachment.

            Safety limits (REQ-09-15):
            - Max size: 12 MB. Oversized: returns metadata only + warning.
            - Text decoding only for text MIME types.
            - Binary content returned as base64 (unless save_path is used).
            """
            if not attachment_id:
                return {"status": "error", "message": "attachment_id is required."}

            # Read metadata first
            attachments = await connection.search_read(
                "ir.attachment",
                [("id", "=", attachment_id)],
                fields=["name", "mimetype", "file_size"],
            )
            if not attachments:
                return {"status": "error", "message": f"Attachment {attachment_id} not found."}

            att = attachments[0]
            file_size = att.get("file_size", 0)
            mimetype_val = att.get("mimetype", "")
            att_name = att.get("name", "")

            # Size limit check (REQ-09-15)
            if file_size > MAX_ATTACHMENT_SIZE_BYTES:
                return {
                    "id": attachment_id,
                    "name": att_name,
                    "mimetype": mimetype_val,
                    "file_size": file_size,
                    "file_size_human": format_size_human(file_size),
                    "warning": (
                        f"Attachment exceeds maximum download size of "
                        f"{format_size_human(MAX_ATTACHMENT_SIZE_BYTES)}. "
                        f"Only metadata returned."
                    ),
                    "encoding": None,
                }

            # Read the content (datas field contains base64 content)
            att_data = await connection.search_read(
                "ir.attachment",
                [("id", "=", attachment_id)],
                fields=["datas"],
            )
            raw_b64 = (att_data[0].get("datas", "") or "") if att_data else ""

            # Save to file path — decode base64 and write directly to disk
            if save_path:
                if not raw_b64:
                    return {
                        "status": "error",
                        "message": f"Attachment {attachment_id} has no content to save.",
                    }
                try:
                    save_dest = Path(save_path)
                    save_dest.parent.mkdir(parents=True, exist_ok=True)
                    content_bytes = base64.b64decode(raw_b64)
                    save_dest.write_bytes(content_bytes)
                    return {
                        "id": attachment_id,
                        "name": att_name,
                        "mimetype": mimetype_val,
                        "file_size": file_size,
                        "file_size_human": format_size_human(file_size),
                        "saved_to": str(save_dest.resolve()),
                        "message": (
                            f"File '{att_name}' saved to {save_dest.resolve()} "
                            f"({format_size_human(file_size)})."
                        ),
                    }
                except Exception as exc:
                    return {
                        "status": "error",
                        "message": f"Failed to save file to '{save_path}': {exc}",
                    }

            # Text decoding (REQ-09-15, REQ-09-16)
            if as_text and mimetype_val in TEXT_MIME_TYPES and raw_b64:
                try:
                    content_bytes = base64.b64decode(raw_b64)
                    content_text = content_bytes.decode("utf-8")
                    return {
                        "id": attachment_id,
                        "name": att_name,
                        "mimetype": mimetype_val,
                        "file_size": file_size,
                        "content": content_text,
                        "encoding": "text",
                    }
                except (UnicodeDecodeError, Exception):
                    pass  # Fall through to base64

            # Binary response (REQ-09-16)
            return {
                "id": attachment_id,
                "name": att_name,
                "mimetype": mimetype_val,
                "file_size": file_size,
                "content_base64": raw_b64,
                "encoding": "base64",
            }

        @server.tool()
        async def odoo_attachments_upload(
            model: str = "",
            record_id: int = 0,
            name: str = "",
            content_base64: str = "",
            mimetype: str | None = None,
        ) -> dict[str, Any]:
            """Upload a file as an attachment to a record (REQ-09-17 to REQ-09-19).

            MIME type auto-detected from file name if omitted.
            Not allowed in readonly mode (REQ-09-19).
            """
            if not model or not record_id:
                return {"status": "error", "message": "model and record_id are required."}
            if not name:
                return {"status": "error", "message": "name is required."}
            if not content_base64:
                return {"status": "error", "message": "content_base64 is required."}

            # Auto-detect MIME type (REQ-09-18)
            if not mimetype:
                guessed, _ = mimetypes.guess_type(name)
                mimetype = guessed or "application/octet-stream"

            # REQ-09-18
            values: dict[str, Any] = {
                "name": name,
                "datas": content_base64,
                "res_model": model,
                "res_id": record_id,
                "mimetype": mimetype,
            }

            attachment_id = await connection.execute_kw(
                "ir.attachment", "create", [values]
            )

            return {
                "id": attachment_id,
                "name": name,
                "model": model,
                "record_id": record_id,
                "mimetype": mimetype,
                "message": f"Attachment '{name}' uploaded successfully.",
            }

        @server.tool()
        async def odoo_attachments_delete(
            attachment_id: int = 0,
        ) -> dict[str, Any]:
            """Delete an attachment (REQ-09-20, REQ-09-21).

            Only allowed in 'full' operation mode.
            Annotation: destructiveHint=True.
            """
            if not attachment_id:
                return {"status": "error", "message": "attachment_id is required."}

            # Read metadata before deletion for response
            attachments = await connection.search_read(
                "ir.attachment",
                [("id", "=", attachment_id)],
                fields=["name"],
            )
            if not attachments:
                return {"status": "error", "message": f"Attachment {attachment_id} not found."}

            att_name = attachments[0].get("name", "")

            await connection.execute_kw(
                "ir.attachment", "unlink", [[attachment_id]]
            )

            return {
                "id": attachment_id,
                "name": att_name,
                "message": f"Attachment '{att_name}' deleted.",
            }

        return [
            "odoo_attachments_list",
            "odoo_attachments_get_content",
            "odoo_attachments_upload",
            "odoo_attachments_delete",
        ]
