# L2/04a — Domain Filter Reference

| Field        | Value                              |
|-------------|-------------------------------------|
| Document ID | SPEC-L2-04a                         |
| Title       | Domain Filter Reference              |
| Status      | Draft                               |
| Parent      | SPEC-04 (Core Tools)                |

---

## 1. Overview

This document is the complete reference for Odoo's domain filter syntax. It is designed to be used both as a specification for domain validation in the server and as LLM context (embedded in tool descriptions and prompts).

---

## 2. Domain Structure

**REQ-04a-01**: An Odoo domain is a list of criteria used to filter records. Each criterion is either:
- A **condition tuple**: `(field_name, operator, value)`
- A **logical operator**: `'&'` (AND), `'|'` (OR), `'!'` (NOT)

**REQ-04a-02**: Domains use **Polish (prefix) notation** for logical operators. The operator comes before its operands.

```python
# Implicit AND (default) — all conditions must match:
[('state', '=', 'draft'), ('amount', '>=', 1000)]
# Equivalent to:
['&', ('state', '=', 'draft'), ('amount', '>=', 1000)]

# OR — either condition matches:
['|', ('state', '=', 'draft'), ('state', '=', 'sent')]

# NOT — negation of a condition:
['!', ('active', '=', False)]

# Complex: (state = 'draft' OR state = 'sent') AND amount >= 1000
['&', '|', ('state', '=', 'draft'), ('state', '=', 'sent'), ('amount', '>=', 1000)]
```

**REQ-04a-03**: When multiple conditions are listed without explicit operators, they are implicitly joined with `'&'` (AND):

```python
# These are equivalent:
[('a', '=', 1), ('b', '=', 2), ('c', '=', 3)]
['&', '&', ('a', '=', 1), ('b', '=', 2), ('c', '=', 3)]
```

---

## 3. Comparison Operators

**REQ-04a-04**: Complete operator reference:

| Operator | Description | Value Type | Example |
|----------|-----------|------------|---------|
| `=` | Equals | any | `('state', '=', 'draft')` |
| `!=` | Not equals | any | `('state', '!=', 'cancel')` |
| `>` | Greater than | number, date, datetime | `('amount', '>', 1000)` |
| `>=` | Greater than or equal | number, date, datetime | `('date', '>=', '2025-01-01')` |
| `<` | Less than | number, date, datetime | `('amount', '<', 500)` |
| `<=` | Less than or equal | number, date, datetime | `('date', '<=', '2025-12-31')` |
| `like` | SQL LIKE (case-sensitive, `%` implicit) | string | `('name', 'like', 'Acme')` matches "Acme Corp" |
| `not like` | NOT LIKE | string | `('name', 'not like', 'test')` |
| `ilike` | Case-insensitive LIKE | string | `('name', 'ilike', 'acme')` matches "ACME Corp" |
| `not ilike` | Case-insensitive NOT LIKE | string | `('email', 'not ilike', '@test.com')` |
| `=like` | SQL LIKE (exact pattern, use `%` explicitly) | string | `('name', '=like', 'SO%')` matches names starting with "SO" |
| `=ilike` | Case-insensitive exact pattern | string | `('name', '=ilike', 'so%')` |
| `in` | Value in list | list | `('state', 'in', ['draft', 'sent'])` |
| `not in` | Value not in list | list | `('state', 'not in', ['cancel', 'done'])` |
| `child_of` | Is child of (hierarchical) | int or list | `('partner_id', 'child_of', 1)` — all children of partner 1 |
| `parent_of` | Is parent of (hierarchical) | int or list | `('partner_id', 'parent_of', 5)` — all parents of partner 5 |

### 3.1 Operator Notes

**REQ-04a-05**: Important behavior details:

1. **`like`/`ilike`**: Odoo automatically wraps the value with `%` wildcards: `('name', 'ilike', 'acme')` becomes `name ILIKE '%acme%'`.
2. **`=like`/`=ilike`**: No automatic wrapping. Use `%` explicitly: `('name', '=like', 'SO%')` matches names starting with "SO".
3. **`in`/`not in`**: The value MUST be a list: `('id', 'in', [1, 2, 3])`.
4. **`child_of`/`parent_of`**: Work on hierarchical models with `parent_id` field. The value is the parent/child record ID.
5. **`=` with `False`**: `('field', '=', False)` matches records where the field is empty/null/false.
6. **`!=` with `False`**: `('field', '!=', False)` matches records where the field has a value (is not empty).

---

## 4. Field References

**REQ-04a-06**: Domains support dot-notation for traversing relational fields:

```python
# Direct field:
('state', '=', 'draft')

# Many2one traversal:
('partner_id.name', 'ilike', 'acme')              # Customer name
('partner_id.country_id.code', '=', 'PT')          # Customer's country code
('partner_id.parent_id.name', 'ilike', 'corp')      # Customer's parent company name

# One2many traversal (matches if ANY related record matches):
('order_line.product_id.name', 'ilike', 'widget')   # Any order line has a product named "widget"
('invoice_ids.state', '=', 'posted')                 # Has a posted invoice
```

**REQ-04a-07**: Dot-notation limitations:
- Maximum traversal depth: Odoo does not enforce a limit, but the server SHOULD warn for depth > 4.
- One2many/Many2many traversal matches if ANY related record matches (implicit `ANY`).
- Computed fields can be traversed but may be slow (not indexed).

