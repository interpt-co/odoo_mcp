"""Configuration management - stub for Group 1.

Defines the OdooMcpConfig interface used by Group 5 for mode/safety settings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class OdooMcpConfig:
    """Server configuration (Group 1 implements the full Pydantic model)."""

    odoo_url: str = "http://localhost:8069"
    odoo_db: str = ""
    odoo_username: str = "admin"
    odoo_password: str = "admin"
    operation_mode: Literal["readonly", "readwrite", "full"] = "readwrite"
    enabled_toolsets: list[str] = field(default_factory=list)
    disabled_toolsets: list[str] = field(default_factory=list)
    max_attachment_size_mb: int = 12
