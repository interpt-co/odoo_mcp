"""XML-RPC protocol adapter for Odoo 14-18.

REQ-01-04, REQ-01-06, REQ-02-04, REQ-02-05, REQ-02b-03, REQ-02b-04, REQ-02b-05.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import xmlrpc.client
from http.client import HTTPSConnection
from typing import Any

from odoo_mcp.connection.protocol import (
    AuthenticationError,
    BaseOdooProtocol,
    ConnectionError,
    OdooRpcError,
)

logger = logging.getLogger("odoo_mcp.connection.xmlrpc")


# ---------------------------------------------------------------------------
# Custom transport with configurable timeout/SSL (REQ-02b-05)
# ---------------------------------------------------------------------------

class SafeTransport(xmlrpc.client.SafeTransport):
    """SafeTransport with configurable timeout, SSL verification, and CA cert."""

    def __init__(
        self,
        timeout: int = 30,
        verify_ssl: bool = True,
        ca_cert: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._timeout = timeout
        self._verify_ssl = verify_ssl
        self._ca_cert = ca_cert
        self._ssl_context: ssl.SSLContext | None = None
        if not verify_ssl:
            self._ssl_context = ssl.create_default_context()
            self._ssl_context.check_hostname = False
            self._ssl_context.verify_mode = ssl.CERT_NONE
        elif ca_cert:
            self._ssl_context = ssl.create_default_context(cafile=ca_cert)

    def make_connection(self, host: Any) -> Any:
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        if self._ssl_context and hasattr(conn, "_context"):
            conn._context = self._ssl_context
        return conn


class UnsafeTransport(xmlrpc.client.Transport):
    """Plain HTTP transport with configurable timeout (for http:// URLs)."""

    def __init__(self, timeout: int = 30, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._timeout = timeout

    def make_connection(self, host: Any) -> Any:
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


# ---------------------------------------------------------------------------
# XML-RPC Adapter (REQ-02b-03)
# ---------------------------------------------------------------------------

class XmlRpcAdapter(BaseOdooProtocol):
    """XML-RPC protocol adapter for Odoo 14–18."""

    def __init__(
        self,
        url: str,
        timeout: int = 30,
        verify_ssl: bool = True,
        ca_cert: str | None = None,
    ) -> None:
        super().__init__()
        self._url = url.rstrip("/")
        self._timeout = timeout
        self._verify_ssl = verify_ssl
        self._ca_cert = ca_cert
        self._common: xmlrpc.client.ServerProxy | None = None
        self._object: xmlrpc.client.ServerProxy | None = None
        self._db: str | None = None
        self._uid: int | None = None
        self._password: str | None = None

    @property
    def protocol_name(self) -> str:
        return "xmlrpc"

    def _make_transport(self) -> xmlrpc.client.Transport:
        if self._url.startswith("https://"):
            return SafeTransport(
                timeout=self._timeout,
                verify_ssl=self._verify_ssl,
                ca_cert=self._ca_cert,
            )
        return UnsafeTransport(timeout=self._timeout)

    def _get_common(self) -> xmlrpc.client.ServerProxy:
        if self._common is None:
            self._common = xmlrpc.client.ServerProxy(
                f"{self._url}/xmlrpc/2/common",
                transport=self._make_transport(),
                allow_none=True,
            )
        return self._common

    def _get_object(self) -> xmlrpc.client.ServerProxy:
        if self._object is None:
            self._object = xmlrpc.client.ServerProxy(
                f"{self._url}/xmlrpc/2/object",
                transport=self._make_transport(),
                allow_none=True,
            )
        return self._object

    # --- OdooProtocol interface ---

    async def authenticate(self, db: str, login: str, password: str) -> int:
        """REQ-02-04, REQ-02-05: Authenticate via XML-RPC common endpoint."""
        try:
            uid = await asyncio.to_thread(
                self._get_common().authenticate, db, login, password, {}
            )
        except xmlrpc.client.Fault as e:
            raise AuthenticationError(
                f"Authentication failed: {e.faultString}",
                model="res.users",
                method="authenticate",
            )
        except (xmlrpc.client.ProtocolError, OSError) as e:
            raise ConnectionError(f"Connection error during authentication: {e}")

        if not uid:
            raise AuthenticationError(
                "Authentication failed: invalid credentials",
                model="res.users",
                method="authenticate",
            )

        self._db = db
        self._uid = uid
        self._password = password
        return uid

    async def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> Any:
        """REQ-02b-04: Execute via XML-RPC, wrapped in asyncio.to_thread."""
        if self._uid is None or self._db is None or self._password is None:
            raise ConnectionError("Not authenticated — call authenticate() first")

        merged_kwargs: dict[str, Any] = dict(kwargs or {})
        if context:
            merged_kwargs["context"] = {**self._base_context, **context}
        elif self._base_context:
            merged_kwargs["context"] = dict(self._base_context)

        try:
            result = await asyncio.to_thread(
                self._get_object().execute_kw,
                self._db,
                self._uid,
                self._password,
                model,
                method,
                list(args),
                merged_kwargs if merged_kwargs else {},
            )
            return result
        except xmlrpc.client.Fault as e:
            raise OdooRpcError.from_xmlrpc_fault(e, model=model, method=method)
        except xmlrpc.client.ProtocolError as e:
            raise ConnectionError(
                f"XML-RPC protocol error: {e.errcode} {e.errmsg}"
            )
        except OSError as e:
            raise ConnectionError(f"Network error: {e}")

    def _get_report(self) -> xmlrpc.client.ServerProxy:
        """Get or create the /xmlrpc/2/report proxy for PDF generation."""
        if not hasattr(self, "_report") or self._report is None:
            self._report = xmlrpc.client.ServerProxy(
                f"{self._url}/xmlrpc/2/report",
                transport=self._make_transport(),
                allow_none=True,
            )
        return self._report

    async def render_report(
        self,
        report_name: str,
        record_ids: list[int],
    ) -> dict[str, Any]:
        """Render a PDF report via the /xmlrpc/2/report endpoint.

        Returns dict with 'result' (base64 PDF) and 'format' keys.
        """
        if self._uid is None or self._db is None or self._password is None:
            raise ConnectionError("Not authenticated — call authenticate() first")

        try:
            result = await asyncio.to_thread(
                self._get_report().render_report,
                self._db,
                self._uid,
                self._password,
                report_name,
                record_ids,
            )
            return result
        except xmlrpc.client.Fault as e:
            raise OdooRpcError.from_xmlrpc_fault(
                e, model="ir.actions.report", method="render_report"
            )
        except xmlrpc.client.ProtocolError as e:
            raise ConnectionError(
                f"XML-RPC protocol error: {e.errcode} {e.errmsg}"
            )
        except OSError as e:
            raise ConnectionError(f"Network error: {e}")

    async def version_info(self) -> dict:
        """Get server version information via XML-RPC common endpoint."""
        try:
            result = await asyncio.to_thread(self._get_common().version)
            return result
        except Exception as e:
            raise ConnectionError(f"Failed to get version info: {e}")

    async def close(self) -> None:
        """REQ-02b-15: Release resources."""
        self._common = None
        self._object = None
        self._report = None
        self._uid = None

    def is_connected(self) -> bool:
        return self._uid is not None
