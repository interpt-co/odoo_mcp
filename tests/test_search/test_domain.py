"""Tests for odoo_mcp.search.domain — DomainBuilder, validation, multi-word ilike."""

import pytest

from odoo_mcp.search.domain import (
    DomainBuilder,
    DomainValidationError,
    build_multi_word_ilike_domain,
    validate_domain,
)


# ---------------------------------------------------------------------------
# DomainBuilder
# ---------------------------------------------------------------------------

class TestDomainBuilder:
    def test_equals(self):
        d = DomainBuilder().equals("state", "draft").build()
        assert d == [("state", "=", "draft")]

    def test_not_equals(self):
        d = DomainBuilder().not_equals("state", "cancel").build()
        assert d == [("state", "!=", "cancel")]

    def test_contains(self):
        d = DomainBuilder().contains("name", "acme").build()
        assert d == [("name", "ilike", "acme")]

    def test_in_list(self):
        d = DomainBuilder().in_list("state", ["draft", "sent"]).build()
        assert d == [("state", "in", ["draft", "sent"])]

    def test_greater_than(self):
        d = DomainBuilder().greater_than("amount", 1000).build()
        assert d == [("amount", ">", 1000)]

    def test_less_than(self):
        d = DomainBuilder().less_than("amount", 500).build()
        assert d == [("amount", "<", 500)]

    def test_between(self):
        d = DomainBuilder().between("date", "2025-01-01", "2025-12-31").build()
        assert d == [("date", ">=", "2025-01-01"), ("date", "<=", "2025-12-31")]

    def test_chaining(self):
        d = (
            DomainBuilder()
            .equals("state", "draft")
            .greater_than("amount", 100)
            .build()
        )
        assert len(d) == 2
        assert d[0] == ("state", "=", "draft")
        assert d[1] == ("amount", ">", 100)

    def test_or_static(self):
        a = DomainBuilder().equals("state", "draft")
        b = DomainBuilder().equals("state", "sent")
        d = DomainBuilder.or_(a, b).build()
        assert d == ["|", ("state", "=", "draft"), ("state", "=", "sent")]

    def test_or_multiple(self):
        a = DomainBuilder().equals("state", "draft")
        b = DomainBuilder().equals("state", "sent")
        c = DomainBuilder().equals("state", "sale")
        d = DomainBuilder.or_(a, b, c).build()
        assert d[0] == "|"
        assert d[1] == "|"
        # 3 conditions
        assert len(d) == 5  # 2 '|' + 3 conditions

    def test_or_single(self):
        a = DomainBuilder().equals("state", "draft")
        d = DomainBuilder.or_(a).build()
        assert d == [("state", "=", "draft")]

    def test_empty(self):
        d = DomainBuilder().build()
        assert d == []


# ---------------------------------------------------------------------------
# validate_domain
# ---------------------------------------------------------------------------

class TestValidateDomain:
    def test_empty_domain(self):
        validate_domain([])  # should not raise

    def test_single_condition(self):
        validate_domain([("state", "=", "draft")])

    def test_list_condition(self):
        validate_domain([["state", "=", "draft"]])

    def test_multiple_and_conditions(self):
        validate_domain([
            ("state", "=", "draft"),
            ("amount", ">=", 1000),
        ])

    def test_or_domain(self):
        validate_domain([
            "|",
            ("state", "=", "draft"),
            ("state", "=", "sent"),
        ])

    def test_not_domain(self):
        validate_domain(["!", ("active", "=", False)])

    def test_complex_domain(self):
        validate_domain([
            "&",
            "|", ("state", "=", "draft"), ("state", "=", "sent"),
            ("amount", ">=", 1000),
        ])

    def test_all_valid_operators(self):
        for op in ("=", "!=", ">", ">=", "<", "<=", "like", "not like",
                    "ilike", "not ilike", "=like", "=ilike",
                    "child_of", "parent_of"):
            validate_domain([("field", op, "value")])

    def test_in_operator_with_list(self):
        validate_domain([("state", "in", ["draft", "sent"])])

    def test_not_in_operator_with_list(self):
        validate_domain([("state", "not in", ["cancel"])])

    # --- Error cases ---

    def test_not_a_list(self):
        with pytest.raises(DomainValidationError, match="must be a list"):
            validate_domain("not a list")

    def test_invalid_operator(self):
        with pytest.raises(DomainValidationError, match="Invalid operator"):
            validate_domain([("state", "==", "draft")])

    def test_invalid_logical_operator(self):
        with pytest.raises(DomainValidationError, match="Invalid logical operator"):
            validate_domain(["AND", ("state", "=", "draft")])

    def test_condition_wrong_length(self):
        with pytest.raises(DomainValidationError, match="3 elements"):
            validate_domain([("state", "=")])

    def test_in_requires_list(self):
        with pytest.raises(DomainValidationError, match="requires a list"):
            validate_domain([("state", "in", "draft")])

    def test_not_in_requires_list(self):
        with pytest.raises(DomainValidationError, match="requires a list"):
            validate_domain([("state", "not in", "cancel")])

    def test_in_error_has_suggestion(self):
        with pytest.raises(DomainValidationError) as exc_info:
            validate_domain([("state", "in", "draft")])
        assert exc_info.value.suggestion is not None
        assert "['draft']" in exc_info.value.suggestion

    def test_field_name_not_string(self):
        with pytest.raises(DomainValidationError, match="Field name must be a string"):
            validate_domain([(123, "=", "x")])

    def test_operator_not_string(self):
        with pytest.raises(DomainValidationError, match="Operator must be a string"):
            validate_domain([("field", 123, "x")])

    def test_invalid_element_type(self):
        with pytest.raises(DomainValidationError, match="Invalid domain element"):
            validate_domain([42])

    def test_prefix_notation_missing_operand(self):
        """An '|' with only one operand should fail."""
        with pytest.raises(DomainValidationError, match="missing"):
            validate_domain(["|", ("state", "=", "draft")])


# ---------------------------------------------------------------------------
# build_multi_word_ilike_domain
# ---------------------------------------------------------------------------

class TestBuildMultiWordIlikeDomain:
    def test_single_word_single_field(self):
        d = build_multi_word_ilike_domain(["name"], "acme")
        assert d == [("name", "ilike", "acme")]

    def test_multi_word_single_field(self):
        d = build_multi_word_ilike_domain(["name"], "john smith")
        assert len(d) == 3  # 1 '|' + 2 conditions
        assert d[0] == "|"

    def test_single_word_multi_field(self):
        d = build_multi_word_ilike_domain(["name", "email"], "acme")
        assert len(d) == 3  # 1 '|' + 2 conditions
        assert d[0] == "|"

    def test_multi_word_multi_field(self):
        d = build_multi_word_ilike_domain(["name", "email"], "john acme")
        # 4 conditions (2 fields x 2 words), 3 '|'s
        assert len(d) == 7
        conditions = [x for x in d if isinstance(x, tuple)]
        assert len(conditions) == 4

    def test_empty_query(self):
        assert build_multi_word_ilike_domain(["name"], "") == []

    def test_empty_fields(self):
        assert build_multi_word_ilike_domain([], "acme") == []
