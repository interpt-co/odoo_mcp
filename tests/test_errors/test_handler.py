"""Tests for the error classification handler."""

import json

import pytest

from odoo_mcp.errors import (
    ErrorCategory,
    ErrorCode,
    ErrorResponse,
    McpErrorCode,
    RETRY_GUIDANCE,
    get_retry_for_category,
    make_tool_error_result,
)
from odoo_mcp.errors.handler import ErrorHandler, _extract_traceback_exception


@pytest.fixture
def handler():
    return ErrorHandler()


# ── ErrorResponse Tests ──────────────────────────────────────────────

class TestErrorResponse:
    def test_to_dict_required_fields(self):
        resp = ErrorResponse(
            category="validation",
            code="VALIDATION_ERROR",
            message="Test message",
            suggestion="Test suggestion",
            retry=True,
        )
        d = resp.to_dict()
        assert d["error"] is True
        assert d["category"] == "validation"
        assert d["code"] == "VALIDATION_ERROR"
        assert d["message"] == "Test message"
        assert d["suggestion"] == "Test suggestion"
        assert d["retry"] is True
        assert "details" not in d
        assert "original_error" not in d

    def test_to_dict_with_optional_fields(self):
        resp = ErrorResponse(
            category="validation",
            code="VALIDATION_ERROR",
            message="Test",
            suggestion="Fix it",
            retry=True,
            details={"field": "name"},
            original_error="raw error",
        )
        d = resp.to_dict()
        assert d["details"] == {"field": "name"}
        assert d["original_error"] == "raw error"

    def test_to_json(self):
        resp = ErrorResponse(
            category="access",
            code="ACCESS_DENIED",
            message="Denied",
            suggestion="Ask admin",
            retry=False,
        )
        j = resp.to_json()
        parsed = json.loads(j)
        assert parsed["error"] is True
        assert parsed["category"] == "access"

    def test_make_tool_error_result(self):
        resp = ErrorResponse(
            category="validation",
            code="VALIDATION_ERROR",
            message="Bad input",
            suggestion="Fix input",
            retry=True,
        )
        result = make_tool_error_result(resp)
        assert result["isError"] is True
        assert len(result["content"]) == 1
        assert result["content"][0]["type"] == "text"
        parsed = json.loads(result["content"][0]["text"])
        assert parsed["error"] is True


# ── Retry Guidance Tests ─────────────────────────────────────────────

class TestRetryGuidance:
    def test_all_categories_have_guidance(self):
        for cat in ErrorCategory:
            assert cat in RETRY_GUIDANCE, f"Missing retry guidance for {cat}"

    def test_retryable_categories(self):
        retryable = {
            ErrorCategory.VALIDATION, ErrorCategory.NOT_FOUND,
            ErrorCategory.CONSTRAINT, ErrorCategory.STATE,
            ErrorCategory.WIZARD, ErrorCategory.CONNECTION,
            ErrorCategory.RATE_LIMIT,
        }
        for cat in retryable:
            assert get_retry_for_category(cat) is True, f"{cat} should be retryable"

    def test_non_retryable_categories(self):
        non_retryable = {
            ErrorCategory.ACCESS, ErrorCategory.CONFIGURATION,
            ErrorCategory.UNKNOWN,
        }
        for cat in non_retryable:
            assert get_retry_for_category(cat) is False, f"{cat} should not be retryable"


# ── MCP Error Codes ──────────────────────────────────────────────────

class TestMcpErrorCodes:
    def test_method_not_found(self):
        assert McpErrorCode.METHOD_NOT_FOUND == -32601

    def test_invalid_params(self):
        assert McpErrorCode.INVALID_PARAMS == -32602

    def test_internal_error(self):
        assert McpErrorCode.INTERNAL_ERROR == -32603


# ── Traceback Extraction ─────────────────────────────────────────────

class TestTracebackExtraction:
    def test_extract_from_traceback(self):
        tb = (
            "Traceback (most recent call last):\n"
            '  File "/opt/odoo/addons/sale/models/sale.py", line 42, in action_confirm\n'
            "    raise ValidationError('Missing lines')\n"
            "odoo.exceptions.ValidationError: Missing lines"
        )
        cls, msg = _extract_traceback_exception(tb)
        assert cls == "odoo.exceptions.ValidationError"
        assert msg == "Missing lines"

    def test_extract_class_only(self):
        tb = "odoo.exceptions.AccessDenied"
        cls, msg = _extract_traceback_exception(tb)
        assert cls == "odoo.exceptions.AccessDenied"
        assert msg == ""

    def test_extract_empty(self):
        cls, msg = _extract_traceback_exception("")
        assert cls == ""
        assert msg == ""

    def test_extract_plain_message(self):
        cls, msg = _extract_traceback_exception("Something went wrong")
        assert cls == ""
        assert msg == "Something went wrong"


# ── Pattern-Based Classification ─────────────────────────────────────

