"""
Error handling module for the Odoo MCP server.

Provides error classification, pattern matching, and LLM-friendly error responses.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ErrorCategory(str, Enum):
    """Error classification categories (REQ-10-01)."""

    VALIDATION = "validation"
    ACCESS = "access"
    NOT_FOUND = "not_found"
    CONSTRAINT = "constraint"
    STATE = "state"
    WIZARD = "wizard"
    CONNECTION = "connection"
    RATE_LIMIT = "rate_limit"
    CONFIGURATION = "configuration"
    UNKNOWN = "unknown"


class ErrorCode:
    """Machine-readable error codes (REQ-10-01)."""

    # Validation
    VALIDATION_ERROR = "VALIDATION_ERROR"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_FIELD = "INVALID_FIELD"
    WRONG_VALUE = "WRONG_VALUE"
    SINGLETON_EXPECTED = "SINGLETON_EXPECTED"
    INVALID_SELECTION = "INVALID_SELECTION"
    TYPE_MISMATCH = "TYPE_MISMATCH"
    INVALID_INTEGER = "INVALID_INTEGER"
    USER_ERROR = "USER_ERROR"
    VALUE_ERROR = "VALUE_ERROR"
    REDIRECT_WARNING = "REDIRECT_WARNING"
    MISSING_ACCOUNTING_CONFIG = "MISSING_ACCOUNTING_CONFIG"
    INSUFFICIENT_STOCK = "INSUFFICIENT_STOCK"
    MISSING_LINES = "MISSING_LINES"

    # Access
    ACCESS_DENIED = "ACCESS_DENIED"
    OPERATION_NOT_ALLOWED = "OPERATION_NOT_ALLOWED"
    RECORD_RULE_VIOLATION = "RECORD_RULE_VIOLATION"
    MODEL_ACCESS_DENIED = "MODEL_ACCESS_DENIED"
    SESSION_EXPIRED = "SESSION_EXPIRED"

    # Not found
    NOT_FOUND = "NOT_FOUND"
    RECORD_NOT_FOUND = "RECORD_NOT_FOUND"
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"

    # Constraint
    CONSTRAINT_ERROR = "CONSTRAINT_ERROR"
    UNIQUE_VIOLATION = "UNIQUE_VIOLATION"
    CHECK_CONSTRAINT = "CHECK_CONSTRAINT"
    FK_VIOLATION = "FK_VIOLATION"

    # State
    STATE_ERROR = "STATE_ERROR"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    DRAFT_REQUIRED = "DRAFT_REQUIRED"
    ALREADY_PROCESSED = "ALREADY_PROCESSED"
    ALREADY_RECONCILED = "ALREADY_RECONCILED"
    CANNOT_DELETE_PROCESSED = "CANNOT_DELETE_PROCESSED"

    # Wizard
    WIZARD_REQUIRED = "WIZARD_REQUIRED"

    # Connection
    CONNECTION_ERROR = "CONNECTION_ERROR"
    CONNECTION_REFUSED = "CONNECTION_REFUSED"
    TIMEOUT = "TIMEOUT"
    ENDPOINT_NOT_FOUND = "ENDPOINT_NOT_FOUND"
    SERVER_ERROR = "SERVER_ERROR"

    # Rate limit
    RATE_LIMITED = "RATE_LIMITED"

    # Configuration
    CONFIG_ERROR = "CONFIG_ERROR"

    # Unknown
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


# Retry guidance mapping (REQ-10-15)
RETRY_GUIDANCE: dict[str, bool] = {
    ErrorCategory.VALIDATION: True,
    ErrorCategory.ACCESS: False,
    ErrorCategory.NOT_FOUND: True,
    ErrorCategory.CONSTRAINT: True,
    ErrorCategory.STATE: True,
    ErrorCategory.WIZARD: True,
    ErrorCategory.CONNECTION: True,
    ErrorCategory.RATE_LIMIT: True,
    ErrorCategory.CONFIGURATION: False,
    ErrorCategory.UNKNOWN: False,
}


class McpErrorCode:
    """Standard MCP JSON-RPC error codes (REQ-10-16)."""

    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603


@dataclass
class ErrorResponse:
    """Structured, LLM-friendly error response (REQ-10-02 through REQ-10-04).

    Required: error, category, code, message, suggestion, retry.
    Optional: details, original_error.
    """

    category: str
    code: str
    message: str
    suggestion: str
    retry: bool
    error: bool = True
    details: dict[str, Any] | None = None
    original_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary, omitting None optional fields."""
        result: dict[str, Any] = {
            "error": self.error,
            "category": self.category,
            "code": self.code,
            "message": self.message,
            "suggestion": self.suggestion,
            "retry": self.retry,
        }
        if self.details is not None:
            result["details"] = self.details
        if self.original_error is not None:
            result["original_error"] = self.original_error
        return result

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict())


def get_retry_for_category(category: str) -> bool:
    """Return whether the given error category is retryable (REQ-10-15)."""
    return RETRY_GUIDANCE.get(category, False)


def make_tool_error_result(error_response: ErrorResponse) -> dict[str, Any]:
    """Create an MCP tool result with isError: true (REQ-10-17).

    Returns a dict matching the CallToolResult structure.
    """
    return {
        "content": [{"type": "text", "text": error_response.to_json()}],
        "isError": True,
    }


class ModeViolationError(Exception):
    """Raised when an operation is blocked by the current safety mode."""


class RateLimitError(Exception):
    """Raised when rate limit is exceeded."""

    def __init__(self, message: str, retry_after: float):
        super().__init__(message)
        self.retry_after = retry_after


class FieldBlockedError(Exception):
    """Raised when a blocked field is used in a write operation."""


class MethodBlockedError(Exception):
    """Raised when a blocked method is called."""


class ModelAccessError(Exception):
    """Raised when access to a model is denied by safety config."""
