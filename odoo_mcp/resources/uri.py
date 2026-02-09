"""URI scheme parser for odoo:// resources.

Implements REQ-06-01, REQ-06-11, REQ-06-12.
"""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass, field
from typing import Any


VALID_CATEGORIES = {"model", "record", "system", "config"}
MAX_LIMIT = 100
DEFAULT_LIMIT = 20


class OdooUriError(ValueError):
    """Raised when an odoo:// URI is malformed."""


@dataclass
class OdooUri:
    """Parsed representation of an odoo:// URI."""

    category: str
    path_segments: list[str] = field(default_factory=list)
    query_params: dict[str, Any] = field(default_factory=dict)
    raw: str = ""

    @property
    def model_name(self) -> str | None:
        """Return the model name if applicable."""
        if self.category in ("model", "record") and self.path_segments:
            return self.path_segments[0]
        return None

    @property
    def record_id(self) -> int | None:
        """Return the record ID if this is a single-record URI."""
        if self.category == "record" and len(self.path_segments) >= 2:
            try:
                return int(self.path_segments[1])
            except (ValueError, IndexError):
                return None
        return None

    @property
    def resource_type(self) -> str | None:
        """Return the resource type (e.g. 'fields', 'methods', 'states')."""
        if self.category == "model" and len(self.path_segments) >= 2:
            return self.path_segments[1]
        if self.category == "system" and self.path_segments:
            return self.path_segments[0]
        if self.category == "config" and self.path_segments:
            return self.path_segments[0]
        return None

    @property
    def domain(self) -> list | None:
        """Return the parsed domain filter if present."""
        return self.query_params.get("domain")

    @property
    def limit(self) -> int:
        """Return the limit, enforcing max and default."""
        return self.query_params.get("limit", DEFAULT_LIMIT)


def parse_odoo_uri(uri: str) -> OdooUri:
    """Parse an odoo:// URI string into an OdooUri object.

    Supports:
      - odoo://system/info
      - odoo://system/modules
      - odoo://system/toolsets
      - odoo://config/safety
      - odoo://model/{model_name}/fields
      - odoo://model/{model_name}/methods
      - odoo://model/{model_name}/states
      - odoo://record/{model_name}/{record_id}
      - odoo://record/{model_name}?domain={json}&limit={int}
    """
    if not uri.startswith("odoo://"):
        raise OdooUriError(f"URI must start with 'odoo://', got: {uri!r}")

    # Strip scheme
    rest = uri[len("odoo://"):]

    # Split query string
    if "?" in rest:
        path_part, query_string = rest.split("?", 1)
    else:
        path_part = rest
        query_string = ""

    # Parse path segments
    segments = [s for s in path_part.split("/") if s]
    if not segments:
        raise OdooUriError(f"URI has no category: {uri!r}")

    category = segments[0]
    if category not in VALID_CATEGORIES:
        raise OdooUriError(
            f"Invalid category '{category}', must be one of: {VALID_CATEGORIES}"
        )

    path_segments = segments[1:]

    # Validate minimum path for each category
    if category == "system" and not path_segments:
        raise OdooUriError(f"system URI requires a resource type: {uri!r}")
    if category == "config" and not path_segments:
        raise OdooUriError(f"config URI requires a resource type: {uri!r}")
    if category == "model" and len(path_segments) < 2:
        raise OdooUriError(
            f"model URI requires model_name and resource type: {uri!r}"
        )
    if category == "record" and not path_segments:
        raise OdooUriError(f"record URI requires a model name: {uri!r}")

    # Parse query parameters
    query_params: dict[str, Any] = {}
    if query_string:
        parsed_qs = urllib.parse.parse_qs(query_string)
        if "domain" in parsed_qs:
            raw_domain = parsed_qs["domain"][0]
            try:
                query_params["domain"] = json.loads(raw_domain)
            except json.JSONDecodeError as exc:
                raise OdooUriError(
                    f"Invalid JSON in domain parameter: {exc}"
                ) from exc
        if "limit" in parsed_qs:
            try:
                limit = int(parsed_qs["limit"][0])
                limit = min(limit, MAX_LIMIT)
                limit = max(limit, 1)
                query_params["limit"] = limit
            except ValueError as exc:
                raise OdooUriError(
                    f"Invalid limit parameter: {exc}"
                ) from exc

    # Apply default limit for record listings
    if category == "record" and "limit" not in query_params:
        query_params["limit"] = DEFAULT_LIMIT

    return OdooUri(
        category=category,
        path_segments=path_segments,
        query_params=query_params,
        raw=uri,
    )
