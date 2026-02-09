"""Static registry data loader.

Loads pre-generated JSON registry files into Registry objects.
Implements REQ-07-08.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from odoo_mcp.registry.model_registry import Registry

logger = logging.getLogger(__name__)

DEFAULT_STATIC_PATH = Path(__file__).parent / "static_data.json"


def load_static_registry(path: Path | str | None = None) -> Registry | None:
    """Load a static registry from a JSON file.

    Returns None if the file does not exist or is invalid.
    """
    file_path = Path(path) if path else DEFAULT_STATIC_PATH
    if not file_path.exists():
        logger.info("No static registry file at %s", file_path)
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load static registry from %s: %s", file_path, exc)
        return None

    try:
        registry = Registry.from_dict(data)
        registry.build_mode = "static"
        logger.info(
            "Loaded static registry: %d models, %d fields (version=%s)",
            registry.model_count, registry.field_count, registry.version,
        )
        return registry
    except Exception as exc:
        logger.warning("Failed to parse static registry: %s", exc)
        return None


def save_static_registry(registry: Registry, path: Path | str | None = None) -> None:
    """Save a registry to a JSON file."""
    file_path = Path(path) if path else DEFAULT_STATIC_PATH
    file_path.parent.mkdir(parents=True, exist_ok=True)
    data = registry.to_dict()
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("Saved static registry to %s", file_path)
