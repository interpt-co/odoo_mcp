"""Tests for the error pattern database."""

import re

import pytest

from odoo_mcp.errors.patterns import ERROR_PATTERNS, ErrorPattern


class TestErrorPatternStructure:
    """Test that all patterns are well-formed."""

    def test_all_patterns_have_unique_ids(self):
        ids = [p.id for p in ERROR_PATTERNS]
        assert len(ids) == len(set(ids)), f"Duplicate pattern IDs: {[x for x in ids if ids.count(x) > 1]}"

    def test_all_patterns_compile(self):
        for pattern in ERROR_PATTERNS:
            try:
                re.compile(pattern.pattern, re.IGNORECASE)
            except re.error as e:
                pytest.fail(f"Pattern {pattern.id} has invalid regex: {e}")

    def test_all_patterns_have_required_fields(self):
        for pattern in ERROR_PATTERNS:
            assert pattern.id, f"Pattern missing id"
            assert pattern.pattern, f"Pattern {pattern.id} missing regex pattern"
            assert pattern.category, f"Pattern {pattern.id} missing category"
            assert pattern.code, f"Pattern {pattern.id} missing code"
            assert pattern.message_template, f"Pattern {pattern.id} missing message_template"
            assert pattern.suggestion_template, f"Pattern {pattern.id} missing suggestion_template"

    def test_minimum_pattern_count(self):
        assert len(ERROR_PATTERNS) >= 25, f"Expected 25+ patterns, got {len(ERROR_PATTERNS)}"


class TestValidationPatterns:
    """Test validation error patterns (VAL-001 through VAL-007)."""

    def test_val001_missing_required_field(self):
        pattern = _find_pattern("VAL-001")
        assert _matches(pattern, "Missing required fields: partner_id")
        assert _matches(pattern, "Required field 'name'")

    def test_val001b_not_null_constraint(self):
        pattern = _find_pattern("VAL-001b")
        assert _matches(pattern, 'null value in column "name" violates not-null constraint')
        match = re.search(pattern.pattern, 'null value in column "partner_id" violates not-null constraint', re.IGNORECASE)
        assert match and match.group(1) == "partner_id"

    def test_val002_invalid_field(self):
        pattern = _find_pattern("VAL-002")
        assert _matches(pattern, "Invalid field 'foo_bar' on model 'sale.order'")
        match = re.search(pattern.pattern, "Invalid field 'xyz' on model 'res.partner'", re.IGNORECASE)
        assert match and match.group(1) == "xyz"
        assert match.group(2) == "res.partner"

    def test_val003_wrong_value(self):
        pattern = _find_pattern("VAL-003")
        assert _matches(pattern, "Wrong value for state: 'invalid'")
        match = re.search(pattern.pattern, "Wrong value for type: 'bad_val'", re.IGNORECASE)
        assert match and match.group(1) == "type"
        assert match.group(2) == "bad_val"

    def test_val004_expected_singleton(self):
        pattern = _find_pattern("VAL-004")
        assert _matches(pattern, "Expected singleton: sale.order(1, 2, 3) - got 3 records")
        match = re.search(pattern.pattern, "Expected singleton but got 5 records", re.IGNORECASE)
        assert match and match.group(1) == "5"

    def test_val005_invalid_selection(self):
        pattern = _find_pattern("VAL-005")
        assert _matches(pattern, "Selection 'bad' invalid for field 'state' on model 'sale.order'")
        match = re.search(pattern.pattern, "Selection 'xyz' invalid for field 'type' on model 'account.move'", re.IGNORECASE)
        assert match and match.group(1) == "xyz"
        assert match.group(2) == "type"
        assert match.group(3) == "account.move"

    def test_val006_type_mismatch(self):
        pattern = _find_pattern("VAL-006")
        assert _matches(pattern, "Expected int, but got str")
        assert _matches(pattern, "expected integer, received string")

    def test_val007_invalid_integer(self):
        pattern = _find_pattern("VAL-007")
        assert _matches(pattern, "invalid literal for int() with base 10: 'abc'")
        match = re.search(pattern.pattern, "Invalid literal for int() with base 10: 'hello'", re.IGNORECASE)
        assert match and match.group(1) == "hello"


class TestAccessPatterns:
    """Test access error patterns (ACC-001 through ACC-004)."""

    def test_acc001_access_denied(self):
        pattern = _find_pattern("ACC-001")
        assert _matches(pattern, "Access Denied")

    def test_acc002_operation_not_allowed(self):
        pattern = _find_pattern("ACC-002")
        assert _matches(pattern, "You are not allowed to modify this type of document")
        assert _matches(pattern, "Sorry, you are not allowed to access the document")

    def test_acc003_record_rule_violation(self):
        pattern = _find_pattern("ACC-003")
        assert _matches(pattern, "Record rule prevented access to sale.order")

    def test_acc004_model_access_denied(self):
        pattern = _find_pattern("ACC-004")
        assert _matches(pattern, "Access to model 'hr.employee' is not allowed")
        match = re.search(pattern.pattern, "Access to model 'hr.employee' is not allowed", re.IGNORECASE)
        assert match and match.group(1) == "hr.employee"


class TestNotFoundPatterns:
    """Test not found patterns (NF-001, NF-002)."""

    def test_nf001_record_not_found(self):
        pattern = _find_pattern("NF-001")
        assert _matches(pattern, "Record does not exist or has been deleted. sale.order(999)")
        match = re.search(pattern.pattern, "Record does not exist or has been deleted. res.partner(42)", re.IGNORECASE)
        assert match and match.group(1) == "res.partner"
        assert match.group(2) == "42"

    def test_nf002_model_not_found(self):
        pattern = _find_pattern("NF-002")
        assert _matches(pattern, "Model 'fake.model' does not exist")
        assert _matches(pattern, "unknown model: 'bad.model'")


