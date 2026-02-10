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
    Json2EndpointNotFoundError,
    OdooRpcError,
)

logger = logging.getLogger("odoo_mcp.connection.json2")

# ---------------------------------------------------------------------------
# JSON-2 parameter mapping
#
# The JSON-2 API (/json/2/<model>/<method>) passes JSON body keys as **kwargs
# to the model method.  Record IDs go in the URL path instead of args.
# This differs from execute_kw which uses positional args + kwargs.
# ---------------------------------------------------------------------------

# Positional arg name mapping for common methods.
# Maps method name -> tuple of parameter names for positional args.
_METHOD_ARG_NAMES: dict[str, tuple[str, ...]] = {
    "search": ("domain",),
    "search_read": ("domain",),
    "search_count": ("domain",),
    "search_fetch": ("domain", "field_names"),
    "read_group": ("domain", "fields", "groupby"),
    "create": ("vals_list",),
    "name_search": ("name",),
    "name_create": ("name",),
    "default_get": ("fields_list",),
    "onchange": ("values", "field_name", "field_onchange"),
}

# For recordset methods where IDs are extracted first, remaining arg names.
_RECORDSET_ARG_NAMES: dict[str, tuple[str, ...]] = {
    "write": ("vals",),
}


def _is_id_list(value: Any) -> bool:
    """Check if a value looks like a list of record IDs."""
    return (
        isinstance(value, (list, tuple))
        and len(value) > 0
        and all(isinstance(i, int) for i in value)
    )


def _is_recordset_method(method: str) -> bool:
    """Check if a method operates on specific records (IDs as first arg)."""
    return method.startswith(("action_", "button_", "message_")) or method in {
        "read", "write", "unlink", "copy", "name_get",
    }


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
        """REQ-02b-09b: Execute via /json/2/{model}/{method}.

        Translates the execute_kw calling convention (positional args + kwargs)
        into JSON-2's named-parameter convention with IDs in the URL path.
        """
        params: dict[str, Any] = dict(kwargs or {})
        if context:
            params["context"] = {**self._base_context, **context}
        elif self._base_context:
            params["context"] = dict(self._base_context)

        # Convert positional args to named parameters for JSON-2
        remaining_args = list(args)
        ids_for_url: list[int] | None = None

        if method in _METHOD_ARG_NAMES:
            # Known method with named positional params (search_read, create, etc.)
            for i, name in enumerate(_METHOD_ARG_NAMES[method]):
                if i < len(remaining_args):
                    params[name] = remaining_args[i]
        elif _is_recordset_method(method) and remaining_args and _is_id_list(remaining_args[0]):
            # Recordset method: first arg is IDs → put in URL
            ids_for_url = remaining_args.pop(0)
            # Map remaining positional args if known
            for i, name in enumerate(_RECORDSET_ARG_NAMES.get(method, ())):
                if i < len(remaining_args):
                    params[name] = remaining_args[i]
        elif remaining_args and _is_id_list(remaining_args[0]):
            # Unknown method with what looks like IDs — assume recordset
            ids_for_url = remaining_args.pop(0)
            logger.debug(
                "Unknown method %s.%s: assuming IDs %s in URL",
                model, method, ids_for_url,
            )

        # Build endpoint
        if ids_for_url:
            ids_str = ",".join(str(i) for i in ids_for_url)
            endpoint = f"/json/2/{model}/{ids_str}/{method}"
        else:
            endpoint = f"/json/2/{model}/{method}"

        try:
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
                raise Json2EndpointNotFoundError(
                    f"Model '{model}' or method '{method}' not found",
                    model=model,
                    method=method,
                )

            data = response.json()

            if isinstance(data, dict) and "error" in data:
                raise OdooRpcError.from_json2_error(
                    data["error"], model=model, method=method
                )

            # JSON-2 returns the result directly (no "result" wrapper for lists)
            if isinstance(data, (list, int, bool, float)):
                return data
            if isinstance(data, dict):
                result = data.get("result", data)
                # Detect Odoo error dicts returned inside "result" wrapper
                # (e.g. SaaS controllers may wrap exceptions this way)
                if (
                    isinstance(result, dict)
                    and "name" in result
                    and "message" in result
                    and result.get("name", "").endswith(
                        ("Error", "Warning", "Exception")
                    )
                ):
                    raise OdooRpcError(
                        message=result["message"],
                        error_class=result.get("name"),
                        traceback=result.get("debug"),
                        model=model,
                        method=method,
                    )
                return result
            return data

        except (AuthenticationError, AccessDeniedError, Json2EndpointNotFoundError, OdooRpcError):
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
