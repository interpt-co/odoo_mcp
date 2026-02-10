"""Project Toolset.

Implements project management workflows per SPEC-05 (REQ-05-30 through REQ-05-33).
"""

from __future__ import annotations

import logging
from typing import Any

from odoo_mcp.connection.manager import ConnectionManager
from odoo_mcp.toolsets.base import BaseToolset, ToolsetMetadata
from odoo_mcp.toolsets.formatting import format_many2one
from odoo_mcp.toolsets.helpers import resolve_name

logger = logging.getLogger("odoo_mcp.toolsets.project")


class ProjectToolset(BaseToolset):
    """Project and task management tools."""

    def metadata(self) -> ToolsetMetadata:
        return ToolsetMetadata(
            name="project",
            description="Project and task management",
            required_modules=["project"],
            depends_on=["core"],
        )

    async def register_tools(
        self, server: Any, connection: ConnectionManager, **kwargs: Any
    ) -> list[str]:

        @server.tool()
        async def odoo_project_create_task(
            name: str = "",
            project_id: int | None = None,
            project_name: str | None = None,
            user_ids: list[int] | None = None,
            description: str | None = None,
            date_deadline: str | None = None,
            priority: str = "0",
            parent_id: int | None = None,
            tag_ids: list[int] | None = None,
        ) -> dict[str, Any]:
            """Create a project task (REQ-05-30).

            priority: '0'=Low (default), '1'=High.
            project_id or project_name to assign to a project.
            """
            if not name:
                return {"status": "error", "message": "name is required."}

            vals: dict[str, Any] = {
                "name": name,
                "priority": priority,
            }

            if project_id or project_name:
                resolved = await resolve_name(
                    connection, "project.project", project_id, project_name, "project"
                )
                if isinstance(resolved, dict):
                    return resolved
                vals["project_id"] = resolved

            if user_ids:
                vals["user_ids"] = [(6, 0, user_ids)]
            if description:
                vals["description"] = description
            if date_deadline:
                vals["date_deadline"] = date_deadline
            if parent_id:
                vals["parent_id"] = parent_id
            if tag_ids:
                vals["tag_ids"] = [(6, 0, tag_ids)]

            task_id = await connection.execute_kw(
                "project.task", "create", [vals]
            )

            tasks = await connection.search_read(
                "project.task",
                [("id", "=", task_id)],
                fields=["name", "project_id", "stage_id", "user_ids", "priority"],
            )
            task = tasks[0] if tasks else {}

            return {
                "id": task_id,
                "name": task.get("name", name),
                "project": format_many2one(task.get("project_id")),
                "stage": format_many2one(task.get("stage_id")),
                "priority": task.get("priority", priority),
                "message": f"Created task '{name}'.",
            }

        @server.tool()
        async def odoo_project_move_stage(
            task_id: int = 0,
            stage_id: int | None = None,
            stage_name: str | None = None,
        ) -> dict[str, Any]:
            """Move a task to a different kanban stage (REQ-05-31).

            Accepts stage_id or stage_name for resolution.
            """
            if not task_id:
                return {"status": "error", "message": "task_id is required."}

            resolved_stage = await resolve_name(
                connection, "project.task.type", stage_id, stage_name, "stage"
            )
            if isinstance(resolved_stage, dict):
                return resolved_stage

            await connection.execute_kw(
                "project.task", "write", [[task_id], {"stage_id": resolved_stage}]
            )

            tasks = await connection.search_read(
                "project.task",
                [("id", "=", task_id)],
                fields=["name", "stage_id"],
            )
            task = tasks[0] if tasks else {}

            return {
                "id": task_id,
                "name": task.get("name", ""),
                "stage": format_many2one(task.get("stage_id")),
                "message": "Task stage updated.",
            }

        @server.tool()
        async def odoo_project_log_timesheet(
            task_id: int = 0,
            hours: float = 0.0,
            description: str = "",
            date: str | None = None,
            user_id: int | None = None,
        ) -> dict[str, Any]:
            """Log a timesheet entry on a task (REQ-05-32, REQ-05-33).

            Creates an account.analytic.line record linked to the task.
            Requires the hr_timesheet module.
            """
            if not task_id:
                return {"status": "error", "message": "task_id is required."}
            if hours <= 0:
                return {"status": "error", "message": "hours must be positive."}

            # Get task's project for the analytic account
            tasks = await connection.search_read(
                "project.task",
                [("id", "=", task_id)],
                fields=["name", "project_id"],
            )
            if not tasks:
                return {"status": "error", "message": f"Task {task_id} not found."}

            task = tasks[0]
            project_m2o = task.get("project_id")
            project_id = None
            if isinstance(project_m2o, (list, tuple)):
                project_id = project_m2o[0]
            elif isinstance(project_m2o, int):
                project_id = project_m2o

            vals: dict[str, Any] = {
                "task_id": task_id,
                "name": description or "/",
                "unit_amount": hours,
            }

            if project_id:
                vals["project_id"] = project_id
            if date:
                vals["date"] = date
            if user_id:
                vals["user_id"] = user_id

            try:
                line_id = await connection.execute_kw(
                    "account.analytic.line", "create", [vals]
                )
            except Exception as exc:
                return {
                    "status": "error",
                    "message": (
                        f"Failed to log timesheet: {exc}. "
                        f"Ensure the hr_timesheet module is installed."
                    ),
                }

            return {
                "id": line_id,
                "task_id": task_id,
                "task_name": task.get("name", ""),
                "hours": hours,
                "description": description,
                "message": f"Logged {hours}h on task '{task.get('name', '')}'.",
            }

        return [
            "odoo_project_create_task",
            "odoo_project_move_stage",
            "odoo_project_log_timesheet",
        ]