---

## 5. Date and Datetime Values

**REQ-04a-08**: Date and datetime values in domains MUST be strings:

```python
# Date field (date):
('date_order', '>=', '2025-01-01')
('date_order', '<=', '2025-12-31')

# Datetime field (datetime):
('create_date', '>=', '2025-01-01 00:00:00')
('write_date', '<=', '2025-02-09 23:59:59')
```

**REQ-04a-09**: Datetime values are always in **UTC**. The server MUST NOT apply timezone conversion to domain datetime values.

---

## 6. One2many/Many2many Command Tuples

**REQ-04a-10**: When creating or updating records with One2many or Many2many fields, special command tuples are used:

| Command | Format | Description |
|---------|--------|-------------|
| CREATE | `(0, 0, {values})` | Create a new related record with the given values |
| UPDATE | `(1, id, {values})` | Update an existing related record (by ID) with the given values |
| DELETE | `(2, id, 0)` | Delete the related record (remove from DB) |
| UNLINK | `(3, id, 0)` | Unlink the related record (remove relationship, keep record) |
| LINK | `(4, id, 0)` | Link an existing record (add to relationship) |
| UNLINK ALL | `(5, 0, 0)` | Remove all linked records (Many2many only) |
| REPLACE | `(6, 0, [ids])` | Replace all linked records with the given ID list |

### 6.1 Examples

**REQ-04a-11**: Command tuple examples:

```python
# Create a sale order with new order lines:
{
    "partner_id": 1,
    "order_line": [
        (0, 0, {"product_id": 5, "product_uom_qty": 2, "price_unit": 100.0}),
        (0, 0, {"product_id": 8, "product_uom_qty": 1, "price_unit": 50.0}),
    ]
}

# Update a specific order line:
{
    "order_line": [
        (1, 42, {"product_uom_qty": 5}),  # Change quantity of line 42
    ]
}

# Delete a specific order line:
{
    "order_line": [
        (2, 42, 0),  # Remove line 42 from the order and delete it
    ]
}

# Replace all tags on a record:
{
    "tag_ids": [
        (6, 0, [1, 3, 5]),  # Set tags to exactly IDs 1, 3, 5
    ]
}

# Add a tag to existing tags:
{
    "tag_ids": [
        (4, 7, 0),  # Add tag 7 to existing tags
    ]
}

# Remove a tag without deleting it:
{
    "tag_ids": [
        (3, 7, 0),  # Remove tag 7 from this record (tag still exists)
    ]
}
```

---

## 7. Common Domain Patterns

**REQ-04a-12**: Reference patterns for LLM tool descriptions:

### 7.1 Basic Patterns

```python
# Empty domain (all records):
[]

# Single condition:
[('state', '=', 'draft')]

# Multiple AND conditions:
[('state', '=', 'draft'), ('partner_id', '=', 42)]

# OR conditions:
['|', ('state', '=', 'draft'), ('state', '=', 'sent')]

# NOT condition:
['!', ('active', '=', False)]
```

### 7.2 Text Search Patterns

```python
# Contains (case-insensitive):
[('name', 'ilike', 'acme')]

# Starts with:
[('name', '=ilike', 'SO%')]

# Ends with:
[('email', '=ilike', '%@acme.com')]

# Multiple words (search for records matching ANY word):
['|', ('name', 'ilike', 'acme'), ('name', 'ilike', 'corp')]
```

### 7.3 Date Range Patterns

```python
# Records from this month:
[('date', '>=', '2025-02-01'), ('date', '<=', '2025-02-28')]

# Records from last 7 days:
[('create_date', '>=', '2025-02-02 00:00:00')]

# Records from a specific year:
[('date_order', '>=', '2025-01-01'), ('date_order', '<', '2026-01-01')]
```

### 7.4 Relational Patterns

```python
# Records for a specific partner:
[('partner_id', '=', 42)]

# Records for partners in a country:
[('partner_id.country_id.code', '=', 'PT')]

# Records with a specific tag:
[('tag_ids', 'in', [5])]

# Records without any tags:
[('tag_ids', '=', False)]
```

### 7.5 State Filter Patterns

```python
# Active records only (Odoo filters these by default):
[('active', '=', True)]

# Include archived records:
# Pass context {'active_test': False} instead of domain

# Draft or sent:
[('state', 'in', ['draft', 'sent'])]

# Not cancelled:
[('state', '!=', 'cancel')]
```

---

## 8. Domain Validation

**REQ-04a-13**: The server MUST validate domains before sending them to Odoo:

1. Each element is either a tuple/list of 3 elements or a string (`'&'`, `'|'`, `'!'`).
2. Operators are in the valid operator set (REQ-04a-04).
3. `in`/`not in` operators have list values.
4. The domain is well-formed in prefix notation (correct number of operands for each operator).

**REQ-04a-14**: If validation fails, return a helpful error:

```json
{
  "error": true,
  "category": "validation",
  "code": "INVALID_DOMAIN",
  "message": "Invalid domain: operator 'in' requires a list value, got string 'draft'",
  "suggestion": "Change [('state', 'in', 'draft')] to [('state', 'in', ['draft'])] or use ('state', '=', 'draft') for single values."
}
```
