"""Connection lifecycle manager with health checks and reconnection.

REQ-02-18 through REQ-02-33.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any

import httpx

from odoo_mcp.config import OdooMcpConfig
from odoo_mcp.connection.json2_adapter import Json2Adapter
from odoo_mcp.connection.jsonrpc_adapter import JsonRpcAdapter
from odoo_mcp.connection.protocol import (
    AuthenticationError,
    BaseOdooProtocol,
    ConnectionError,
    ConnectionState,
    Json2EndpointNotFoundError,
    OdooRpcError,
    OdooVersion,
    SessionExpiredError,
)
from odoo_mcp.connection.version import (
    detect_edition,
    detect_version,
    recommended_protocol,
)
from odoo_mcp.connection.xmlrpc_adapter import XmlRpcAdapter

logger = logging.getLogger("odoo_mcp.connection.manager")


class ConnectionManager:
    """Manages the Odoo connection lifecycle (REQ-02-18, REQ-02-19)."""

    def __init__(self, config: OdooMcpConfig) -> None:
        self._config = config
        self._state = ConnectionState.DISCONNECTED
        self._protocol: BaseOdooProtocol | None = None
        self._odoo_version: OdooVersion | None = None
        self._uid: int | None = None
        self._username: str | None = None
        self._last_activity: float = 0.0
        self._installed_modules: list[str] = []
        # JSON-2 → XML-RPC fallback state
        self._xmlrpc_fallback: XmlRpcAdapter | None = None
        self._fallback_methods: set[tuple[str, str]] = set()
        # HTTP client for report PDF download
        self._report_http_client: httpx.AsyncClient | None = None
        self._owns_report_client: bool = False

    # --- Properties (REQ-02-19) ---

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def is_ready(self) -> bool:
        return self._state == ConnectionState.READY

    @property
    def odoo_version(self) -> OdooVersion | None:
        return self._odoo_version

    @property
    def protocol(self) -> BaseOdooProtocol | None:
        return self._protocol

    @property
    def uid(self) -> int | None:
        return self._uid

    @property
    def database(self) -> str:
        return self._config.odoo_db

    @property
    def server_url(self) -> str:
        return self._config.odoo_url

    # --- Connection establishment ---

    async def connect(self) -> None:
        """Full connection sequence: authenticate, detect version, select protocol.

        REQ-02-13, REQ-02-14, REQ-02-04 through REQ-02-09.
        """
        self._state = ConnectionState.CONNECTING
        url = self._config.odoo_url
        db = self._config.odoo_db
        timeout = self._config.odoo_timeout
        verify_ssl = self._config.odoo_verify_ssl
        ca_cert = self._config.odoo_ca_cert

        # Determine credentials — API key takes precedence (REQ-02-03)
        api_key = self._config.odoo_api_key
        username = self._config.odoo_username or ""
        password = api_key or self._config.odoo_password or ""

        try:
            # Step 1: Detect version first (REQ-02-10)
            self._odoo_version = await detect_version(
                url, db, username, password, timeout=timeout
            )
            logger.info(
                "Detected Odoo version: %s (edition: %s)",
                self._odoo_version,
                self._odoo_version.edition,
            )

            # Step 2: Select protocol (REQ-02-13, REQ-02-14)
            protocol_name = self._config.odoo_protocol
            if protocol_name == "auto":
                protocol_name = recommended_protocol(self._odoo_version)
                logger.info("Auto-selected protocol: %s", protocol_name)
            else:
                logger.info("Using configured protocol: %s", protocol_name)

            # Step 3: Create adapter
            adapter = self._create_adapter(
                protocol_name, url, timeout, verify_ssl, ca_cert, api_key
            )

            # Step 4: Set base context (REQ-02-27, REQ-02-28, REQ-02-29)
            base_ctx: dict[str, Any] = {
                "lang": self._config.odoo_lang,
                "tz": self._config.odoo_tz,
            }
            if self._config.odoo_company_id:
                base_ctx["allowed_company_ids"] = [self._config.odoo_company_id]
            elif self._config.odoo_company_ids:
                base_ctx["allowed_company_ids"] = list(self._config.odoo_company_ids)
            adapter.set_base_context(base_ctx)

            # Step 5: Authenticate (REQ-02-04 through REQ-02-09)
            uid = await self._authenticate_with_fallback(
                adapter, db, username, password, api_key
            )

            self._protocol = adapter
            self._uid = uid
            self._username = username
            self._state = ConnectionState.AUTHENTICATED

            # Step 6: Detect edition if not yet known
            if self._odoo_version.edition == "community":
                edition = await detect_edition(adapter)
                self._odoo_version.edition = edition

            self._state = ConnectionState.READY
            self._last_activity = time.monotonic()
            logger.info(
                "Connected to %s (db=%s, uid=%d, protocol=%s, version=%s %s)",
                url,
                db,
                uid,
                protocol_name,
                self._odoo_version,
                self._odoo_version.edition,
            )

        except (AuthenticationError, ConnectionError) as e:
            self._state = ConnectionState.ERROR
            logger.error("Connection failed: %s", e)
            raise
        except Exception as e:
            self._state = ConnectionState.ERROR
            logger.error("Unexpected error during connection: %s", e)
            raise ConnectionError(f"Connection failed: {e}")

    def _create_adapter(
        self,
        protocol_name: str,
        url: str,
        timeout: int,
        verify_ssl: bool,
        ca_cert: str | None,
        api_key: str | None,
    ) -> BaseOdooProtocol:
        """Create the appropriate protocol adapter."""
        if protocol_name == "xmlrpc":
            return XmlRpcAdapter(
                url=url, timeout=timeout, verify_ssl=verify_ssl, ca_cert=ca_cert
            )
        elif protocol_name == "jsonrpc":
            return JsonRpcAdapter(
                url=url, timeout=timeout, verify_ssl=verify_ssl, ca_cert=ca_cert
            )
        elif protocol_name == "json2":
            if not api_key:
                raise AuthenticationError(
                    "JSON-2 protocol requires an API key (odoo_api_key)",
                    model="res.users",
                    method="authenticate",
                )
            return Json2Adapter(
                url=url,
                api_key=api_key,
                timeout=timeout,
                verify_ssl=verify_ssl,
                ca_cert=ca_cert,
            )
        else:
            raise ValueError(f"Unknown protocol: {protocol_name}")

    async def _authenticate_with_fallback(
        self,
        adapter: BaseOdooProtocol,
        db: str,
        username: str,
        password: str,
        api_key: str | None,
    ) -> int:
        """Authenticate, falling back from api_key to password if needed (REQ-02-07)."""
        try:
            return await adapter.authenticate(db, username, password)
        except AuthenticationError:
            # If we used api_key and also have password, try password
            if (
                api_key
                and self._config.odoo_password
                and api_key == password
                and adapter.protocol_name != "json2"
            ):
                logger.warning(
                    "API key authentication failed, falling back to password"
                )
                return await adapter.authenticate(
                    db, username, self._config.odoo_password
                )
            raise

    # --- JSON-2 → XML-RPC fallback ---

    async def _get_or_create_xmlrpc_fallback(self) -> XmlRpcAdapter:
        """Lazily create and authenticate an XML-RPC adapter for fallback."""
        if self._xmlrpc_fallback is not None:
            return self._xmlrpc_fallback

        url = self._config.odoo_url
        db = self._config.odoo_db
        timeout = self._config.odoo_timeout
        verify_ssl = self._config.odoo_verify_ssl
        ca_cert = self._config.odoo_ca_cert
        username = self._config.odoo_username or ""
        password = self._config.odoo_api_key or self._config.odoo_password or ""

        adapter = XmlRpcAdapter(
            url=url, timeout=timeout, verify_ssl=verify_ssl, ca_cert=ca_cert
        )
        if self._protocol:
            adapter.set_base_context(dict(self._protocol._base_context))
        await adapter.authenticate(db, username, password)
        self._xmlrpc_fallback = adapter
        logger.info("Created XML-RPC fallback adapter for JSON-2 404s")
        return adapter

    # --- Health check (REQ-02-20) ---

    async def ensure_healthy(self) -> None:
        """Check connection health if inactive for too long."""
        if not self.is_ready or self._protocol is None:
            return

        elapsed = time.monotonic() - self._last_activity
        if elapsed < self._config.health_check_interval:
            return

        logger.debug("Running health check (%.0fs since last activity)", elapsed)
        try:
            result = await self._protocol.search_count(
                "res.users", [("id", "=", self._uid)]
            )
            if result != 1:
                raise ConnectionError("Health check failed: user not found")
            self._last_activity = time.monotonic()
        except Exception as e:
            logger.warning("Health check failed: %s", e)
            self._state = ConnectionState.ERROR
            await self._reconnect()

    # --- Automatic reconnection (REQ-02-21) ---

    async def _reconnect(self) -> None:
        """Attempt reconnection with exponential backoff."""
        self._state = ConnectionState.RECONNECTING
        max_attempts = self._config.reconnect_max_attempts
        base_delay = self._config.reconnect_backoff_base

        # Close report HTTP client if we own it
        if self._report_http_client and self._owns_report_client:
            try:
                await self._report_http_client.aclose()
            except Exception:
                pass
        self._report_http_client = None
        self._owns_report_client = False

        # Close fallback adapter (cache is kept — 404s are deterministic)
        if self._xmlrpc_fallback:
            try:
                await self._xmlrpc_fallback.close()
            except Exception:
                pass
            self._xmlrpc_fallback = None

        for attempt in range(1, max_attempts + 1):
            delay = base_delay * (2 ** (attempt - 1))
            logger.info(
                "Reconnection attempt %d/%d (delay: %ds)",
                attempt,
                max_attempts,
                delay,
            )
            await asyncio.sleep(delay)

            try:
                # Close existing connection
                if self._protocol:
                    try:
                        await self._protocol.close()
                    except Exception:
                        pass
                    self._protocol = None

                await self.connect()
                logger.info("Reconnection successful")
                return
            except Exception as e:
                logger.warning("Reconnection attempt %d failed: %s", attempt, e)

        self._state = ConnectionState.ERROR
        raise ConnectionError(
            f"Failed to reconnect after {max_attempts} attempts"
        )

    async def _execute_via_xmlrpc_fallback(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a call via the XML-RPC fallback adapter."""
        fallback = await self._get_or_create_xmlrpc_fallback()
        result = await fallback.execute_kw(model, method, args, kwargs, context)
        self._last_activity = time.monotonic()
        return result

    async def execute_with_retry(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> Any:
        """Execute an Odoo call with automatic health check and retry on failure."""
        await self.ensure_healthy()

        if not self._protocol:
            raise ConnectionError("Not connected")

        # If this model/method already known to need XML-RPC, skip JSON-2
        if (model, method) in self._fallback_methods:
            return await self._execute_via_xmlrpc_fallback(
                model, method, args, kwargs, context
            )

        try:
            result = await self._protocol.execute_kw(
                model, method, args, kwargs, context
            )
            self._last_activity = time.monotonic()
            return result
        except Json2EndpointNotFoundError:
            logger.warning(
                "JSON-2 returned 404 for %s/%s, falling back to XML-RPC",
                model, method,
            )
            self._fallback_methods.add((model, method))
            return await self._execute_via_xmlrpc_fallback(
                model, method, args, kwargs, context
            )
        except SessionExpiredError:
            logger.warning("Session expired, reconnecting...")
            await self._reconnect()
            if self._protocol:
                result = await self._protocol.execute_kw(
                    model, method, args, kwargs, context
                )
                self._last_activity = time.monotonic()
                return result
            raise ConnectionError("Not connected after reconnection")
        except ConnectionError:
            logger.warning("Connection error, attempting reconnection...")
            try:
                await self._reconnect()
                if self._protocol:
                    result = await self._protocol.execute_kw(
                        model, method, args, kwargs, context
                    )
                    self._last_activity = time.monotonic()
                    return result
            except ConnectionError:
                pass
            raise

    # --- Convenience methods (used by workflow toolsets) ---

    async def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> Any:
        """Convenience wrapper around execute_with_retry for toolset compatibility."""
        return await self.execute_with_retry(
            model, method, args or [], kwargs, context
        )

    async def search_read(
        self,
        model: str,
        domain: list[Any],
        fields: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        """Convenience wrapper delegating to the protocol's search_read."""
        if not self._protocol:
            raise ConnectionError("Not connected")
        await self.ensure_healthy()

        # If search_read already known to need XML-RPC for this model, skip JSON-2
        if (model, "search_read") in self._fallback_methods:
            fallback = await self._get_or_create_xmlrpc_fallback()
            result = await fallback.search_read(
                model, domain, fields=fields, limit=limit, offset=offset, order=order
            )
            self._last_activity = time.monotonic()
            return result

        try:
            result = await self._protocol.search_read(
                model, domain, fields=fields, limit=limit, offset=offset, order=order
            )
            self._last_activity = time.monotonic()
            return result
        except Json2EndpointNotFoundError:
            logger.warning(
                "JSON-2 returned 404 for %s/search_read, falling back to XML-RPC",
                model,
            )
            self._fallback_methods.add((model, "search_read"))
            fallback = await self._get_or_create_xmlrpc_fallback()
            result = await fallback.search_read(
                model, domain, fields=fields, limit=limit, offset=offset, order=order
            )
            self._last_activity = time.monotonic()
            return result

    # --- Report rendering (REQ-09-23) ---

    async def _get_report_http_client(self) -> httpx.AsyncClient:
        """Get an authenticated HTTP client for report PDF download.

        For Json2Adapter: creates a new client with Bearer auth only
            (avoids Content-Type: application/json which breaks http-type routes).
        For JsonRpcAdapter: reuses the adapter's session-authenticated client.
        For XmlRpcAdapter: creates and session-authenticates a new httpx client.
        """
        if self._report_http_client is not None:
            return self._report_http_client

        if not self._protocol:
            raise ConnectionError("Not connected")

        url = self._config.odoo_url
        timeout = self._config.odoo_timeout
        verify_ssl = self._config.odoo_verify_ssl
        ca_cert = self._config.odoo_ca_cert
        verify: bool | str = ca_cert if ca_cert else verify_ssl

        # For Json2Adapter: create a new client with Bearer auth but WITHOUT
        # Content-Type: application/json.  The report endpoint is type='http'
        # and Odoo routes requests with Content-Type application/json through
        # the JSON-RPC dispatcher, which rejects the http-type route.
        if isinstance(self._protocol, Json2Adapter):
            client = httpx.AsyncClient(
                base_url=url,
                timeout=timeout,
                verify=verify,
                headers={"Authorization": f"Bearer {self._config.odoo_api_key}"},
            )
            self._report_http_client = client
            self._owns_report_client = True
            return self._report_http_client

        # For JsonRpcAdapter: create a new client with the session cookie
        # but WITHOUT Content-Type: application/json.  Like Json2Adapter,
        # the JsonRpcAdapter sets Content-Type as a default header, and Odoo
        # routes requests with that Content-Type through the JSON-RPC
        # dispatcher — which rejects the http-type /report/pdf/ route.
        if isinstance(self._protocol, JsonRpcAdapter):
            session_id = self._protocol._client.cookies.get("session_id")
            if session_id:
                client = httpx.AsyncClient(
                    base_url=url,
                    timeout=timeout,
                    verify=verify,
                )
                client.cookies.set("session_id", session_id)
                self._report_http_client = client
                self._owns_report_client = True
                return self._report_http_client
            # No session cookie; fall through to session-auth client creation

        # For XmlRpcAdapter: create a session-authenticated httpx client
        client = await self._create_session_http_client()
        self._report_http_client = client
        self._owns_report_client = True
        return self._report_http_client

    async def _create_session_http_client(self) -> httpx.AsyncClient:
        """Create a new httpx client authenticated via /web/session/authenticate."""
        url = self._config.odoo_url
        timeout = self._config.odoo_timeout
        ca_cert = self._config.odoo_ca_cert
        verify: bool | str = ca_cert if ca_cert else self._config.odoo_verify_ssl

        client = httpx.AsyncClient(
            base_url=url,
            timeout=timeout,
            verify=verify,
        )

        db = self._config.odoo_db
        username = self._config.odoo_username or ""
        password = self._config.odoo_api_key or self._config.odoo_password or ""

        try:
            response = await client.post(
                "/web/session/authenticate",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "call",
                    "params": {
                        "db": db,
                        "login": username,
                        "password": password,
                    },
                },
            )
            data = response.json()
            result = data.get("result", {})
            if not result.get("uid"):
                raise ConnectionError(
                    "Report HTTP client: session authentication failed"
                )
            session_id = response.cookies.get("session_id")
            if session_id:
                client.cookies.set("session_id", session_id)
        except ConnectionError:
            await client.aclose()
            raise
        except Exception as e:
            await client.aclose()
            raise ConnectionError(
                f"Report HTTP client: authentication failed: {e}"
            )

        return client

    async def _get_session_http_client(self) -> httpx.AsyncClient:
        """Create a fresh session-authenticated HTTP client (fallback).

        Used as fallback when the primary report HTTP client doesn't work
        (e.g. Bearer auth rejected, session expired, Content-Type conflict).
        Always creates a new session to ensure a clean authentication state.
        Replaces the existing report client.
        """
        # Close existing client if we own it
        if self._report_http_client and self._owns_report_client:
            try:
                await self._report_http_client.aclose()
            except Exception:
                pass
            self._report_http_client = None

        client = await self._create_session_http_client()
        self._report_http_client = client
        self._owns_report_client = True
        return client

    async def render_report(
        self,
        report_name: str,
        record_ids: list[int],
    ) -> dict[str, Any]:
        """Render a PDF report via the HTTP /report/pdf/ web controller.

        This endpoint works across all Odoo versions (14-19+), unlike
        /xmlrpc/2/report which was removed in Odoo 15.

        Falls back to XML-RPC render_report for truly old instances.
        """
        await self.ensure_healthy()

        # Try HTTP /report/pdf/ endpoint first (works on all versions)
        ids_str = ",".join(str(i) for i in record_ids)
        report_url = f"/report/pdf/{report_name}/{ids_str}"

        try:
            client = await self._get_report_http_client()
            response = await client.get(report_url)

            if (
                response.status_code == 200
                and "pdf" in response.headers.get("content-type", "").lower()
            ):
                pdf_b64 = base64.b64encode(response.content).decode("ascii")
                self._last_activity = time.monotonic()
                return {"result": pdf_b64, "format": "pdf"}

            logger.warning(
                "HTTP report download returned status %d (content-type: %s), "
                "falling back to XML-RPC",
                response.status_code,
                response.headers.get("content-type", "unknown"),
            )
        except ConnectionError:
            raise
        except Exception as e:
            logger.warning(
                "HTTP report download failed: %s, falling back to XML-RPC", e
            )

        # Fallback: XML-RPC /xmlrpc/2/report (only works on Odoo 14;
        # the 'report' service was removed in Odoo 15+).
        if self._odoo_version and self._odoo_version.major <= 14:
            if self._protocol and isinstance(self._protocol, XmlRpcAdapter):
                result = await self._protocol.render_report(report_name, record_ids)
                self._last_activity = time.monotonic()
                return result

            fallback = await self._get_or_create_xmlrpc_fallback()
            result = await fallback.render_report(report_name, record_ids)
            self._last_activity = time.monotonic()
            return result

        # Fallback for Odoo 15+: try session-authenticated HTTP client.
        # This handles the case where Bearer auth isn't available (e.g. no API key).
        last_error = ""
        try:
            client = await self._get_session_http_client()
            response = await client.get(report_url)

            if (
                response.status_code == 200
                and "pdf" in response.headers.get("content-type", "").lower()
            ):
                pdf_b64 = base64.b64encode(response.content).decode("ascii")
                self._last_activity = time.monotonic()
                return {"result": pdf_b64, "format": "pdf"}

            last_error = (
                f"status {response.status_code} "
                f"(content-type: {response.headers.get('content-type', 'unknown')})"
            )
        except Exception as e:
            last_error = str(e)
            logger.warning("Session-auth report fallback also failed: %s", e)

        raise ConnectionError(
            f"Report generation failed for '{report_name}': {last_error}. "
            f"Ensure the report exists and you have access."
        )

    # --- Connection info (REQ-02-33) ---

    def get_connection_info(self) -> dict:
        """Return connection metadata for resources."""
        return {
            "url": self.server_url,
            "database": self.database,
            "uid": self._uid,
            "username": self._username,
            "odoo_version": str(self._odoo_version) if self._odoo_version else None,
            "protocol": self._protocol.protocol_name if self._protocol else None,
            "edition": self._odoo_version.edition if self._odoo_version else None,
            "state": self._state.value,
            "installed_modules": self._installed_modules,
        }

    # --- Shutdown ---

    async def disconnect(self) -> None:
        """Close the connection cleanly."""
        # Close report HTTP client if we created it (not when reusing adapter client)
        if self._report_http_client and self._owns_report_client:
            try:
                await self._report_http_client.aclose()
            except Exception:
                pass
        self._report_http_client = None
        self._owns_report_client = False
        if self._xmlrpc_fallback:
            try:
                await self._xmlrpc_fallback.close()
            except Exception:
                pass
            self._xmlrpc_fallback = None
        self._fallback_methods.clear()
        if self._protocol:
            try:
                await self._protocol.close()
            except Exception:
                pass
            self._protocol = None
        self._uid = None
        self._state = ConnectionState.DISCONNECTED
        logger.info("Disconnected from Odoo")
