"""Error handler - stub for Group 2.

Defines the error handling interfaces that Group 2 will implement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class OdooRpcError(Exception):
    """Exception raised when an Odoo RPC call fails."""

    def __init__(
        self,
        message: str,
        error_class: str = "",
        traceback: str = "",
        model: str = "",
        method: str = "",
    ) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.traceback = traceback
        self.model = model
        self.method = method


@dataclass
class ErrorResponse:
    """Structured error response."""

    category: str
    code: str
    message: str
    suggestion: str = ""


class ErrorHandler:
    """Classifies and translates Odoo errors (Group 2 implements)."""

    @staticmethod
    def classify(error: Exception) -> ErrorResponse:
        if isinstance(error, OdooRpcError):
            return ErrorResponse(
                category="odoo_rpc",
                code="rpc_error",
                message=str(error),
                suggestion="Check the Odoo server logs for more details.",
            )
        return ErrorResponse(
            category="unknown",
            code="unknown_error",
            message=str(error),
        )
