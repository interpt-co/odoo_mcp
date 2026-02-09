"""Multi-probe version detection protocol.

REQ-02-10, REQ-02-11, REQ-02a-01 through REQ-02a-12.
"""

from __future__ import annotations

import asyncio
import logging
import re
import xmlrpc.client
from typing import Any

import httpx

from odoo_mcp.connection.protocol import OdooVersion

logger = logging.getLogger("odoo_mcp.connection.version")

# ---------------------------------------------------------------------------
# Version-to-protocol mapping (REQ-02a-07)
# ---------------------------------------------------------------------------

PROTOCOL_MAP: dict[int, str] = {
    14: "xmlrpc",
    15: "xmlrpc",
    16: "xmlrpc",
    17: "jsonrpc",
    18: "jsonrpc",
}
# 19+ -> json2


def recommended_protocol(version: OdooVersion) -> str:
    """Return the recommended protocol for a given Odoo version."""
    if version.major >= 19:
        return "json2"
    return PROTOCOL_MAP.get(version.major, "xmlrpc")


# ---------------------------------------------------------------------------
# Version parsing (REQ-02a-05)
# ---------------------------------------------------------------------------

def parse_version(version_info: list | tuple | str) -> OdooVersion:
    """Parse various Odoo version formats into OdooVersion."""
    if isinstance(version_info, (list, tuple)):
        return OdooVersion(
            major=int(version_info[0]),
            minor=int(version_info[1]) if len(version_info) > 1 else 0,
            micro=int(version_info[2]) if len(version_info) > 2 else 0,
            level=str(version_info[3]) if len(version_info) > 3 else "final",
            serial=int(version_info[4]) if len(version_info) > 4 else 0,
            full_string=".".join(str(x) for x in version_info[:3]),
        )

    if isinstance(version_info, str):
        raw = version_info
        # Normalize SaaS prefix
        cleaned = raw.replace("saas~", "saas-")
        is_saas = cleaned.startswith("saas-")
        is_enterprise = cleaned.rstrip().endswith("e")

        # Strip the "e" suffix
        cleaned = cleaned.rstrip("e")
        # Strip date suffix: "17.0-20240101" -> "17.0"
        if is_saas:
            cleaned = cleaned[5:]  # remove "saas-"
        else:
            cleaned = cleaned.split("-")[0]

        parts = cleaned.split(".")
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0

        edition = "enterprise" if is_enterprise else "community"
        level = "saas" if is_saas else "final"

        return OdooVersion(
            major=major,
            minor=minor,
            micro=0,
            level=level,
            serial=0,
            full_string=raw,
            edition=edition,
        )

    raise ValueError(f"Cannot parse version from: {version_info!r}")


# ---------------------------------------------------------------------------
# Probe 1: XML-RPC version() (REQ-02a-01, REQ-02a-02)
# ---------------------------------------------------------------------------

async def probe_xmlrpc_version(url: str, timeout: int = 10) -> dict | None:
    """Call /xmlrpc/2/common version() — available on all Odoo versions."""
    try:
        proxy = xmlrpc.client.ServerProxy(
            f"{url}/xmlrpc/2/common", allow_none=True
        )
        result = await asyncio.to_thread(proxy.version)
        return result
    except Exception as exc:
        logger.debug("XML-RPC version probe failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Probe 2: JSON-RPC session info (REQ-02a-03)
# ---------------------------------------------------------------------------

async def probe_jsonrpc_version(
    url: str,
    db: str,
    login: str,
    password: str,
    timeout: int = 10,
) -> dict | None:
    """Authenticate via /web/session/authenticate and extract version."""
    try:
        async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
            response = await client.post(
                f"{url}/web/session/authenticate",
                json={
                    "jsonrpc": "2.0",
                    "method": "call",
                    "params": {"db": db, "login": login, "password": password},
                },
            )
            data = response.json()
            if "result" in data:
                return {
                    "server_version": data["result"].get("server_version"),
                    "server_version_info": data["result"].get("server_version_info"),
                }
    except Exception as exc:
        logger.debug("JSON-RPC version probe failed: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Probe 3: HTTP header/page inspection (REQ-02a-04)
# ---------------------------------------------------------------------------

async def probe_http_version(url: str, timeout: int = 10) -> str | None:
    """Inspect HTTP response for version hints."""
    try:
        async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
            response = await client.get(f"{url}/web/login", follow_redirects=True)
            # Look for <meta name="generator" content="Odoo 17">
            match = re.search(r'content="Odoo\s+(\d+)"', response.text)
            if match:
                return match.group(1) + ".0"
            # Check asset URLs: /web/assets/17.0-...
            match = re.search(r"/web/assets/(\d+\.\d+)", response.text)
            if match:
                return match.group(1)
    except Exception as exc:
        logger.debug("HTTP version probe failed: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Edition detection (REQ-02a-06)
# ---------------------------------------------------------------------------

async def detect_edition(
    protocol: Any,
    session_info: dict | None = None,
) -> str:
    """Detect Community vs Enterprise edition."""
    # Method 1: session info (Odoo 16+)
    if session_info and session_info.get("is_enterprise"):
        return "enterprise"

    # Method 2: check if web_enterprise module is installed
    try:
        result = await protocol.search_read(
            "ir.module.module",
            [("name", "=", "web_enterprise"), ("state", "=", "installed")],
            fields=["name"],
        )
        if result:
            return "enterprise"
    except Exception:
        logger.debug("Edition detection via module probe failed")

    return "community"


# ---------------------------------------------------------------------------
# Main version detection orchestrator
# ---------------------------------------------------------------------------

async def detect_version(
    url: str,
    db: str = "",
    login: str = "",
    password: str = "",
    timeout: int = 10,
) -> OdooVersion:
    """Run all probes in order and return the best version info.

    REQ-02a-01: Probe 1 (XML-RPC) -> Probe 2 (JSON-RPC session) -> Probe 3 (HTTP).
    REQ-02a-09: If all probes fail, fall back to 14.0 with XML-RPC.
    """
    # Probe 1: XML-RPC
    result = await probe_xmlrpc_version(url, timeout=timeout)
    if result:
        version_info = result.get("server_version_info") or result.get(
            "server_version"
        )
        if version_info:
            version = parse_version(version_info)
            if not version.full_string:
                version.full_string = result.get("server_version", str(version))
            return version

    # Probe 2: JSON-RPC session authenticate
    if db and login and password:
        result = await probe_jsonrpc_version(url, db, login, password, timeout=timeout)
        if result:
            version_info = result.get("server_version_info") or result.get(
                "server_version"
            )
            if version_info:
                version = parse_version(version_info)
                if not version.full_string:
                    version.full_string = result.get("server_version", str(version))
                return version

    # Probe 3: HTTP page inspection
    version_str = await probe_http_version(url, timeout=timeout)
    if version_str:
        return parse_version(version_str)

    # All probes failed (REQ-02a-09)
    logger.warning(
        "Could not detect Odoo version. Falling back to XML-RPC with version assumption 14.0."
    )
    return OdooVersion(
        major=14, minor=0, micro=0, level="unknown", full_string="14.0 (assumed)"
    )