class TestConstraintPatterns:
    """Test constraint patterns (CON-001 through CON-003)."""

    def test_con001_unique_violation(self):
        pattern = _find_pattern("CON-001")
        msg = 'duplicate key value violates unique constraint "sale_order_name_unique" Key (name)=(SO001)'
        assert _matches(pattern, msg)
        match = re.search(pattern.pattern, msg, re.IGNORECASE)
        assert match and match.group(1) == "sale_order_name_unique"
        assert match.group(2) == "name"
        assert match.group(3) == "SO001"

    def test_con002_check_constraint(self):
        pattern = _find_pattern("CON-002")
        assert _matches(pattern, 'new row violates check constraint "positive_qty" violated')

    def test_con003_fk_violation(self):
        pattern = _find_pattern("CON-003")
        assert _matches(pattern, 'foreign key constraint "sale_order_partner_fk" referenced by "res_partner"')


class TestStatePatterns:
    """Test state patterns (ST-001 through ST-003)."""

    def test_st001_invalid_state_transition(self):
        pattern = _find_pattern("ST-001")
        assert _matches(pattern, "Cannot confirm order in state 'cancel'")
        assert _matches(pattern, "can't validate record in state 'done'")

    def test_st002_draft_required(self):
        pattern = _find_pattern("ST-002")
        assert _matches(pattern, "Only draft orders can be confirmed")
        assert _matches(pattern, "only quotation can be sent")

    def test_st003_already_processed(self):
        pattern = _find_pattern("ST-003")
        assert _matches(pattern, "This order has been already confirmed")
        assert _matches(pattern, "Invoice already posted")
        assert _matches(pattern, "Transfer has been validated")


class TestBusinessLogicPatterns:
    """Test business logic patterns (BIZ-001 through BIZ-005)."""

    def test_biz001_missing_accounting_config(self):
        pattern = _find_pattern("BIZ-001")
        assert _matches(pattern, "No account configured for this operation")
        assert _matches(pattern, "no journal found for this transaction")

    def test_biz002_insufficient_stock(self):
        pattern = _find_pattern("BIZ-002")
        assert _matches(pattern, "Not enough stock available")
        assert _matches(pattern, "insufficient quantity in warehouse")

    def test_biz003_missing_lines(self):
        pattern = _find_pattern("BIZ-003")
        assert _matches(pattern, "The order has no lines")
        assert _matches(pattern, "invoice without any items")

    def test_biz004_already_reconciled(self):
        pattern = _find_pattern("BIZ-004")
        assert _matches(pattern, "The move entry is already reconciled")

    def test_biz005_cannot_delete_processed(self):
        pattern = _find_pattern("BIZ-005")
        assert _matches(pattern, "You can not delete a posted invoice")
        assert _matches(pattern, "cannot unlink a confirmed order")


class TestConnectionPatterns:
    """Test connection patterns (CONN-001 through CONN-003)."""

    def test_conn001_connection_refused(self):
        pattern = _find_pattern("CONN-001")
        assert _matches(pattern, "Connection refused")
        assert _matches(pattern, "ECONNREFUSED")

    def test_conn002_timeout(self):
        pattern = _find_pattern("CONN-002")
        assert _matches(pattern, "Request timed out")
        assert _matches(pattern, "ETIMEDOUT")

    def test_conn003_session_expired(self):
        pattern = _find_pattern("CONN-003")
        assert _matches(pattern, "Session expired")
        assert _matches(pattern, "Invalid session")


class TestPatternOrder:
    """Test that patterns are ordered by specificity."""

    def test_specific_before_general(self):
        """VAL-001 (specific with error_class) should come before NF-002 (general)."""
        val001_idx = _find_index("VAL-001")
        nf002_idx = _find_index("NF-002")
        assert val001_idx < nf002_idx

    def test_conn_patterns_at_end(self):
        """Connection patterns (general) should be after specific patterns."""
        conn001_idx = _find_index("CONN-001")
        val001_idx = _find_index("VAL-001")
        assert val001_idx < conn001_idx


class TestPatternExtensibility:
    """Test that the pattern database is extensible (REQ-10-12, REQ-10a-03)."""

    def test_can_append_custom_pattern(self):
        original_len = len(ERROR_PATTERNS)
        custom = ErrorPattern(
            id="CUSTOM-001",
            pattern=r"Custom error: (\w+)",
            error_class=None,
            category="validation",
            code="CUSTOM_ERROR",
            message_template="Custom error: {detail}",
            suggestion_template="Fix the custom error.",
            extract_groups={"detail": "group1"},
        )
        ERROR_PATTERNS.append(custom)
        assert len(ERROR_PATTERNS) == original_len + 1
        assert _matches(custom, "Custom error: something")
        # Clean up
        ERROR_PATTERNS.pop()
        assert len(ERROR_PATTERNS) == original_len


# ── Helpers ──────────────────────────────────────────────────────────

def _find_pattern(pattern_id: str) -> ErrorPattern:
    for p in ERROR_PATTERNS:
        if p.id == pattern_id:
            return p
    raise ValueError(f"Pattern {pattern_id} not found")


def _find_index(pattern_id: str) -> int:
    for i, p in enumerate(ERROR_PATTERNS):
        if p.id == pattern_id:
            return i
    raise ValueError(f"Pattern {pattern_id} not found")


def _matches(pattern: ErrorPattern, text: str) -> bool:
    return re.search(pattern.pattern, text, re.IGNORECASE) is not None
