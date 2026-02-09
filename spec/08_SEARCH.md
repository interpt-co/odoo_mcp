# 08 — Progressive Deep Search

| Field        | Value                              |
|-------------|-------------------------------------|
| Document ID | SPEC-08                             |
| Title       | Progressive Deep Search              |
| Status      | Draft                               |
| Depends On  | SPEC-04, SPEC-07                    |
| Referenced By | —                                  |

---

## 1. Overview

LLMs frequently search with imprecise, partial, or natural-language terms. Odoo's standard `name_search` is limited to exact/ilike matching on the `_rec_name` field. This document specifies a progressive deep search strategy that automatically broadens the search when initial attempts fail, significantly improving the LLM's ability to find records.

The progressive search is implemented as a dedicated tool and also used internally by workflow tools for name resolution.

---

## 2. Search Levels

**REQ-08-01**: The progressive search MUST implement 5 search levels, executed in order. Each level is tried only if previous levels returned insufficient results.

| Level | Name | Strategy | Performance |
|-------|------|----------|-------------|
| 1 | Exact Match | Exact `=` match on name field | Fast |
| 2 | Standard ilike | `ilike` on standard search fields | Fast |
| 3 | Extended Fields | `ilike` on deep search fields (email, phone, vat, ref, etc.) | Moderate |
| 4 | Related Models | Search across related models and expand to linked records | Slow |
| 5 | Chatter Search | Search in `mail.message` body | Slowest |

**REQ-08-02**: The search MUST stop and return results as soon as a level produces results that meet the minimum threshold (default: 1 record), unless the `exhaustive` flag is set.

---

## 3. Tool Specification

### 3.1 odoo_core_deep_search

**REQ-08-03**: The deep search tool belongs to the `core` toolset.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Search query — natural language or keywords. Examples: 'Acme', 'john@example.com', '+351 912 345 678'"
    },
    "model": {
      "type": "string",
      "description": "Primary model to search in. If omitted, searches across all configured models.",
      "default": null
    },
    "max_depth": {
      "type": "integer",
      "description": "Maximum search level to reach (1-5). Default: 3 for targeted searches, 5 for broad searches.",
      "default": 3,
      "minimum": 1,
      "maximum": 5
    },
    "limit": {
      "type": "integer",
      "description": "Maximum results per model. Default: 20.",
      "default": 20,
      "minimum": 1,
      "maximum": 100
    },
    "fields": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Fields to return. Default: model-specific defaults."
    },
    "exhaustive": {
      "type": "boolean",
      "description": "If true, run all levels regardless of early results. Default: false.",
      "default": false
    }
  },
  "required": ["query"]
}
```

---

## 4. Model Search Configuration

**REQ-08-04**: Each searchable model MUST have a search configuration:

```python
@dataclass
class ModelSearchConfig:
    model: str
    name_field: str                         # Field used for name_search (usually "name")
    search_fields: list[str]                # Level 2: standard searchable fields
    deep_search_fields: list[str]           # Level 3: extended searchable fields
    default_fields: list[str]               # Fields returned in results
    has_chatter: bool                       # Level 5: supports chatter search
    related_models: list[str]               # Level 4: models to expand search to
