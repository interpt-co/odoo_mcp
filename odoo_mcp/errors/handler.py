"""
Error classification handler for the Odoo MCP server.

Translates raw Odoo errors (XML-RPC faults, JSON-RPC errors, HTTP errors)
into structured, LLM-friendly ErrorResponse objects.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from odoo_mcp.errors import (
    ErrorCategory,
    ErrorCode,
    ErrorResponse,
    RETRY_GUIDANCE,
    get_retry_for_category,
)
from odoo_mcp.errors.patterns import ERROR_PATTERNS

logger = logging.getLogger(__name__)

# JSON-RPC / JSON-2 data.name → (category, code) mapping (REQ-10-07)
JSONRPC_CLASS_MAP: dict[str, tuple[str, str]] = {
    "odoo.exceptions.ValidationError": (ErrorCategory.VALIDATION, ErrorCode.VALIDATION_ERROR),
    "odoo.exceptions.UserError": (ErrorCategory.VALIDATION, ErrorCode.USER_ERROR),
    "odoo.exceptions.AccessError": (ErrorCategory.ACCESS, ErrorCode.ACCESS_DENIED),
    "odoo.exceptions.MissingError": (ErrorCategory.NOT_FOUND, ErrorCode.NOT_FOUND),
    "odoo.exceptions.AccessDenied": (ErrorCategory.ACCESS, ErrorCode.ACCESS_DENIED),
    "odoo.exceptions.RedirectWarning": (ErrorCategory.VALIDATION, ErrorCode.REDIRECT_WARNING),
    "builtins.ValueError": (ErrorCategory.VALIDATION, ErrorCode.VALUE_ERROR),
    "psycopg2.errors.UniqueViolation": (ErrorCategory.CONSTRAINT, ErrorCode.UNIQUE_VIOLATION),
    "psycopg2.errors.CheckViolation": (ErrorCategory.CONSTRAINT, ErrorCode.CHECK_CONSTRAINT),
    "psycopg2.errors.ForeignKeyViolation": (ErrorCategory.CONSTRAINT, ErrorCode.FK_VIOLATION),
}

# XML-RPC faultString keyword → (category, code) mapping (REQ-10-05)
XMLRPC_FAULT_MAP: list[tuple[str, str, str]] = [
    ("ValidationError", ErrorCategory.VALIDATION, ErrorCode.VALIDATION_ERROR),
    ("MissingError", ErrorCategory.NOT_FOUND, ErrorCode.NOT_FOUND),
    ("UserError", ErrorCategory.VALIDATION, ErrorCode.USER_ERROR),
    ("AccessError", ErrorCategory.ACCESS, ErrorCode.ACCESS_DENIED),
    ("AccessDenied", ErrorCategory.ACCESS, ErrorCode.ACCESS_DENIED),
    ("unique", ErrorCategory.CONSTRAINT, ErrorCode.UNIQUE_VIOLATION),
    ("duplicate", ErrorCategory.CONSTRAINT, ErrorCode.UNIQUE_VIOLATION),
    ("check constraint", ErrorCategory.CONSTRAINT, ErrorCode.CHECK_CONSTRAINT),
    ("foreign key", ErrorCategory.CONSTRAINT, ErrorCode.FK_VIOLATION),
    ("ir.actions", ErrorCategory.WIZARD, ErrorCode.WIZARD_REQUIRED),
]


def _sanitize_args(args: Any) -> Any:
    """Sanitize arguments for logging — strip passwords and long values."""
    if isinstance(args, dict):
        return {
            k: "***" if "password" in k.lower() or "secret" in k.lower() or "key" in k.lower()
            else (f"<{len(v)} chars>" if isinstance(v, str) and len(v) > 200 else v)
            for k, v in args.items()
        }
    if isinstance(args, (list, tuple)):
        return [_sanitize_args(a) for a in args]
    return args


def _extract_traceback_exception(traceback_text: str) -> tuple[str, str]:
    """Extract exception class and message from a Python traceback (REQ-10-13).

    Returns (error_class, error_message).
    """
    if not traceback_text:
        return "", ""

    lines = traceback_text.strip().splitlines()

    # The last line typically contains the exception
    last_line = lines[-1].strip() if lines else ""

    # Try to extract "ExceptionClass: message" pattern
    match = re.match(r"^([\w.]+(?:Error|Exception|Warning|Denied|Violation)?)\s*:\s*(.+)$", last_line)
    if match:
        return match.group(1), match.group(2).strip()

    # Try just class name
    match = re.match(r"^([\w.]+(?:Error|Exception|Warning|Denied|Violation)?)$", last_line)
    if match:
        return match.group(1), ""

    return "", last_line


class ErrorHandler:
    """Main error classifier (REQ-10a-02).

    Translates raw Odoo errors into structured ErrorResponse objects using
    the pattern database and classification rules.
    """

    def classify(
        self,
        error_message: str,
        error_class: str | None = None,
        model: str | None = None,
        method: str | None = None,
    ) -> ErrorResponse:
        """Classify an Odoo error using the pattern database (REQ-10a-02).

        Matching order:
        1. Match by error_class first (narrowest).
        2. Then match by pattern regex against message.
        3. First matching pattern wins.
        4. Fallback classification if no pattern matches.
        """
        for pattern in ERROR_PATTERNS:
            # Check error_class match (if specified in pattern)
            if pattern.error_class and error_class:
                if pattern.error_class not in error_class:
                    continue
            elif pattern.error_class and not error_class:
                # Pattern requires a specific error_class but none was provided;
                # still try regex matching
                pass

            # Check regex match
            match = re.search(pattern.pattern, error_message, re.IGNORECASE)
            if match:
                groups: dict[str, str] = {}
                for name, group_ref in pattern.extract_groups.items():
                    group_num = int(group_ref.replace("group", ""))
                    try:
                        value = match.group(group_num) or ""
                    except IndexError:
                        value = ""
                    # If primary group is empty, try subsequent groups
                    # (handles regex alternations where different groups capture)
                    if not value and match.lastindex:
                        for i in range(group_num + 1, match.lastindex + 1):
                            try:
                                alt = match.group(i)
                                if alt:
                                    value = alt
                                    break
                            except IndexError:
                                pass
                    groups[name] = value

                # Add context
                groups["model"] = model or groups.get("model", "unknown")
                groups["method"] = method or ""
                groups.setdefault("url", "")

                try:
                    message = pattern.message_template.format(**groups)
                except KeyError:
                    message = pattern.message_template
                try:
                    suggestion = pattern.suggestion_template.format(**groups)
                except KeyError:
                    suggestion = pattern.suggestion_template

                retry = get_retry_for_category(pattern.category)
                response = ErrorResponse(
                    category=pattern.category,
                    code=pattern.code,
                    message=message,
                    suggestion=suggestion,
                    retry=retry,
                    original_error=error_message,
                    details=groups,
                )
                self._log_error(response, model, method)
                return response

        # Fallback: no pattern matched
        response = ErrorResponse(
            category=ErrorCategory.UNKNOWN,
            code=ErrorCode.UNKNOWN_ERROR,
            message=f"Odoo error: {error_message[:200]}",
            suggestion="An unexpected error occurred. Check the error details and try a different approach.",
            retry=False,
            original_error=error_message,
        )
        self._log_error(response, model, method)
        return response

    def classify_xmlrpc_fault(
        self,
        fault_code: int | str,
        fault_string: str,
        model: str | None = None,
        method: str | None = None,
    ) -> ErrorResponse:
        """Classify an XML-RPC Fault (REQ-10-05).

        Parses faultCode and faultString to determine the error category.
        """
        fault_code_str = str(fault_code)

        # Check faultCode for Access Denied
        if "Access Denied" in fault_code_str or "Access Denied" in fault_string:
            return ErrorResponse(
                category=ErrorCategory.ACCESS,
                code=ErrorCode.ACCESS_DENIED,
                message="Access denied. Authentication credentials are invalid or expired.",
                suggestion="Check the username and password/API key. The session may have expired.",
                retry=False,
                original_error=fault_string,
            )

        # Extract exception info from faultString (REQ-10-06)
        error_class, error_msg = self._extract_from_fault_string(fault_string)

        # Try pattern-based classification first
        response = self.classify(
            error_message=error_msg or fault_string,
            error_class=error_class or None,
            model=model,
            method=method,
        )

        # If pattern matching fell through, try keyword mapping
        if response.code == ErrorCode.UNKNOWN_ERROR:
            for keyword, category, code in XMLRPC_FAULT_MAP:
                if keyword in fault_string:
                    response = ErrorResponse(
                        category=category,
                        code=code,
                        message=f"Odoo error: {error_msg or fault_string[:200]}",
                        suggestion=self._get_fallback_suggestion(category, model),
                        retry=get_retry_for_category(category),
                        original_error=fault_string,
                    )
                    self._log_error(response, model, method)
                    break

        return response

    def classify_jsonrpc_error(
        self,
        error_data: dict[str, Any],
        model: str | None = None,
        method: str | None = None,
    ) -> ErrorResponse:
        """Classify a JSON-RPC/JSON-2 error response (REQ-10-07).

        Expects the 'data' dict from a JSON-RPC error response containing:
        - name: exception class (e.g., "odoo.exceptions.ValidationError")
        - message: error message
        - debug: full traceback (optional)
        """
        data_name = error_data.get("name", "")
        data_message = error_data.get("message", "")
        data_debug = error_data.get("debug", "")

        # Extract final exception from debug traceback if available
        if data_debug:
            tb_class, tb_msg = _extract_traceback_exception(data_debug)
            if not data_name and tb_class:
                data_name = tb_class
            if not data_message and tb_msg:
                data_message = tb_msg

        # Try direct class mapping
        if data_name in JSONRPC_CLASS_MAP:
            category, code = JSONRPC_CLASS_MAP[data_name]
            # Still try pattern DB for better messages
            response = self.classify(
                error_message=data_message,
                error_class=data_name,
                model=model,
                method=method,
            )
            # If pattern DB didn't improve, use the class-based mapping
            if response.code == ErrorCode.UNKNOWN_ERROR:
                response = ErrorResponse(
                    category=category,
                    code=code,
                    message=data_message[:200] if data_message else f"Odoo {data_name}",
                    suggestion=self._get_fallback_suggestion(category, model),
                    retry=get_retry_for_category(category),
                    original_error=data_debug or data_message,
                )
                self._log_error(response, model, method)
            return response

        # Fall through to general classify
        return self.classify(
            error_message=data_message,
            error_class=data_name or None,
            model=model,
            method=method,
        )

    def classify_http_error(
        self,
        status_code: int | None = None,
        error_type: str | None = None,
        error_message: str = "",
        model: str | None = None,
        method: str | None = None,
    ) -> ErrorResponse:
        """Classify an HTTP/network error (REQ-10-08).

        Args:
            status_code: HTTP status code (if available).
            error_type: Exception class name (e.g., "httpx.ConnectError").
            error_message: Error description.
        """
        # httpx exception types
        if error_type:
            if "ConnectError" in error_type:
                return self._make_http_response(
                    ErrorCategory.CONNECTION, ErrorCode.CONNECTION_REFUSED,
                    "Cannot connect to Odoo server",
                    "The Odoo server is not responding. Check that the server is running and the URL is correct.",
                    error_message,
                )
            if "TimeoutException" in error_type or "Timeout" in error_type:
                return self._make_http_response(
                    ErrorCategory.CONNECTION, ErrorCode.TIMEOUT,
                    "Request timed out",
                    "The Odoo server took too long to respond. Wait and retry with a simpler query.",
                    error_message,
                )

        # HTTP status codes
        if status_code:
            if status_code in (401, 403):
                return self._make_http_response(
                    ErrorCategory.ACCESS, ErrorCode.SESSION_EXPIRED,
                    "Session expired or invalid credentials",
                    "The session may have expired. Re-authentication should happen automatically.",
                    error_message,
                )
            if status_code == 404:
                return self._make_http_response(
                    ErrorCategory.CONNECTION, ErrorCode.ENDPOINT_NOT_FOUND,
                    "API endpoint not found",
                    "The Odoo API endpoint was not found. Check the server URL and protocol.",
                    error_message,
                )
            if status_code == 429:
                return self._make_http_response(
                    ErrorCategory.RATE_LIMIT, ErrorCode.RATE_LIMITED,
                    "Rate limit exceeded",
                    "Too many requests. Wait before retrying.",
                    error_message,
                    retry_after=60,
                )
            if status_code >= 500:
                return self._make_http_response(
                    ErrorCategory.CONNECTION, ErrorCode.SERVER_ERROR,
                    f"Server error (HTTP {status_code})",
                    "The Odoo server returned an internal error. The issue may be temporary.",
                    error_message,
                )

        # Fallback to general classify
        return self.classify(error_message=error_message, model=model, method=method)

    def classify_exception(
        self,
        exc: Exception,
        model: str | None = None,
        method: str | None = None,
    ) -> ErrorResponse:
        """Classify a Python exception into an ErrorResponse.

        Handles xmlrpc.client.Fault, HTTP errors, and generic exceptions.
        """
        exc_class = f"{type(exc).__module__}.{type(exc).__qualname__}"
        exc_message = str(exc)

        # xmlrpc.client.Fault
        if hasattr(exc, "faultCode") and hasattr(exc, "faultString"):
            return self.classify_xmlrpc_fault(
                fault_code=exc.faultCode,  # type: ignore[attr-defined]
                fault_string=exc.faultString,  # type: ignore[attr-defined]
                model=model,
                method=method,
            )

        # HTTP errors (httpx-style)
        if hasattr(exc, "response") and hasattr(exc.response, "status_code"):  # type: ignore[union-attr]
            return self.classify_http_error(
                status_code=exc.response.status_code,  # type: ignore[union-attr]
                error_type=exc_class,
                error_message=exc_message,
                model=model,
                method=method,
            )

        # Network errors without response
        if "ConnectError" in exc_class or "TimeoutException" in exc_class:
            return self.classify_http_error(
                error_type=exc_class,
                error_message=exc_message,
                model=model,
                method=method,
            )

        # General classification
        return self.classify(
            error_message=exc_message,
            error_class=exc_class,
            model=model,
            method=method,
        )

    def _extract_from_fault_string(self, fault_string: str) -> tuple[str, str]:
        """Extract exception class and message from an XML-RPC faultString (REQ-10-06).

        Returns (error_class, error_message).
        """
        if not fault_string:
            return "", ""

        # Check if it contains a traceback
        if "Traceback" in fault_string:
            return _extract_traceback_exception(fault_string)

        # Try "ClassName: message" format
        match = re.match(r"^([\w.]+(?:Error|Exception|Warning|Denied|Violation)?)\s*:\s*(.+)", fault_string, re.DOTALL)
        if match:
            return match.group(1).strip(), match.group(2).strip()

        return "", fault_string

    def _make_http_response(
        self,
        category: str,
        code: str,
        message: str,
        suggestion: str,
        original_error: str,
        retry_after: int | None = None,
    ) -> ErrorResponse:
        """Create an ErrorResponse for HTTP errors."""
        details: dict[str, Any] | None = None
        if retry_after is not None:
            details = {"retry_after": retry_after}

        response = ErrorResponse(
            category=category,
            code=code,
            message=message,
            suggestion=suggestion,
            retry=get_retry_for_category(category),
            original_error=original_error,
            details=details,
        )
        self._log_error(response, None, None)
        return response

    def _get_fallback_suggestion(self, category: str, model: str | None) -> str:
        """Generate a fallback suggestion based on category (REQ-10-09)."""
        if category == ErrorCategory.VALIDATION:
            if model:
                return (
                    f"Check the field values. Use odoo_core_fields_get with model='{model}' "
                    "to see field types and requirements."
                )
            return "Check the field values and try again."

        if category == ErrorCategory.ACCESS:
            return "The current user does not have permission for this operation."

        if category == ErrorCategory.NOT_FOUND:
            return "The record or model was not found. Verify the ID or model name."

        if category == ErrorCategory.CONSTRAINT:
            return "A database constraint was violated. Check for duplicate or invalid values."

        if category == ErrorCategory.STATE:
            return "The record is in an invalid state for this operation. Check the current state first."

        if category == ErrorCategory.WIZARD:
            return "This operation requires a wizard interaction. Follow the wizard protocol."

        if category == ErrorCategory.CONNECTION:
            return "A connection error occurred. The server may be down or unreachable."

        if category == ErrorCategory.RATE_LIMIT:
            return "Too many requests. Wait before retrying."

        if category == ErrorCategory.CONFIGURATION:
            return "A configuration error was detected. An administrator needs to fix the server configuration."

        return "An unexpected error occurred. Check the error details and try a different approach."

    def _log_error(
        self,
        response: ErrorResponse,
        model: str | None,
        method: str | None,
    ) -> None:
        """Log the error at the appropriate level (REQ-10-18, REQ-10-19)."""
        context = {
            "model": model or "",
            "method": method or "",
            "error_code": response.code,
        }

        msg = f"[{response.code}] {response.message} | model={context['model']} method={context['method']}"

        if response.category in (
            ErrorCategory.VALIDATION,
            ErrorCategory.STATE,
            ErrorCategory.NOT_FOUND,
        ):
            logger.warning(msg)
        elif response.category in (
            ErrorCategory.ACCESS,
            ErrorCategory.CONNECTION,
            ErrorCategory.UNKNOWN,
        ):
            logger.error(msg)
        else:
            logger.warning(msg)

        # Always log full traceback at debug level
        if response.original_error:
            logger.debug("Full error: %s", response.original_error)
