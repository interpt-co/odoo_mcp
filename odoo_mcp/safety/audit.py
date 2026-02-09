"""
Audit logging for the Odoo MCP server.

Implements JSONL audit logging for tool invocations with data sanitization
(REQ-11-22 through REQ-11-24).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Fields that must never be logged (REQ-11-24)
_SENSITIVE_FIELD_NAMES = frozenset({
    "password", "password_crypt", "passwd", "secret",
    "api_key", "api_key_ids", "token", "access_token",
    "oauth_access_token", "totp_secret", "new_password",
    "confirm_password",
})


@dataclass
class AuditConfig:
    """Audit logging configuration (REQ-11-22)."""

    enabled: bool = False
    log_file: str | None = None
    log_reads: bool = False
    log_writes: bool = True
    log_deletes: bool = True


class AuditLogger:
    """Audit logger that writes JSONL entries to a file (REQ-11-22 through REQ-11-24).

    Async file writing for non-blocking operation.
    """

    def __init__(self, config: AuditConfig | None = None):
        self._config = config or AuditConfig()
        self._file_handle = None
        try:
            loop = asyncio.get_running_loop()
            self._lock: asyncio.Lock | None = asyncio.Lock()
        except RuntimeError:
            self._lock = None

    @property
    def config(self) -> AuditConfig:
        return self._config

    async def log_operation(
        self,
        tool: str,
        model: str,
        operation: str,
        values: dict[str, Any] | None,
        result: Any,
        success: bool,
        duration_ms: int,
        session_id: str,
        odoo_uid: int,
    ) -> None:
        """Log an operation to the audit file (REQ-11-23).

        Args:
            tool: Tool name (e.g., "odoo_core_create").
            model: Odoo model name.
            operation: Operation type ("read", "create", "write", "unlink", "execute").
            values: Input values (sanitized before logging).
            result: Operation result.
            success: Whether the operation succeeded.
            duration_ms: Duration in milliseconds.
            session_id: MCP session ID.
            odoo_uid: Odoo user ID.
        """
        if not self._config.enabled:
            return

        # Check if this operation type should be logged
        if not self._should_log(operation):
            return

        # Build the audit entry (REQ-11-23)
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "tool": tool,
            "model": model,
            "operation": operation,
            "success": success,
            "duration_ms": duration_ms,
            "odoo_uid": odoo_uid,
        }

        # Sanitize and add values (REQ-11-24)
        if values is not None:
            entry["values"] = self._sanitize_values(values)

        # Add result info
        if result is not None:
            entry.update(self._sanitize_result(result, operation))

        await self._write_entry(entry)

    def _should_log(self, operation: str) -> bool:
        """Check if the operation type should be logged."""
        if operation in ("read", "search"):
            return self._config.log_reads
        if operation in ("create", "write", "execute"):
            return self._config.log_writes
        if operation == "unlink":
            return self._config.log_deletes
        # Default: log writes
        return self._config.log_writes

    def _sanitize_values(self, values: dict[str, Any]) -> dict[str, Any]:
        """Sanitize values for logging (REQ-11-24).

        - Never log passwords or API keys.
        - Never log binary field content (log field names only).
        """
        sanitized: dict[str, Any] = {}
        for key, val in values.items():
            # Never log sensitive fields
            if key.lower() in _SENSITIVE_FIELD_NAMES:
                sanitized[key] = "***REDACTED***"
            # Never log binary content
            elif isinstance(val, bytes):
                sanitized[key] = f"<binary {len(val)} bytes>"
            elif isinstance(val, str) and len(val) > 1000 and _looks_like_base64(val):
                sanitized[key] = f"<binary-b64 {len(val)} chars>"
            else:
                sanitized[key] = val
        return sanitized

    def _sanitize_result(self, result: Any, operation: str) -> dict[str, Any]:
        """Sanitize the result for logging (REQ-11-24).

        For read operations: log domain/IDs only, not full record data.
        For create: log result_id.
        """
        if operation == "create":
            if isinstance(result, int):
                return {"result_id": result}
            if isinstance(result, list) and result and isinstance(result[0], int):
                return {"result_ids": result}

        if operation in ("read", "search"):
            # Only log IDs, not full data
            if isinstance(result, list):
                ids = []
                for r in result:
                    if isinstance(r, dict) and "id" in r:
                        ids.append(r["id"])
                    elif isinstance(r, int):
                        ids.append(r)
                if ids:
                    return {"result_count": len(result), "result_ids": ids[:20]}
                return {"result_count": len(result)}

        if operation == "write":
            return {"result": bool(result)}

        if operation == "unlink":
            return {"result": bool(result)}

        return {}

    async def _write_entry(self, entry: dict[str, Any]) -> None:
        """Write a single JSONL entry to the log file (async, non-blocking)."""
        if not self._config.log_file:
            logger.debug("Audit entry (no file configured): %s", json.dumps(entry))
            return

        line = json.dumps(entry, default=str) + "\n"

        try:
            # Use asyncio to write without blocking
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._sync_write, line)
        except Exception:
            logger.exception("Failed to write audit log entry")

    def _sync_write(self, line: str) -> None:
        """Synchronous file write (called in executor)."""
        log_path = Path(self._config.log_file)  # type: ignore[arg-type]
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)

    async def close(self) -> None:
        """Close the audit logger."""
        pass  # File is opened/closed per write; nothing to close


def _looks_like_base64(value: str) -> bool:
    """Heuristic check if a string looks like base64 binary data."""
    if len(value) < 100:
        return False
    # Base64 typically contains only a-zA-Z0-9+/= chars
    import re
    sample = value[:200]
    non_b64 = re.sub(r"[A-Za-z0-9+/=\n\r]", "", sample)
    return len(non_b64) < len(sample) * 0.05
