"""Formatting utilities - stub for Group 4.

Provides response normalization helpers used by workflow tools.
"""

from __future__ import annotations

import re
from typing import Any


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


def strip_html(html: str) -> str:
    """Strip HTML tags and return plain text."""
    if not html:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#39;", "'", text)
    return text.strip()


def format_many2one(value: Any) -> dict[str, Any] | None:
    """Format an Odoo many2one field value to {id, name}."""
    if not value:
        return None
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return {"id": value[0], "name": value[1]}
    if isinstance(value, dict):
        return value
    return None
