"""Reports Toolset.

Implements PDF report generation per SPEC-09 (REQ-09-22 through REQ-09-26).
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from odoo_mcp.connection.manager import ConnectionManager
from odoo_mcp.toolsets.base import BaseToolset, ToolsetMetadata
from odoo_mcp.toolsets.formatting import format_size_human

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

    def register_tools(
        self, server: Any, connection: ConnectionManager
    ) -> list[str]:

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

            odoo_version = connection.odoo_version

            try:
                if odoo_version < 17:
                    # XML-RPC path (Odoo 14-16) (REQ-09-23)
                    result = await connection.execute_kw(
                        "ir.actions.report",
                        "render_qweb_pdf",
                        [report_name, record_ids],
                        context=context,
                    )
                else:
                    # JSON-RPC/JSON-2 path (Odoo 17+) (REQ-09-23)
                    result = await connection.execute_kw(
                        "ir.actions.report",
                        "_render_qweb_pdf",
                        [report_name, record_ids],
                        context=context,
                    )
            except Exception as exc:
                return {
                    "status": "error",
                    "message": f"Report generation failed: {exc}",
                }

            # Parse result - typically (pdf_content, report_type) or dict
            content_b64 = ""
            if isinstance(result, (list, tuple)) and len(result) >= 1:
                pdf_bytes = result[0]
                if isinstance(pdf_bytes, bytes):
                    content_b64 = base64.b64encode(pdf_bytes).decode("ascii")
                elif isinstance(pdf_bytes, str):
                    content_b64 = pdf_bytes
            elif isinstance(result, dict) and "result" in result:
                content_b64 = result["result"]
            elif isinstance(result, bytes):
                content_b64 = base64.b64encode(result).decode("ascii")
            elif isinstance(result, str):
                content_b64 = result

            # Compute size
            try:
                size = len(base64.b64decode(content_b64)) if content_b64 else 0
            except Exception:
                size = 0

            # Generate file name
            file_name = f"{report_name.split('.')[-1]}_{'-'.join(str(r) for r in record_ids)}.pdf"

            # REQ-09-24
            return {
                "report_name": report_name,
                "record_ids": record_ids,
                "format": "pdf",
                "content_base64": content_b64,
                "file_name": file_name,
                "size": size,
                "size_human": format_size_human(size),
            }

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
