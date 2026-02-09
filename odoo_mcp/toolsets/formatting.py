"""Response normalisation utilities shared by all tools.

Implements REQ-04-05, REQ-04-35 through REQ-04-37, REQ-08-18, REQ-08-19.
"""

from __future__ import annotations

import html
import re
from typing import Any

# ---------------------------------------------------------------------------
# Known HTML field names (REQ-08-18)
# ---------------------------------------------------------------------------

KNOWN_HTML_FIELDS: set[str] = {
    "description",
    "comment",
    "body",
    "note",
    "notes",
    "narration",
    "description_sale",
    "description_purchase",
    "website_description",
}


# ---------------------------------------------------------------------------
# HTML stripping (REQ-08-19)
# ---------------------------------------------------------------------------

def strip_html(html_content: str) -> str:
    """Strip HTML tags and decode entities to plain text."""
    if not html_content:
        return ""
    # Replace <br> and </p> with newlines
    text = re.sub(r"<br\s*/?>", "\n", html_content, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    # Remove all remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    # Decode HTML entities
    text = html.unescape(text)
    # Clean up whitespace
    text = re.sub(r"\n\s*\n", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Datetime normalisation (REQ-04-37)
# ---------------------------------------------------------------------------

_ODOO_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


def normalize_datetime(value: str) -> str:
    """Convert ``"2025-02-09 14:30:00"`` → ``"2025-02-09T14:30:00Z"``."""
    if _ODOO_DATETIME_RE.match(value):
        return value.replace(" ", "T") + "Z"
    return value


# ---------------------------------------------------------------------------
# Field-level normalisation helpers
# ---------------------------------------------------------------------------

def _normalize_many2one(value: Any) -> Any:
    """``[1, "Name"]`` → ``{"id": 1, "name": "Name"}``, ``False`` → ``None``."""
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return {"id": value[0], "name": value[1]}
    if value is False:
        return None
    return value


def format_many2one(value: Any) -> dict[str, Any] | None:
    """Format an Odoo many2one field value to ``{"id": ..., "name": ...}``.

    Handles ``[id, name]`` tuples/lists, ``False``, ``None``, and dict passthrough.
    """
    if not value:
        return None
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return {"id": value[0], "name": value[1]}
    if isinstance(value, dict):
        return value
    return None


def _normalize_false(value: Any, field_type: str | None) -> Any:
    """Map Odoo's ``False`` sentinel depending on field type (REQ-04-35)."""
    if value is not False:
        return value
    if field_type in ("char", "text", "html"):
        return ""
    # date, datetime, many2one, binary, etc. → null
    return None


# ---------------------------------------------------------------------------
# Size formatting
# ---------------------------------------------------------------------------

def format_size_human(size_bytes: int) -> str:
    """Convert bytes to human-readable size string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalize_record(
    record: dict[str, Any],
    field_types: dict[str, str] | None = None,
    *,
    strip_html_fields: bool = True,
    exclude_binary: bool = True,
    requested_fields: set[str] | None = None,
) -> dict[str, Any]:
    """Apply all normalisation rules to a single record dict.

    Parameters
    ----------
    record:
        Raw Odoo record dictionary.
    field_types:
        Mapping of ``field_name → field_type`` (e.g. from ``fields_get``).
        When *None*, heuristic normalisation is applied.
    strip_html_fields:
        Strip HTML from known HTML fields (REQ-08-18).
    exclude_binary:
        Remove binary fields unless they were explicitly requested
        (REQ-04-36).
    requested_fields:
        Fields that were explicitly requested by the caller.  Binary fields
        present in this set are kept.
    """
    if field_types is None:
        field_types = {}
    if requested_fields is None:
        requested_fields = set()

    normalised: dict[str, Any] = {}
    for fname, value in record.items():
        ftype = field_types.get(fname)

        # Binary field exclusion (REQ-04-36)
        if ftype == "binary" and exclude_binary and fname not in requested_fields:
            continue

        # False normalisation (REQ-04-35)
        if value is False:
            value = _normalize_false(value, ftype)

        # Many2one normalisation (REQ-04-05 / REQ-04-35)
        elif ftype == "many2one" or (
            ftype is None and isinstance(value, (list, tuple)) and len(value) == 2
            and isinstance(value[0], int) and isinstance(value[1], str)
        ):
            value = _normalize_many2one(value)

        # Datetime normalisation (REQ-04-37)
        elif ftype in ("datetime",) and isinstance(value, str):
            value = normalize_datetime(value)
        elif ftype is None and isinstance(value, str) and _ODOO_DATETIME_RE.match(value):
            value = normalize_datetime(value)

        # HTML stripping (REQ-08-18 / REQ-08-19)
        if strip_html_fields and isinstance(value, str):
            if ftype == "html" or fname in KNOWN_HTML_FIELDS:
                value = strip_html(value)

        normalised[fname] = value

    return normalised


def normalize_records(
    records: list[dict[str, Any]],
    field_types: dict[str, str] | None = None,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Apply normalisation to a list of records."""
    return [normalize_record(r, field_types, **kwargs) for r in records]
