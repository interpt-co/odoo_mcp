"""Domain builder utility and domain validation.

Implements REQ-04-38, REQ-04a-01 through REQ-04a-14, REQ-08-14, REQ-08-15.
The DomainBuilder is used internally — it is NOT exposed as an MCP tool.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Allowed operators (REQ-04a-04)
# ---------------------------------------------------------------------------

VALID_OPERATORS: set[str] = {
    "=", "!=",
    ">", ">=", "<", "<=",
    "like", "not like",
    "ilike", "not ilike",
    "=like", "=ilike",
    "in", "not in",
    "child_of", "parent_of",
}

LOGICAL_OPERATORS: set[str] = {"&", "|", "!"}

LIST_OPERATORS: set[str] = {"in", "not in"}


# ---------------------------------------------------------------------------
# Domain validation (REQ-04a-13 / REQ-04a-14)
# ---------------------------------------------------------------------------

class DomainValidationError(Exception):
    """Raised when a domain fails validation."""

    def __init__(self, message: str, suggestion: str | None = None):
        super().__init__(message)
        self.suggestion = suggestion


def validate_domain(domain: list) -> None:
    """Validate an Odoo domain list.

    Raises :class:`DomainValidationError` with an actionable suggestion when
    the domain is malformed.
    """
    if not isinstance(domain, list):
        raise DomainValidationError(
            "Domain must be a list.",
            suggestion="Wrap your domain in a list, e.g. [('field', '=', value)].",
        )

    if len(domain) == 0:
        return  # empty domain is valid

    # Walk the domain and validate each element
    i = 0
    while i < len(domain):
        element = domain[i]

        # Logical operator
        if isinstance(element, str):
            if element not in LOGICAL_OPERATORS:
                raise DomainValidationError(
                    f"Invalid logical operator '{element}'.",
                    suggestion=f"Valid logical operators are: {', '.join(sorted(LOGICAL_OPERATORS))}.",
                )
            i += 1
            continue

        # Condition tuple/list
        if isinstance(element, (list, tuple)):
            if len(element) != 3:
                raise DomainValidationError(
                    f"Domain condition must have exactly 3 elements, got {len(element)}: {element!r}.",
                    suggestion="Each condition should be (field, operator, value).",
                )
            field_name, operator, value = element

            if not isinstance(field_name, str):
                raise DomainValidationError(
                    f"Field name must be a string, got {type(field_name).__name__}: {field_name!r}.",
                )

            if not isinstance(operator, str):
                raise DomainValidationError(
                    f"Operator must be a string, got {type(operator).__name__}: {operator!r}.",
                )

            if operator not in VALID_OPERATORS:
                raise DomainValidationError(
                    f"Invalid operator '{operator}'.",
                    suggestion=f"Valid operators: {', '.join(sorted(VALID_OPERATORS))}.",
                )

            # 'in' / 'not in' require list values (REQ-04a-05)
            if operator in LIST_OPERATORS and not isinstance(value, list):
                raise DomainValidationError(
                    f"Operator '{operator}' requires a list value, got {type(value).__name__}: {value!r}.",
                    suggestion=(
                        f"Change [(\"{field_name}\", \"{operator}\", {value!r})] "
                        f"to [(\"{field_name}\", \"{operator}\", [{value!r}])]"
                        + (f" or use (\"{field_name}\", \"=\", {value!r}) for single values."
                           if operator == "in" else ".")
                    ),
                )

            i += 1
            continue

        raise DomainValidationError(
            f"Invalid domain element at index {i}: {element!r}.",
            suggestion="Each element must be a condition [field, operator, value] or a logical operator ('&', '|', '!').",
        )

    # Validate prefix-notation operand counts
    _validate_prefix_notation(domain)


def _validate_prefix_notation(domain: list) -> None:
    """Check that prefix-notation operators have the correct operand count."""
    # Count how many "leaf" conditions (non-string elements) are consumed
    # by logical operators.
    # '&' and '|' are binary (consume 2 operands), '!' is unary (consumes 1).
    # Implicit '&' joins are OK — the domain is valid as long as it can be
    # interpreted.  We only reject clearly broken prefix notation.
    try:
        _consume(domain, 0)
    except _PrefixError as exc:
        raise DomainValidationError(str(exc)) from None


class _PrefixError(Exception):
    pass


def _consume(domain: list, pos: int) -> int:
    """Consume one operand (condition or operator+operands) starting at *pos*.

    Returns the index after the consumed operand.
    """
    if pos >= len(domain):
        raise _PrefixError(
            "Unexpected end of domain — a logical operator is missing its operand(s)."
        )
    element = domain[pos]
    if isinstance(element, str) and element in LOGICAL_OPERATORS:
        if element == "!":
            return _consume(domain, pos + 1)
        # '&' and '|' consume two operands
        next_pos = _consume(domain, pos + 1)
        return _consume(domain, next_pos)
    # leaf condition
    return pos + 1


# ---------------------------------------------------------------------------
# DomainBuilder (REQ-08-14)
# ---------------------------------------------------------------------------

class DomainBuilder:
    """Fluent builder for Odoo search domains.

    Used internally by tools and the deep search engine (REQ-08-15).
    NOT exposed as an MCP tool.
    """

    def __init__(self) -> None:
        self._conditions: list[Any] = []

    # -- comparison helpers ------------------------------------------------

    def equals(self, field: str, value: Any) -> DomainBuilder:
        self._conditions.append((field, "=", value))
        return self

    def not_equals(self, field: str, value: Any) -> DomainBuilder:
        self._conditions.append((field, "!=", value))
        return self

    def contains(self, field: str, value: str) -> DomainBuilder:
        """Case-insensitive ``ilike`` match."""
        self._conditions.append((field, "ilike", value))
        return self

    def in_list(self, field: str, values: list) -> DomainBuilder:
        self._conditions.append((field, "in", values))
        return self

    def greater_than(self, field: str, value: Any) -> DomainBuilder:
        self._conditions.append((field, ">", value))
        return self

    def less_than(self, field: str, value: Any) -> DomainBuilder:
        self._conditions.append((field, "<", value))
        return self

    def between(self, field: str, low: Any, high: Any) -> DomainBuilder:
        self._conditions.append((field, ">=", low))
        self._conditions.append((field, "<=", high))
        return self

    # -- logical -----------------------------------------------------------

    @staticmethod
    def or_(*builders: DomainBuilder) -> DomainBuilder:
        """Combine multiple builders with OR in prefix notation."""
        all_conditions: list[Any] = []
        for b in builders:
            all_conditions.extend(b._conditions)

        result = DomainBuilder()
        if len(all_conditions) <= 1:
            result._conditions = all_conditions
            return result

        # prefix-notation OR: n-1 '|' operators before n conditions
        for _ in range(len(all_conditions) - 1):
            result._conditions.append("|")
        result._conditions.extend(all_conditions)
        return result

    def build(self) -> list:
        """Return a plain list suitable for Odoo's ``domain`` parameter."""
        return list(self._conditions)


# ---------------------------------------------------------------------------
# Multi-word ilike domain builder (REQ-08-08)
# ---------------------------------------------------------------------------

def build_multi_word_ilike_domain(fields: list[str], query: str) -> list:
    """Build an OR domain that matches any *word* in *query* across all *fields*.

    Example::

        build_multi_word_ilike_domain(["name", "email"], "john acme")
        # → ['|', '|', '|',
        #    ('name', 'ilike', 'john'), ('name', 'ilike', 'acme'),
        #    ('email', 'ilike', 'john'), ('email', 'ilike', 'acme')]
    """
    words = query.split()
    if not words or not fields:
        return []

    conditions: list[Any] = []
    for field in fields:
        for word in words:
            conditions.append((field, "ilike", word))

    if len(conditions) == 1:
        return conditions

    domain: list[Any] = []
    for _ in range(len(conditions) - 1):
        domain.append("|")
    domain.extend(conditions)
    return domain
