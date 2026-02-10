"""Reports Toolset.

Implements PDF report generation per SPEC-09 (REQ-09-22 through REQ-09-26).

Uses a 3-tier strategy for PDF generation:
  Tier 1 - Existing Attachment: check ir.attachment for previously-generated PDF
  Tier 2 - mail.compose.message: create wizard with mail.template to trigger
           _render_qweb_pdf server-side (pure RPC, no HTTP needed)
  Tier 3 - HTTP fallback: use connection.render_report() via /report/pdf/
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from odoo_mcp.connection.manager import ConnectionManager
from odoo_mcp.toolsets.base import BaseToolset, ToolsetMetadata
from odoo_mcp.toolsets.formatting import format_size_human, save_binary_to_file

logger = logging.getLogger("odoo_mcp.toolsets.reports")


class ReportsToolset(BaseToolset):
    """PDF report generation tools."""

    def metadata(self) -> ToolsetMetadata:
        return ToolsetMetadata(
            name="reports",
            description="PDF report generation",
            required_modules=[],
            depends_on=["core"],
        )

    async def register_tools(
        self, server: Any, connection: ConnectionManager, **kwargs: Any
    ) -> list[str]:

        # Cache: report_id -> template_id (or None if no template found)
        _template_cache: dict[int, int | None] = {}

        async def _find_report_action(report_name: str) -> dict[str, Any] | None:
            """Look up ir.actions.report by report_name."""
            results = await connection.search_read(
                "ir.actions.report",
                [("report_name", "=", report_name)],
                fields=["id", "model", "attachment", "attachment_use"],
                limit=1,
            )
            return results[0] if results else None

        async def _try_existing_attachment(
            report_action: dict[str, Any], record_id: int
        ) -> str | None:
            """Tier 1: Check for a previously-generated PDF attachment.

            Only applicable when attachment_use is True and attachment
            expression is non-empty.  Returns base64 PDF data or None.
            """
            if not report_action.get("attachment_use"):
                return None
            if not report_action.get("attachment"):
                return None

            model = report_action.get("model", "")
            domain: list[Any] = [
                ("res_model", "=", model),
                ("res_id", "=", record_id),
                ("mimetype", "=", "application/pdf"),
            ]
            attachments = await connection.search_read(
                "ir.attachment",
                domain,
                fields=["id", "name", "datas"],
                limit=1,
                order="id desc",
            )
            if attachments and attachments[0].get("datas"):
                logger.info(
                    "Tier 1: Found existing attachment %s for %s/%d",
                    attachments[0].get("name"),
                    model,
                    record_id,
                )
                return attachments[0]["datas"]
            return None

        async def _find_template_for_report(report_id: int) -> int | None:
            """Find a mail.template linked to the given report action.

            Tries report_template_ids (v17+) then report_template (v14-v16).
            """
            if report_id in _template_cache:
                return _template_cache[report_id]

            template_id: int | None = None

            # Try v17+ field: report_template_ids (Many2many)
            try:
                results = await connection.search_read(
                    "mail.template",
                    [("report_template_ids", "in", [report_id])],
                    fields=["id"],
                    limit=1,
                )
                if results:
                    template_id = results[0]["id"]
            except Exception:
                pass

            # Try v14-v16 field: report_template (Many2one)
            if template_id is None:
                try:
                    results = await connection.search_read(
                        "mail.template",
                        [("report_template", "=", report_id)],
                        fields=["id"],
                        limit=1,
                    )
                    if results:
                        template_id = results[0]["id"]
                except Exception:
                    pass

            _template_cache[report_id] = template_id
            return template_id

        async def _try_mail_compose_message(
            template_id: int, model: str, record_id: int
        ) -> str | None:
            """Tier 2: Create mail.compose.message wizard to trigger PDF generation.

            Creating the wizard with a template triggers _compute_attachment_ids
            (stored compute), which calls _render_qweb_pdf server-side.
            No email is sent — we only create the wizard, never call send().

            Returns base64 PDF data or None.
            """
            try:
                ctx = {
                    "default_template_id": template_id,
                    "default_model": model,
                    "default_res_ids": [record_id],
                }
                wizard_id = await connection.execute_kw(
                    "mail.compose.message",
                    "create",
                    [{
                        "template_id": template_id,
                        "model": model,
                        "res_ids": [record_id],
                        "composition_mode": "comment",
                    }],
                    context=ctx,
                )

                # Read the wizard's attachment_ids (populated by compute)
                wizard_data = await connection.execute_kw(
                    "mail.compose.message",
                    "read",
                    [[wizard_id], ["attachment_ids"]],
                )
                if not wizard_data:
                    return None

                row = wizard_data[0] if isinstance(wizard_data, list) else wizard_data
                attachment_ids = row.get("attachment_ids", [])
                if not attachment_ids:
                    return None

                # Fetch attachment data
                attachments = await connection.search_read(
                    "ir.attachment",
                    [("id", "in", attachment_ids)],
                    fields=["name", "datas"],
                )

                # Prefer PDF attachment
                for att in attachments:
                    if att.get("name", "").lower().endswith(".pdf") and att.get("datas"):
                        logger.info(
                            "Tier 2: Generated PDF via mail.compose.message: %s",
                            att["name"],
                        )
                        return att["datas"]

                # Take first attachment with data
                for att in attachments:
                    if att.get("datas"):
                        logger.info(
                            "Tier 2: Generated attachment via mail.compose.message: %s",
                            att.get("name"),
                        )
                        return att["datas"]

            except Exception as exc:
                logger.debug("Tier 2 (mail.compose.message) failed: %s", exc)

            return None

        def _parse_render_result(result: Any) -> str:
            """Extract base64 PDF content from render_report result."""
            if isinstance(result, dict) and "result" in result:
                return result["result"]
            if isinstance(result, (list, tuple)) and len(result) >= 1:
                pdf_bytes = result[0]
                if isinstance(pdf_bytes, bytes):
                    return base64.b64encode(pdf_bytes).decode("ascii")
                if isinstance(pdf_bytes, str):
                    return pdf_bytes
            if isinstance(result, bytes):
                return base64.b64encode(result).decode("ascii")
            if isinstance(result, str):
                return result
            return ""

        def _build_response(
            report_name: str,
            record_ids: list[int],
            content_b64: str,
            generation_method: str,
        ) -> dict[str, Any]:
            """Build report response with auto-save to temp file."""
            try:
                size = len(base64.b64decode(content_b64)) if content_b64 else 0
            except Exception:
                size = 0

            file_name = (
                f"{report_name.split('.')[-1]}"
                f"_{'-'.join(str(r) for r in record_ids)}.pdf"
            )

            resp: dict[str, Any] = {
                "report_name": report_name,
                "record_ids": record_ids,
                "format": "pdf",
                "content_base64": content_b64,
                "file_name": file_name,
                "size": size,
                "size_human": format_size_human(size),
                "generation_method": generation_method,
            }

            # Auto-save to temp file for easy access
            if content_b64:
                saved_to = save_binary_to_file(
                    content_b64,
                    "report",
                    record_ids[0] if record_ids else None,
                    report_name.replace(".", "_"),
                )
                if saved_to:
                    resp["saved_to"] = saved_to

            return resp

        @server.tool()
        async def odoo_reports_generate(
            report_name: str = "",
            record_ids: list[int] | None = None,
            context: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            """Generate a PDF report for records (REQ-09-22 to REQ-09-24).

            report_name: Technical report name (e.g. 'sale.report_saleorder').
            record_ids: Record IDs to include (max 20).
            Annotation: readOnlyHint=True (reports don't modify data).

            Protocol-specific generation (REQ-09-23):
            - XML-RPC (Odoo 14-16): /xmlrpc/2/report render_report
            - JSON-RPC/JSON-2 (Odoo 17+): ir.actions.report._render_qweb_pdf
            """
            if not report_name:
                return {"status": "error", "message": "report_name is required."}
            if not record_ids:
                return {"status": "error", "message": "record_ids is required."}
            if len(record_ids) > 20:
                return {
                    "status": "error",
                    "message": "Maximum 20 record_ids allowed per report.",
                }

            # Look up the report action for Tier 1 & 2 metadata
            report_action = await _find_report_action(report_name)

            # Single-record requests can use Tier 1 and Tier 2
            if report_action and len(record_ids) == 1:
                record_id = record_ids[0]

                # Tier 1: Existing attachment (free, no side-effects)
                try:
                    b64 = await _try_existing_attachment(report_action, record_id)
                    if b64:
                        return _build_response(
                            report_name, record_ids, b64, "existing_attachment"
                        )
                except Exception as exc:
                    logger.debug("Tier 1 failed: %s", exc)

                # Tier 2: mail.compose.message (pure RPC)
                template_id = await _find_template_for_report(report_action["id"])
                if template_id:
                    b64 = await _try_mail_compose_message(
                        template_id, report_action["model"], record_id
                    )
                    if b64:
                        return _build_response(
                            report_name, record_ids, b64, "mail_compose"
                        )

            # Tier 3: HTTP fallback (existing approach)
            try:
                result = await connection.render_report(report_name, record_ids)
            except Exception as exc:
                return {
                    "status": "error",
                    "message": f"Report generation failed: {exc}",
                }

            content_b64 = _parse_render_result(result)
            return _build_response(
                report_name, record_ids, content_b64, "http_render"
            )

        @server.tool()
        async def odoo_reports_list(
            model: str = "",
        ) -> dict[str, Any]:
            """List available reports for a model (REQ-09-25, REQ-09-26).
            """
            if not model:
                return {"status": "error", "message": "model is required."}

            # REQ-09-26
            domain: list[Any] = [("model", "=", model)]
            reports = await connection.search_read(
                "ir.actions.report",
                domain,
                fields=["name", "report_name", "report_type", "print_report_name"],
            )

            return {
                "model": model,
                "reports": [
                    {
                        "name": r.get("name", ""),
                        "report_name": r.get("report_name", ""),
                        "report_type": r.get("report_type", ""),
                    }
                    for r in reports
                ],
            }

        return [
            "odoo_reports_generate",
            "odoo_reports_list",
        ]
