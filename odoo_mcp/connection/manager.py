"""Connection manager - stub for Group 1.

This file defines the ConnectionManager interface that Group 1 will implement.
Group 5 uses this to access the protocol, version, and UID.
"""

from __future__ import annotations

from typing import Any

from .protocol import OdooProtocol


class ConnectionManager:
    """Manages the Odoo connection lifecycle."""

    def __init__(self) -> None:
        self._protocol: OdooProtocol | None = None
        self._odoo_version: int = 17
        self._uid: int = 2
        self._url: str = ""
        self._database: str = ""

    @property
    def protocol(self) -> OdooProtocol:
        if self._protocol is None:
            raise RuntimeError("Not connected to Odoo")
        return self._protocol

    @property
    def odoo_version(self) -> int:
        return self._odoo_version

    @property
    def uid(self) -> int:
        return self._uid

    @property
    def url(self) -> str:
        return self._url

    @property
    def database(self) -> str:
        return self._database

    @property
    def is_ready(self) -> bool:
        return self._protocol is not None

    async def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> Any:
        return await self.protocol.execute_kw(model, method, args, kwargs, context)

    async def search_read(
        self,
        model: str,
        domain: list[Any],
        fields: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        return await self.protocol.search_read(
            model, domain, fields, limit, offset, order
        )
