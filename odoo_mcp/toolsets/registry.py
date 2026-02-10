"""Toolset registry — discovery, dependency resolution, and registration.

Implements REQ-03-04 through REQ-03-12, REQ-03-15 through REQ-03-18.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from .base import BaseToolset, ToolsetMetadata

logger = logging.getLogger("odoo_mcp.toolsets.registry")

# ---------------------------------------------------------------------------
# Registration report dataclasses (REQ-03-09 / REQ-03-10)
# ---------------------------------------------------------------------------


@dataclass
class ToolsetRegistrationResult:
    name: str
    status: Literal["registered", "skipped", "failed"]
    tools_registered: list[str] = field(default_factory=list)
    skip_reason: str | None = None
    error: str | None = None


@dataclass
class RegistrationReport:
    results: list[ToolsetRegistrationResult] = field(default_factory=list)
    total_toolsets: int = 0
    registered_toolsets: int = 0
    total_tools: int = 0
    timestamp: str = ""


# ---------------------------------------------------------------------------
# Toolset catalog (REQ-03-15)
# ---------------------------------------------------------------------------

TOOLSET_CATALOG: dict[str, dict[str, Any]] = {
    "core": {"required_modules": [], "depends_on": [], "min_version": 14},
    "sales": {"required_modules": ["sale"], "depends_on": ["core"], "min_version": 14},
    "accounting": {"required_modules": ["account"], "depends_on": ["core"], "min_version": 14},
    "inventory": {"required_modules": ["stock"], "depends_on": ["core"], "min_version": 14},
    "crm": {"required_modules": ["crm"], "depends_on": ["core"], "min_version": 14},
    "helpdesk": {"required_modules": ["helpdesk"], "depends_on": ["core"], "min_version": 14},
    "project": {"required_modules": ["project"], "depends_on": ["core"], "min_version": 14},
    "chatter": {"required_modules": ["mail"], "depends_on": ["core"], "min_version": 14},
    "attachments": {"required_modules": [], "depends_on": ["core"], "min_version": 14},
    "reports": {"required_modules": [], "depends_on": ["core"], "min_version": 14},
}


# ---------------------------------------------------------------------------
# Topological sort (REQ-03-06)
# ---------------------------------------------------------------------------

class CircularDependencyError(Exception):
    """Raised when a circular dependency is detected among toolsets."""


def _topological_sort(toolsets: list[BaseToolset]) -> list[BaseToolset]:
    """Sort *toolsets* so that dependencies come before dependants.

    Raises :class:`CircularDependencyError` if a cycle is detected.
    """
    by_name: dict[str, BaseToolset] = {t.metadata().name: t for t in toolsets}
    visited: set[str] = set()
    in_stack: set[str] = set()
    order: list[str] = []

    def visit(name: str, path: list[str]) -> None:
        if name in in_stack:
            cycle = path[path.index(name) :] + [name]
            raise CircularDependencyError(
                f"Circular dependency detected: {' → '.join(cycle)}"
            )
        if name in visited:
            return
        in_stack.add(name)
        ts = by_name.get(name)
        if ts is not None:
            for dep in ts.metadata().depends_on:
                visit(dep, path + [name])
        in_stack.discard(name)
        visited.add(name)
        order.append(name)

    for name in by_name:
        visit(name, [])

    return [by_name[n] for n in order if n in by_name]


# ---------------------------------------------------------------------------
# ToolsetRegistry (REQ-03-04)
# ---------------------------------------------------------------------------

class ToolsetRegistry:
    """Discovers, filters, and registers toolsets."""

    def __init__(self, connection: Any, config: Any) -> None:
        self._connection = connection
        self._config = config
        self._registered: dict[str, ToolsetMetadata] = {}
        self._tool_to_toolset: dict[str, ToolsetMetadata] = {}
        self._report: RegistrationReport | None = None

    # -- public API --------------------------------------------------------

    async def discover_and_register(
        self,
        server: Any,
        toolset_classes: list[type[BaseToolset]] | None = None,
    ) -> RegistrationReport:
        """Discover, filter, and register all eligible toolsets (REQ-03-04)."""
        from . import ALL_TOOLSETS

        classes = toolset_classes if toolset_classes is not None else ALL_TOOLSETS
        instances = [cls() for cls in classes]

        # Topological sort (REQ-03-06)
        sorted_toolsets = _topological_sort(instances)

        report = RegistrationReport(
            total_toolsets=len(sorted_toolsets),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # Fetch installed modules once for prerequisite checking
        installed_modules = await self._fetch_installed_modules()
        odoo_version = self._get_odoo_version()

        for ts in sorted_toolsets:
            meta = ts.metadata()
            result = ToolsetRegistrationResult(name=meta.name, status="registered")

            # --- Config filter (REQ-03-07.4) ---
            skip = self._check_config_filter(meta.name)
            if skip:
                result.status = "skipped"
                result.skip_reason = skip
                report.results.append(result)
                logger.info("Toolset '%s' skipped: %s", meta.name, skip)
                continue

            # --- Module prerequisites (REQ-03-07.1) ---
            skip = self._check_modules(meta, installed_modules)
            if skip:
                result.status = "skipped"
                result.skip_reason = skip
                report.results.append(result)
                logger.info("Toolset '%s' skipped: %s", meta.name, skip)
                continue

            # --- Version prerequisites (REQ-03-07.2) ---
            skip = self._check_version(meta, odoo_version)
            if skip:
                result.status = "skipped"
                result.skip_reason = skip
                report.results.append(result)
                logger.info("Toolset '%s' skipped: %s", meta.name, skip)
                continue

            # --- Dependency prerequisites (REQ-03-07.3) ---
            skip = self._check_dependencies(meta)
            if skip:
                result.status = "skipped"
                result.skip_reason = skip
                report.results.append(result)
                logger.info("Toolset '%s' skipped: %s", meta.name, skip)
                continue

            # --- Register tools ---
            try:
                tool_names = await ts.register_tools(
                    server,
                    self._connection,
                    config=self._config,
                    registry=self,
                )
            except Exception as exc:
                result.status = "failed"
                result.error = str(exc)
                report.results.append(result)
                logger.error("Toolset '%s' failed: %s", meta.name, exc)
                continue

            # Unique tool name enforcement (REQ-03-12)
            for tn in tool_names:
                if tn in self._tool_to_toolset:
                    existing = self._tool_to_toolset[tn].name
                    result.status = "failed"
                    result.error = (
                        f"Duplicate tool name '{tn}' — "
                        f"already registered by toolset '{existing}'"
                    )
                    report.results.append(result)
                    logger.error(result.error)
                    break
            else:
                result.tools_registered = list(tool_names)
                self._registered[meta.name] = meta
                for tn in tool_names:
                    self._tool_to_toolset[tn] = meta
                report.results.append(result)
                logger.info(
                    "Toolset '%s' registered %d tool(s): %s",
                    meta.name,
                    len(tool_names),
                    ", ".join(tool_names),
                )

        report.registered_toolsets = len(self._registered)
        report.total_tools = len(self._tool_to_toolset)
        self._report = report

        logger.info(
            "Registration complete: %d/%d toolsets, %d tools",
            report.registered_toolsets,
            report.total_toolsets,
            report.total_tools,
        )
        return report

    def get_registered_toolsets(self) -> list[ToolsetMetadata]:
        return list(self._registered.values())

    def get_toolset_for_tool(self, tool_name: str) -> ToolsetMetadata | None:
        return self._tool_to_toolset.get(tool_name)

    def get_report(self) -> RegistrationReport | None:
        return self._report

    # -- prerequisite checks -----------------------------------------------

    async def _fetch_installed_modules(self) -> set[str]:
        """Query Odoo for installed modules (REQ-03-07.1)."""
        try:
            result = await self._connection.execute_kw(
                "ir.module.module",
                "search_read",
                [[("state", "=", "installed")]],
                {"fields": ["name"]},
            )
            return {m["name"] for m in (result or [])}
        except Exception:
            logger.warning("Could not fetch installed modules — skipping module checks")
            return set()

    def _get_odoo_version(self) -> Any:
        try:
            return getattr(self._connection, "odoo_version", None)
        except Exception:
            return None

    def _check_modules(self, meta: ToolsetMetadata, installed: set[str]) -> str | None:
        if not meta.required_modules:
            return None
        missing = [m for m in meta.required_modules if m not in installed]
        if missing:
            return f"Module(s) not installed: {', '.join(missing)}"
        return None

    def _check_version(self, meta: ToolsetMetadata, odoo_version: Any) -> str | None:
        if odoo_version is None:
            return None
        major = odoo_version.major if hasattr(odoo_version, "major") else int(odoo_version)
        if meta.min_odoo_version is not None and major < meta.min_odoo_version:
            return f"Requires Odoo >= {meta.min_odoo_version}, got {major}"
        if meta.max_odoo_version is not None and major > meta.max_odoo_version:
            return f"Requires Odoo <= {meta.max_odoo_version}, got {major}"
        return None

    def _check_dependencies(self, meta: ToolsetMetadata) -> str | None:
        if not meta.depends_on:
            return None
        missing = [d for d in meta.depends_on if d not in self._registered]
        if missing:
            return f"Depends on unregistered toolset(s): {', '.join(missing)}"
        return None

    def _check_config_filter(self, name: str) -> str | None:
        enabled = getattr(self._config, "enabled_toolsets", [])
        disabled = getattr(self._config, "disabled_toolsets", [])
        if enabled and name not in enabled:
            return f"Not in enabled_toolsets list"
        if disabled and name in disabled:
            return f"In disabled_toolsets list"
        return None