class TestPatternClassification:
    def test_missing_required_field(self, handler):
        resp = handler.classify(
            "Missing required fields: partner_id",
            error_class="odoo.exceptions.ValidationError",
            model="sale.order",
        )
        assert resp.category == "validation"
        assert resp.code == "MISSING_REQUIRED_FIELD"
        assert "partner_id" in resp.message
        assert resp.retry is True

    def test_invalid_field(self, handler):
        resp = handler.classify(
            "Invalid field 'foo' on model 'sale.order'",
            model="sale.order",
        )
        assert resp.category == "validation"
        assert resp.code == "INVALID_FIELD"
        assert "foo" in resp.message
        assert "sale.order" in resp.message

    def test_access_denied(self, handler):
        resp = handler.classify(
            "Access Denied",
            error_class="odoo.exceptions.AccessDenied",
        )
        assert resp.category == "access"
        assert resp.code == "ACCESS_DENIED"
        assert resp.retry is False

    def test_record_not_found(self, handler):
        resp = handler.classify(
            "Record does not exist or has been deleted. sale.order(999)",
            error_class="odoo.exceptions.MissingError",
            model="sale.order",
        )
        assert resp.category == "not_found"
        assert resp.code == "RECORD_NOT_FOUND"
        assert resp.retry is True

    def test_unique_violation(self, handler):
        resp = handler.classify(
            'duplicate key value violates unique constraint "sale_order_name_uniq" Key (name)=(SO001)',
            error_class="psycopg2.errors.UniqueViolation",
        )
        assert resp.category == "constraint"
        assert resp.code == "UNIQUE_VIOLATION"
        assert resp.retry is True

    def test_state_error(self, handler):
        resp = handler.classify(
            "Cannot confirm order in state 'cancel'",
            error_class="odoo.exceptions.UserError",
            model="sale.order",
        )
        assert resp.category == "state"
        assert resp.code == "INVALID_STATE_TRANSITION"
        assert resp.retry is True

    def test_connection_refused(self, handler):
        resp = handler.classify("Connection refused")
        assert resp.category == "connection"
        assert resp.code == "CONNECTION_REFUSED"
        assert resp.retry is True

    def test_timeout(self, handler):
        resp = handler.classify("Request timed out after 30 seconds")
        assert resp.category == "connection"
        assert resp.code == "TIMEOUT"

    def test_session_expired(self, handler):
        resp = handler.classify("Session expired, please re-authenticate")
        assert resp.category == "connection"
        assert resp.code == "SESSION_EXPIRED"

    def test_fallback_unknown(self, handler):
        resp = handler.classify("Some completely unknown error xyz abc 123")
        assert resp.category == "unknown"
        assert resp.code == "UNKNOWN_ERROR"
        assert resp.retry is False

    def test_original_error_preserved(self, handler):
        resp = handler.classify("Missing required fields: name")
        assert resp.original_error == "Missing required fields: name"

    def test_suggestion_references_tool_names(self, handler):
        resp = handler.classify(
            "Invalid field 'bad_field' on model 'sale.order'",
            model="sale.order",
        )
        assert "odoo_core_fields_get" in resp.suggestion

    def test_traceback_not_in_message(self, handler):
        resp = handler.classify(
            "Traceback (most recent call last):\n"
            "  File 'x.py', line 1\n"
            "  Missing required fields: name",
        )
        assert "Traceback" not in resp.message


# ── XML-RPC Fault Classification ─────────────────────────────────────

class TestXmlRpcClassification:
    def test_access_denied_in_fault_code(self, handler):
        resp = handler.classify_xmlrpc_fault(
            fault_code="Access Denied",
            fault_string="Access Denied",
        )
        assert resp.category == "access"
        assert resp.code == "ACCESS_DENIED"

    def test_validation_error(self, handler):
        resp = handler.classify_xmlrpc_fault(
            fault_code=1,
            fault_string="odoo.exceptions.ValidationError: Missing required fields: partner_id",
        )
        assert resp.category == "validation"

    def test_missing_error(self, handler):
        resp = handler.classify_xmlrpc_fault(
            fault_code=1,
            fault_string="odoo.exceptions.MissingError: Record does not exist or has been deleted. sale.order(42)",
        )
        assert resp.category == "not_found"

    def test_wizard_required(self, handler):
        resp = handler.classify_xmlrpc_fault(
            fault_code=1,
            fault_string="ir.actions.act_window is required for this operation",
        )
        assert resp.category == "wizard" or resp.code == "WIZARD_REQUIRED"

    def test_unknown_fault(self, handler):
        resp = handler.classify_xmlrpc_fault(
            fault_code=999,
            fault_string="Something totally unexpected",
        )
        assert resp.category == "unknown"

    def test_unique_constraint_in_fault(self, handler):
        resp = handler.classify_xmlrpc_fault(
            fault_code=1,
            fault_string='duplicate key value violates unique constraint "test_uniq" Key (ref)=(001)',
        )
        assert resp.category == "constraint"
        assert resp.code == "UNIQUE_VIOLATION"


# ── JSON-RPC Classification ──────────────────────────────────────────

