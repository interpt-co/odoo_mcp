"""JSON-RPC protocol adapter for Odoo 14-18 with session-based authentication.

REQ-02-08, REQ-02-09, REQ-02b-06, REQ-02b-07, REQ-02b-08.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from odoo_mcp.connection.protocol import (
    AccessDeniedError,
    AuthenticationError,
    BaseOdooProtocol,
    ConnectionError,
    OdooRpcError,
    SessionExpiredError,
)

logger = logging.getLogger("odoo_mcp.connection.jsonrpc")


class JsonRpcAdapter(BaseOdooProtocol):
    """JSON-RPC protocol adapter for Odoo 14–18 (REQ-02b-06)."""

    def __init__(
        self,
        url: str,
        timeout: int = 30,
        verify_ssl: bool = True,
        ca_cert: str | None = None,
    ) -> None:
        super().__init__()
        self._url = url.rstrip("/")
        self._session_id: str | None = None
        self._uid: int | None = None
        self._db: str | None = None
        self._request_id: int = 0
        self._user_info: dict[str, Any] = {}

        verify: bool | str = ca_cert if ca_cert else verify_ssl
        self._client = httpx.AsyncClient(
            base_url=self._url,
            timeout=timeout,
            verify=verify,
            headers={"Content-Type": "application/json"},
        )

    @property
    def protocol_name(self) -> str:
        return "jsonrpc"

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    # --- OdooProtocol interface ---

    async def authenticate(self, db: str, login: str, password: str) -> int:
        """REQ-02b-07: Session-based authentication via /web/session/authenticate."""
        self._db = db
        try:
            response = await self._client.post(
                "/web/session/authenticate",
                json={
                    "jsonrpc": "2.0",
                    "id": self._next_id(),
                    "method": "call",
                    "params": {
                        "db": db,
                        "login": login,
                        "password": password,
                    },
                },
            )
        except httpx.ConnectError as e:
            raise ConnectionError(f"Connection failed: {e}")
        except httpx.TimeoutException:
            raise ConnectionError("Authentication request timed out")

        data = response.json()

        if "error" in data:
            raise AuthenticationError(
                data["error"].get("message", "Authentication failed"),
                model="res.users",
                method="authenticate",
            )

        result = data.get("result", {})
        self._uid = result.get("uid")
        if not self._uid:
            raise AuthenticationError(
                "Authentication failed: no uid returned",
                model="res.users",
                method="authenticate",
            )

        # Store session cookie (REQ-02-09)
        self._session_id = response.cookies.get("session_id")
        if self._session_id:
            self._client.cookies.set("session_id", self._session_id)

        # Capture user info
        self._user_info = {
            "uid": self._uid,
            "name": result.get("name"),
            "username": result.get("username"),
            "is_admin": result.get("is_admin"),
            "server_version": result.get("server_version"),
            "server_version_info": result.get("server_version_info"),
        }

        return self._uid

    async def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> Any:
        """REQ-02b-08: Execute via /web/dataset/call_kw/{model}/{method}."""
        merged_kwargs: dict[str, Any] = dict(kwargs or {})
        if context:
            merged_kwargs["context"] = {**self._base_context, **context}
        elif self._base_context:
            merged_kwargs["context"] = dict(self._base_context)

        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "call",
            "params": {
                "model": model,
                "method": method,
                "args": list(args),
                "kwargs": merged_kwargs,
            },
        }

        try:
            endpoint = f"/web/dataset/call_kw/{model}/{method}"
            response = await self._client.post(endpoint, json=payload)

            # Session expiry detection (REQ-02-22)
            if response.status_code == 401:
                raise SessionExpiredError(
                    "Session expired", model=model, method=method
                )
            if response.status_code == 403:
                raise AccessDeniedError(
                    "Access denied", model=model, method=method
                )

            data = response.json()

            if "error" in data:
                error_data = data["error"]
                # JSON-RPC error code 100 -> session expired
                if error_data.get("code") == 100:
                    raise SessionExpiredError(
                        "Session expired", model=model, method=method
                    )
                raise OdooRpcError.from_jsonrpc_error(
                    error_data, model=model, method=method
                )

            return data.get("result")

        except (SessionExpiredError, AccessDeniedError, OdooRpcError):
            raise
        except httpx.TimeoutException:
            raise ConnectionError("Request timed out")
        except httpx.ConnectError as e:
            raise ConnectionError(f"Connection failed: {e}")

    async def version_info(self) -> dict:
        """Get server version from stored session info or direct call."""
        if self._user_info.get("server_version"):
            return {
                "server_version": self._user_info["server_version"],
                "server_version_info": self._user_info.get("server_version_info"),
            }
        # Fall back to calling version via JSON-RPC
        try:
            response = await self._client.post(
                "/web/webclient/version_info",
                json={
                    "jsonrpc": "2.0",
                    "id": self._next_id(),
                    "method": "call",
                    "params": {},
                },
            )
            data = response.json()
            return data.get("result", {})
        except Exception as e:
            raise ConnectionError(f"Failed to get version info: {e}")

    async def close(self) -> None:
        """REQ-02b-16: Close httpx client."""
        if self._client:
            await self._client.aclose()
            self._client = None  # type: ignore[assignment]
        self._session_id = None
        self._uid = None

    def is_connected(self) -> bool:
        return self._uid is not None and self._client is not None
