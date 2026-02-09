"""JSON-2 protocol adapter for Odoo 19+.

REQ-02-06, REQ-02b-09, REQ-02b-09a, REQ-02b-09b, REQ-02b-09c.
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
)

logger = logging.getLogger("odoo_mcp.connection.json2")


class Json2Adapter(BaseOdooProtocol):
    """JSON-2 protocol adapter for Odoo 19+ (REQ-02b-09)."""

    def __init__(
        self,
        url: str,
        api_key: str,
        timeout: int = 30,
        verify_ssl: bool = True,
        ca_cert: str | None = None,
    ) -> None:
        super().__init__()
        self._url = url.rstrip("/")
        self._api_key = api_key
        self._uid: int | None = None

        verify: bool | str = ca_cert if ca_cert else verify_ssl
        self._client = httpx.AsyncClient(
            base_url=self._url,
            timeout=timeout,
            verify=verify,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )

    @property
    def protocol_name(self) -> str:
        return "json2"

    # --- OdooProtocol interface ---

    async def authenticate(self, db: str, login: str, password: str) -> int:
        """REQ-02b-09a: Resolve uid by searching res.users with login."""
        try:
            result = await self.execute_kw(
                "res.users",
                "search_read",
                [[("login", "=", login)]],
                {"fields": ["id"], "limit": 1},
            )
        except OdooRpcError:
            raise AuthenticationError(
                "Authentication failed: could not search for user",
                model="res.users",
                method="search_read",
            )

        if not result:
            raise AuthenticationError(
                f"User not found: {login}",
                model="res.users",
                method="search_read",
            )

        self._uid = result[0]["id"]
        return self._uid

    async def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> Any:
        """REQ-02b-09b: Execute via /json/2/{model}/{method}."""
        merged_kwargs: dict[str, Any] = dict(kwargs or {})
        if context:
            merged_kwargs["context"] = {**self._base_context, **context}
        elif self._base_context:
            merged_kwargs["context"] = dict(self._base_context)

        # JSON-2 uses named parameters
        params: dict[str, Any] = {"args": list(args)}
        params.update(merged_kwargs)

        try:
            endpoint = f"/json/2/{model}/{method}"
            response = await self._client.post(endpoint, json=params)

            if response.status_code == 401:
                raise AuthenticationError(
                    "Invalid API key", model=model, method=method
                )
            if response.status_code == 403:
                raise AccessDeniedError(
                    "Access denied", model=model, method=method
                )
            if response.status_code == 404:
                raise OdooRpcError(
                    f"Model '{model}' or method '{method}' not found",
                    model=model,
                    method=method,
                )

            data = response.json()

            if "error" in data:
                raise OdooRpcError.from_json2_error(
                    data["error"], model=model, method=method
                )

            return data.get("result")

        except (AuthenticationError, AccessDeniedError, OdooRpcError):
            raise
        except httpx.TimeoutException:
            raise ConnectionError("Request timed out")
        except httpx.ConnectError as e:
            raise ConnectionError(f"Connection failed: {e}")

    async def version_info(self) -> dict:
        """Get server version via JSON-2 endpoint."""
        try:
            response = await self._client.get("/json/2/res.users/version")
            if response.status_code == 200:
                return response.json().get("result", {})
        except Exception:
            pass
        # Fallback: try the XML-RPC common endpoint (may still be available on 19)
        try:
            response = await self._client.post(
                "/web/webclient/version_info",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
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
        self._uid = None

    def is_connected(self) -> bool:
        return self._uid is not None and self._client is not None