class TestJsonRpcClassification:
    def test_validation_error(self, handler):
        data = {
            "name": "odoo.exceptions.ValidationError",
            "message": "Missing required fields: name",
            "debug": "",
        }
        resp = handler.classify_jsonrpc_error(data, model="sale.order")
        assert resp.category == "validation"

    def test_access_error(self, handler):
        data = {
            "name": "odoo.exceptions.AccessError",
            "message": "Access to model 'hr.employee' is not allowed",
            "debug": "",
        }
        resp = handler.classify_jsonrpc_error(data)
        assert resp.category == "access"

    def test_missing_error(self, handler):
        data = {
            "name": "odoo.exceptions.MissingError",
            "message": "Record does not exist or has been deleted. res.partner(999)",
            "debug": "",
        }
        resp = handler.classify_jsonrpc_error(data)
        assert resp.category == "not_found"

    def test_psycopg2_unique_violation(self, handler):
        data = {
            "name": "psycopg2.errors.UniqueViolation",
            "message": 'duplicate key value violates unique constraint "test_uniq" Key (code)=(X1)',
            "debug": "",
        }
        resp = handler.classify_jsonrpc_error(data)
        assert resp.category == "constraint"

    def test_debug_traceback_extraction(self, handler):
        data = {
            "name": "",
            "message": "",
            "debug": (
                "Traceback (most recent call last):\n"
                "  File 'x.py', line 10\n"
                "odoo.exceptions.ValidationError: Bad value"
            ),
        }
        resp = handler.classify_jsonrpc_error(data)
        assert resp.category == "validation"

    def test_unknown_class(self, handler):
        data = {
            "name": "some.random.Exception",
            "message": "something weird happened",
            "debug": "",
        }
        resp = handler.classify_jsonrpc_error(data)
        assert resp.code == "UNKNOWN_ERROR"


# ── HTTP Error Classification ────────────────────────────────────────

class TestHttpClassification:
    def test_connect_error(self, handler):
        resp = handler.classify_http_error(
            error_type="httpx.ConnectError",
            error_message="Connection refused",
        )
        assert resp.category == "connection"
        assert resp.code == "CONNECTION_REFUSED"

    def test_timeout_error(self, handler):
        resp = handler.classify_http_error(
            error_type="httpx.TimeoutException",
            error_message="Read timed out",
        )
        assert resp.category == "connection"
        assert resp.code == "TIMEOUT"

    def test_401_unauthorized(self, handler):
        resp = handler.classify_http_error(status_code=401)
        assert resp.category == "access"
        assert resp.code == "SESSION_EXPIRED"

    def test_403_forbidden(self, handler):
        resp = handler.classify_http_error(status_code=403)
        assert resp.category == "access"
        assert resp.code == "SESSION_EXPIRED"

    def test_404_not_found(self, handler):
        resp = handler.classify_http_error(status_code=404)
        assert resp.category == "connection"
        assert resp.code == "ENDPOINT_NOT_FOUND"

    def test_429_rate_limited(self, handler):
        resp = handler.classify_http_error(status_code=429)
        assert resp.category == "rate_limit"
        assert resp.code == "RATE_LIMITED"
        assert resp.retry is True
        assert resp.details is not None
        assert "retry_after" in resp.details

    def test_500_server_error(self, handler):
        resp = handler.classify_http_error(status_code=500)
        assert resp.category == "connection"
        assert resp.code == "SERVER_ERROR"

    def test_502_server_error(self, handler):
        resp = handler.classify_http_error(status_code=502)
        assert resp.category == "connection"
        assert resp.code == "SERVER_ERROR"


# ── Exception Classification ─────────────────────────────────────────

class TestExceptionClassification:
    def test_generic_exception(self, handler):
        exc = ValueError("Invalid literal for int() with base 10: 'abc'")
        resp = handler.classify_exception(exc)
        assert resp.category == "validation"
        assert resp.code == "INVALID_INTEGER"

    def test_runtime_error(self, handler):
        exc = RuntimeError("Something completely unknown")
        resp = handler.classify_exception(exc)
        assert resp.category == "unknown"


# ── Logging Level Tests ──────────────────────────────────────────────

class TestLogging:
    def test_validation_logs_warning(self, handler, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="odoo_mcp.errors.handler"):
            handler.classify("Missing required fields: name", model="sale.order")
        assert any("MISSING_REQUIRED_FIELD" in r.message for r in caplog.records)

    def test_access_logs_error(self, handler, caplog):
        import logging
        with caplog.at_level(logging.ERROR, logger="odoo_mcp.errors.handler"):
            handler.classify("Access Denied", error_class="odoo.exceptions.AccessDenied")
        assert any("ACCESS_DENIED" in r.message for r in caplog.records)

    def test_unknown_logs_error(self, handler, caplog):
        import logging
        with caplog.at_level(logging.ERROR, logger="odoo_mcp.errors.handler"):
            handler.classify("Totally unknown error 12345")
        assert any("UNKNOWN_ERROR" in r.message for r in caplog.records)

    def test_debug_includes_original(self, handler, caplog):
        import logging
        with caplog.at_level(logging.DEBUG, logger="odoo_mcp.errors.handler"):
            handler.classify("Missing required fields: name")
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("Missing required fields" in r.message for r in debug_records)