```

**REQ-08-05**: Default search configurations for common models:

```python
SEARCH_CONFIGS = {
    "res.partner": ModelSearchConfig(
        model="res.partner",
        name_field="name",
        search_fields=["name", "display_name"],
        deep_search_fields=["email", "phone", "mobile", "vat", "ref", "website", "comment", "street", "city"],
        default_fields=["id", "name", "email", "phone", "is_company", "city", "country_id"],
        has_chatter=True,
        related_models=["sale.order", "account.move", "crm.lead", "helpdesk.ticket"],
    ),
    "sale.order": ModelSearchConfig(
        model="sale.order",
        name_field="name",
        search_fields=["name", "client_order_ref"],
        deep_search_fields=["note", "origin"],
        default_fields=["id", "name", "partner_id", "state", "amount_total", "date_order"],
        has_chatter=True,
        related_models=["res.partner"],
    ),
    "account.move": ModelSearchConfig(
        model="account.move",
        name_field="name",
        search_fields=["name", "ref", "payment_reference"],
        deep_search_fields=["narration"],
        default_fields=["id", "name", "partner_id", "move_type", "state", "amount_total", "invoice_date"],
        has_chatter=True,
        related_models=["res.partner"],
    ),
    "crm.lead": ModelSearchConfig(
        model="crm.lead",
        name_field="name",
        search_fields=["name", "contact_name", "partner_name"],
        deep_search_fields=["email_from", "phone", "description"],
        default_fields=["id", "name", "partner_id", "stage_id", "expected_revenue", "user_id"],
        has_chatter=True,
        related_models=["res.partner"],
    ),
    "helpdesk.ticket": ModelSearchConfig(
        model="helpdesk.ticket",
        name_field="name",
        search_fields=["name"],
        deep_search_fields=["description"],
        default_fields=["id", "name", "partner_id", "stage_id", "user_id", "team_id", "priority"],
        has_chatter=True,
        related_models=["res.partner"],
    ),
    "product.product": ModelSearchConfig(
        model="product.product",
        name_field="name",
        search_fields=["name", "default_code"],
        deep_search_fields=["barcode", "description", "description_sale"],
        default_fields=["id", "name", "default_code", "list_price", "qty_available", "type"],
        has_chatter=False,
        related_models=[],
    ),
    "project.task": ModelSearchConfig(
        model="project.task",
        name_field="name",
        search_fields=["name"],
        deep_search_fields=["description"],
        default_fields=["id", "name", "project_id", "stage_id", "user_ids", "date_deadline", "priority"],
        has_chatter=True,
        related_models=["project.project"],
    ),
}
```

**REQ-08-06**: Models not in the configuration MAY still be searched using a fallback configuration that uses `name` as the search field and `name_search` for level 1.

---

## 5. Search Level Implementations

### 5.1 Level 1 — Exact Match

**REQ-08-07**: Search using exact `=` operator on the name field:

```python
domain = [(name_field, '=', query)]
results = await connection.search_read(model, domain, fields=default_fields, limit=limit)
```

### 5.2 Level 2 — Standard ilike

**REQ-08-08**: Search using `ilike` across standard search fields with multi-word support:

```python
# For multi-word queries, build OR domain across all search fields and all words
words = query.split()
conditions = []
for field in search_fields:
    for word in words:
        conditions.append((field, 'ilike', word))

# Build prefix-notation OR domain
domain = []
for _ in range(len(conditions) - 1):
    domain.append('|')
domain.extend(conditions)
```

### 5.3 Level 3 — Extended Fields

**REQ-08-09**: Same as Level 2 but using `deep_search_fields` instead of `search_fields`. Only fields that exist on the model (verified via registry) are used.

### 5.4 Level 4 — Related Models

**REQ-08-10**: Search across related models and expand to linked records:

1. Search the query in related models (e.g., search for "Acme" in `res.partner` when the primary model is `sale.order`).
2. Extract partner IDs from matches.
3. Expand partner IDs to include related contacts:
   - If partner is a company → include all child contacts (employees).
   - If partner is an individual → include parent company + siblings.
4. Search the primary model using expanded partner IDs:
   ```python
   domain = [('partner_id', 'in', expanded_partner_ids)]
   ```

### 5.5 Level 5 — Chatter Search

**REQ-08-11**: Search in `mail.message` body for models with chatter:

```python
message_domain = [
    ('model', '=', model),
    ('body', 'ilike', query),
    ('message_type', 'in', ['email', 'comment']),
]
messages = await connection.search_read('mail.message', message_domain, ['res_id'], limit=limit)
record_ids = list(set(m['res_id'] for m in messages))
# Then read the actual records
```

---

## 6. Response Format

**REQ-08-12**: The deep search response MUST include a search log for transparency:

```json
{
  "query": "acme",
  "results": {
    "res.partner": [
      {"id": 1, "name": "Acme Corp", "email": "info@acme.com", "is_company": true}
    ],
    "sale.order": [
      {"id": 42, "name": "SO042", "partner_id": {"id": 1, "name": "Acme Corp"}, "state": "sale"}
    ]
  },
  "search_log": [
    {"level": 1, "strategy": "exact_match", "model": "res.partner", "results_found": 0},
    {"level": 2, "strategy": "standard_ilike", "model": "res.partner", "results_found": 1},
    {"level": 2, "strategy": "standard_ilike", "model": "sale.order", "results_found": 0},
    {"level": 4, "strategy": "related_models", "model": "sale.order", "results_found": 1}
  ],
  "depth_reached": 4,
  "total_results": 2,
  "strategies_used": ["exact_match", "standard_ilike", "related_models"],
  "suggestions": [
    "Found partner 'Acme Corp' and their sales orders.",
    "Use odoo_core_search_read with domain [['partner_id', '=', 1]] to find more related records."
  ]
}
```

**REQ-08-13**: The `suggestions` field MUST contain LLM-actionable hints:
- If results were found via partner expansion, suggest searching other models with the partner ID.
- If no results were found, suggest alternative search terms or different models.
- If results came from chatter, note that the match was in message content, not record fields.

---

## 7. Domain Builder Utility

**REQ-08-14**: The search module MUST include a domain builder utility that helps construct valid Odoo domains:

```python
class DomainBuilder:
    def __init__(self):
        self._conditions: list = []

    def equals(self, field: str, value: Any) -> 'DomainBuilder': ...
    def not_equals(self, field: str, value: Any) -> 'DomainBuilder': ...
    def contains(self, field: str, value: str) -> 'DomainBuilder': ...  # ilike
    def in_list(self, field: str, values: list) -> 'DomainBuilder': ...
    def greater_than(self, field: str, value: Any) -> 'DomainBuilder': ...
    def less_than(self, field: str, value: Any) -> 'DomainBuilder': ...
    def between(self, field: str, low: Any, high: Any) -> 'DomainBuilder': ...
    def or_(*conditions: 'DomainBuilder') -> 'DomainBuilder': ...
    def build(self) -> list: ...
```

**REQ-08-15**: The domain builder is used internally by tools and the deep search engine. It is NOT exposed as an MCP tool (domains are passed as raw lists in tool schemas).

---

## 8. Name Search Utility

**REQ-08-16**: A reusable `name_search` utility MUST be provided for workflow tools:

```python
async def name_search(
    connection: OdooProtocol,
    model: str,
    name: str,
    operator: str = 'ilike',
    limit: int = 5,
    domain: list | None = None,
) -> list[dict]:
    """
    Search for records by name.
    Returns list of {"id": int, "name": str}.
    """
```

**REQ-08-17**: This utility wraps Odoo's native `name_search` method:
```python
results = await connection.execute_kw(model, 'name_search', [name], {
    'args': domain or [],
    'operator': operator,
    'limit': limit,
})
# name_search returns [[id, name], ...] → normalize to [{"id": id, "name": name}, ...]
```

---

## 9. HTML Content Handling

**REQ-08-18**: Search results that include HTML fields (`html` type or known HTML fields like `description`, `comment`, `body`, `note`) MUST be stripped to plain text by default.

**REQ-08-19**: The HTML stripping function:

```python
def strip_html(html_content: str) -> str:
    """Strip HTML tags and decode entities."""
    if not html_content:
        return ""
    # Replace <br> and </p> with newlines
    text = re.sub(r'<br\s*/?>', '\n', html_content, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
    # Remove all remaining tags
    text = re.sub(r'<[^>]+>', '', text)
    # Decode HTML entities
    text = html.unescape(text)
    # Clean up whitespace
    text = re.sub(r'\n\s*\n', '\n\n', text)
    return text.strip()
```
