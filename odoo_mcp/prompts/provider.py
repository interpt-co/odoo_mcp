"""MCP Prompt Provider.

Implements REQ-06-17 through REQ-06-21.
"""

from __future__ import annotations

import logging
from typing import Any

from odoo_mcp.registry.model_registry import (
    ModelRegistry,
    ModelInfo,
    FieldInfo,
    FIELD_TYPE_MAP,
)

logger = logging.getLogger(__name__)


DOMAIN_HELP_TEXT = """\
# Odoo Domain Filter Syntax Reference

## Structure
A domain is a list of criteria. Each criterion is either:
- A condition tuple: `(field_name, operator, value)`
- A logical operator: `'&'` (AND), `'|'` (OR), `'!'` (NOT)

Domains use **Polish (prefix) notation** for logical operators.

## Implicit AND
Multiple conditions without operators are joined with AND:
```
[('state', '=', 'draft'), ('amount', '>=', 1000)]
```

## Comparison Operators
| Operator | Description | Example |
|----------|-----------|---------|
| `=` | Equals | `('state', '=', 'draft')` |
| `!=` | Not equals | `('state', '!=', 'cancel')` |
| `>` | Greater than | `('amount', '>', 1000)` |
| `>=` | Greater or equal | `('date', '>=', '2025-01-01')` |
| `<` | Less than | `('amount', '<', 500)` |
| `<=` | Less or equal | `('date', '<=', '2025-12-31')` |
| `like` | SQL LIKE (case-sensitive) | `('name', 'like', 'Acme')` |
| `not like` | NOT LIKE | `('name', 'not like', 'test')` |
| `ilike` | Case-insensitive LIKE | `('name', 'ilike', 'acme')` |
| `not ilike` | Case-insensitive NOT LIKE | `('email', 'not ilike', '@test.com')` |
| `=like` | Exact LIKE pattern (use %) | `('name', '=like', 'SO%')` |
| `=ilike` | Case-insensitive exact pattern | `('name', '=ilike', 'so%')` |
| `in` | Value in list | `('state', 'in', ['draft', 'sent'])` |
| `not in` | Value not in list | `('state', 'not in', ['cancel'])` |
| `child_of` | Is child of (hierarchical) | `('partner_id', 'child_of', 1)` |
| `parent_of` | Is parent of (hierarchical) | `('partner_id', 'parent_of', 5)` |

## Important Notes
- `like`/`ilike`: Odoo wraps value with `%` automatically
- `=like`/`=ilike`: No auto-wrapping, use `%` explicitly
- `in`/`not in`: Value MUST be a list
- `=` with `False`: matches empty/null/false fields
- `!=` with `False`: matches fields that have a value

## Dot Notation (Relational Traversal)
```
('partner_id.name', 'ilike', 'acme')
('partner_id.country_id.code', '=', 'PT')
('order_line.product_id.name', 'ilike', 'widget')
```

## Date/Datetime Values (always strings, UTC)
```
('date_order', '>=', '2025-01-01')
('create_date', '>=', '2025-01-01 00:00:00')
```

## Logical Operators (Polish Notation)
```python
# OR:
['|', ('state', '=', 'draft'), ('state', '=', 'sent')]

# NOT:
['!', ('active', '=', False)]

# Complex: (state=draft OR state=sent) AND amount >= 1000
['&', '|', ('state', '=', 'draft'), ('state', '=', 'sent'), ('amount', '>=', 1000)]
```

## One2many/Many2many Command Tuples (for create/write)
| Command | Format | Description |
|---------|--------|-------------|
| CREATE | `(0, 0, {values})` | Create new related record |
| UPDATE | `(1, id, {values})` | Update existing related record |
| DELETE | `(2, id, 0)` | Delete related record |
| UNLINK | `(3, id, 0)` | Remove relationship (keep record) |
| LINK | `(4, id, 0)` | Link existing record |
| UNLINK ALL | `(5, 0, 0)` | Remove all (Many2many only) |
| REPLACE | `(6, 0, [ids])` | Replace all with given IDs |

## Common Patterns
```python
# All records: []
# Single condition: [('state', '=', 'draft')]
# Multiple AND: [('state', '=', 'draft'), ('partner_id', '=', 42)]
# OR: ['|', ('state', '=', 'draft'), ('state', '=', 'sent')]
# Contains: [('name', 'ilike', 'acme')]
# Starts with: [('name', '=ilike', 'SO%')]
# Date range: [('date', '>=', '2025-02-01'), ('date', '<=', '2025-02-28')]
# Relational: [('partner_id.country_id.code', '=', 'PT')]
# Has a tag: [('tag_ids', 'in', [5])]
# Not cancelled: [('state', '!=', 'cancel')]
```
"""


class PromptContext:
    """Dependencies for prompt generation."""

    def __init__(
        self,
        registry: ModelRegistry | None = None,
        server_version: str = "",
        server_edition: str = "",
        url: str = "",
        database: str = "",
        username: str = "",
        uid: int = 0,
        toolsets: list[dict[str, Any]] | None = None,
    ) -> None:
        self.registry = registry
        self.server_version = server_version
        self.server_edition = server_edition
        self.url = url
        self.database = database
        self.username = username
        self.uid = uid
        self.toolsets = toolsets or []


class PromptProvider:
    """Provides MCP prompts for the Odoo MCP server."""

    def __init__(self, context: PromptContext) -> None:
        self._ctx = context

    def get_prompt_definitions(self) -> list[dict[str, Any]]:
        """Return all prompt definitions for MCP registration."""
        return [
            {
                "name": "odoo_overview",
                "description": "Get an overview of the connected Odoo instance, available tools, and how to use them",
            },
            {
                "name": "odoo_domain_help",
                "description": "Reference guide for Odoo domain filter syntax",
            },
            {
                "name": "odoo_model_guide",
                "description": "Get a guide for working with a specific Odoo model",
                "arguments": [
                    {
                        "name": "model_name",
                        "description": "The Odoo model name (e.g., 'sale.order')",
                        "required": True,
                    }
                ],
            },
            {
                "name": "odoo_create_record",
                "description": "Get guidance for creating a record on a specific model",
                "arguments": [
                    {
                        "name": "model_name",
                        "description": "The Odoo model name",
                        "required": True,
                    }
                ],
            },
            {
                "name": "odoo_search_help",
                "description": "Get help constructing a search query for a model",
                "arguments": [
                    {
                        "name": "model_name",
                        "description": "The Odoo model name",
                        "required": True,
                    },
                    {
                        "name": "query",
                        "description": "What you're looking for (natural language)",
                        "required": True,
                    },
                ],
            },
        ]

    async def get_prompt(
        self, name: str, arguments: dict[str, str] | None = None
    ) -> list[dict[str, Any]]:
        """Generate prompt messages for a given prompt name."""
        arguments = arguments or {}

        if name == "odoo_overview":
            return self._prompt_overview()
        elif name == "odoo_domain_help":
            return self._prompt_domain_help()
        elif name == "odoo_model_guide":
            model_name = arguments.get("model_name", "")
            return self._prompt_model_guide(model_name)
        elif name == "odoo_create_record":
            model_name = arguments.get("model_name", "")
            return self._prompt_create_record(model_name)
        elif name == "odoo_search_help":
            model_name = arguments.get("model_name", "")
            query = arguments.get("query", "")
            return self._prompt_search_help(model_name, query)
        else:
            return [{"role": "user", "content": {"type": "text", "text": f"Unknown prompt: {name}"}}]

    # -- REQ-06-17: odoo_overview --

    def _prompt_overview(self) -> list[dict[str, Any]]:
        toolset_names = [t.get("name", "?") for t in self._ctx.toolsets]
        tool_count = sum(len(t.get("tools", [])) for t in self._ctx.toolsets)

        model_list = ""
        if self._ctx.registry:
            models = self._ctx.registry.list_models()
            model_list = ", ".join(m.model for m in models[:20])

        text = f"""\
You are connected to an Odoo {self._ctx.server_version} ({self._ctx.server_edition}) instance at {self._ctx.url}.
Database: {self._ctx.database}
User: {self._ctx.username} (uid: {self._ctx.uid})

Available toolsets: {', '.join(toolset_names) if toolset_names else 'none'}
Total tools: {tool_count}

Key models available: {model_list or 'use odoo_core_list_models to discover'}

To get started:
- Use odoo_core_search_read to search for records
- Use odoo_core_fields_get to understand a model's structure
- Use workflow tools (e.g., odoo_sales_create_order) for business operations
- Use odoo_core_list_models to discover available models"""

        return [{"role": "user", "content": {"type": "text", "text": text}}]

    # -- REQ-06-18: odoo_domain_help --

    def _prompt_domain_help(self) -> list[dict[str, Any]]:
        return [{"role": "user", "content": {"type": "text", "text": DOMAIN_HELP_TEXT}}]

    # -- REQ-06-19: odoo_model_guide --

    def _prompt_model_guide(self, model_name: str) -> list[dict[str, Any]]:
        reg = self._ctx.registry
        if reg is None:
            return [{"role": "user", "content": {"type": "text", "text": "Registry not available."}}]

        model = reg.get_model(model_name)
        if model is None:
            return [{"role": "user", "content": {"type": "text", "text": f"Model '{model_name}' not found in registry."}}]

        sections = [f"# Guide: {model.model} ({model.name})"]
        if model.description:
            sections.append(f"\n{model.description}")

        # Fields grouped by required / key / other
        required = [f for f in model.fields.values() if f.required]
        relational = [f for f in model.fields.values() if f.type in ("many2one", "one2many", "many2many") and not f.required]
        other = [f for f in model.fields.values() if not f.required and f.type not in ("many2one", "one2many", "many2many")]

        sections.append("\n## Fields")
        if required:
            sections.append("\n### Required Fields")
            for f in required:
                sections.append(f"- **{f.name}** ({f.type}): {f.label}" + (f" - {f.help}" if f.help else ""))
        if relational:
            sections.append("\n### Relational Fields")
            for f in relational:
                rel = f" -> {f.relation}" if f.relation else ""
                sections.append(f"- **{f.name}** ({f.type}{rel}): {f.label}")
        if other:
            sections.append(f"\n### Other Fields ({len(other)} fields)")
            for f in other[:15]:
                sections.append(f"- **{f.name}** ({f.type}): {f.label}")
            if len(other) > 15:
                sections.append(f"- ... and {len(other) - 15} more")

        # States
        if model.states:
            sections.append("\n## States")
            for val, label in model.states:
                sections.append(f"- `{val}`: {label}")

        # Common operations
        sections.append("\n## Common Operations")
        sections.append(f'- Search: `odoo_core_search_read` with model="{model.model}"')
        sections.append(f'- Create: `odoo_core_create` with model="{model.model}"')
        sections.append(f'- Read fields: `odoo_core_fields_get` with model="{model.model}"')

        # Methods
        if model.methods:
            sections.append("\n## Available Methods")
            for m in model.methods.values():
                desc = f" - {m.description}" if m.description else ""
                sections.append(f"- `{m.name}`{desc}")

        # Related models
        rel_models = set()
        for f in model.fields.values():
            if f.relation:
                rel_models.add(f.relation)
        if rel_models:
            sections.append("\n## Related Models")
            for rm in sorted(rel_models):
                sections.append(f"- {rm}")

        # Tips
        sections.append("\n## Tips")
        if model.has_chatter:
            sections.append("- This model has chatter (mail.thread) - you can post messages and log notes")
        if model.states:
            sections.append("- Use state-specific filters for efficient searching")
        sections.append(f"- Use `odoo://model/{model.model}/fields` resource for full field details")

        text = "\n".join(sections)
        return [{"role": "user", "content": {"type": "text", "text": text}}]

    # -- REQ-06-20: odoo_create_record --

    def _prompt_create_record(self, model_name: str) -> list[dict[str, Any]]:
        reg = self._ctx.registry
        if reg is None:
            return [{"role": "user", "content": {"type": "text", "text": "Registry not available."}}]

        model = reg.get_model(model_name)
        if model is None:
            return [{"role": "user", "content": {"type": "text", "text": f"Model '{model_name}' not found."}}]

        sections = [f"# Creating a {model.name} ({model.model}) record"]

        # Required fields
        required = [f for f in model.fields.values() if f.required and f.name != "id"]
        sections.append("\n## Required Fields")
        if required:
            for f in required:
                type_info = FIELD_TYPE_MAP.get(f.type, {})
                json_type = type_info.get("json", f.type)
                line = f"- **{f.name}** ({f.type} -> {json_type}): {f.label}"
                if f.help:
                    line += f"\n  - Help: {f.help}"
                if f.relation:
                    line += f"\n  - Relation: search `{f.relation}` first to get the ID"
                if f.selection:
                    vals = ", ".join(f'`{v}`' for v, _ in f.selection)
                    line += f"\n  - Values: {vals}"
                if f.default is not None:
                    line += f"\n  - Default: `{f.default}`"
                sections.append(line)
        else:
            sections.append("No required fields (besides auto-generated ones).")

        # Common optional fields
        optional = [
            f for f in model.fields.values()
            if not f.required
            and f.name not in ("id", "create_uid", "create_date", "write_uid", "write_date", "__last_update")
            and not f.compute
            and f.store
        ]
        if optional:
            sections.append(f"\n## Common Optional Fields ({len(optional)} total)")
            for f in optional[:10]:
                sections.append(f"- **{f.name}** ({f.type}): {f.label}")
            if len(optional) > 10:
                sections.append(f"- ... and {len(optional) - 10} more")

        # Relational field resolution guidance
        rel_fields = [f for f in required if f.relation]
        if rel_fields:
            sections.append("\n## Relational Field Resolution")
            for f in rel_fields:
                sections.append(
                    f"- For `{f.name}`, first search `{f.relation}` using "
                    f"`odoo_core_search_read` to find the correct ID"
                )

        # Example
        sections.append("\n## Example")
        example_vals: dict[str, str] = {}
        for f in required:
            if f.type == "char":
                example_vals[f.name] = '"value"'
            elif f.type in ("integer", "many2one"):
                example_vals[f.name] = "1"
            elif f.type == "float":
                example_vals[f.name] = "0.0"
            elif f.type == "boolean":
                example_vals[f.name] = "true"
            elif f.type == "selection" and f.selection:
                example_vals[f.name] = f'"{f.selection[0][0]}"'
            else:
                example_vals[f.name] = '"..."'
        vals_str = ", ".join(f'"{k}": {v}' for k, v in example_vals.items())
        sections.append(f'```json\n{{"model": "{model.model}", "values": {{{vals_str}}}}}\n```')

        text = "\n".join(sections)
        return [{"role": "user", "content": {"type": "text", "text": text}}]

    # -- REQ-06-21: odoo_search_help --

    def _prompt_search_help(self, model_name: str, query: str) -> list[dict[str, Any]]:
        reg = self._ctx.registry
        if reg is None:
            return [{"role": "user", "content": {"type": "text", "text": "Registry not available."}}]

        model = reg.get_model(model_name)
        if model is None:
            return [{"role": "user", "content": {"type": "text", "text": f"Model '{model_name}' not found."}}]

        sections = [f"# Search Help: {model.model}"]
        sections.append(f"\nQuery: \"{query}\"")

        # Suggest searchable fields
        searchable = [
            f for f in model.fields.values()
            if f.store and f.type in ("char", "text", "selection", "many2one", "integer", "float", "date", "datetime", "boolean")
        ]

        sections.append("\n## Searchable Fields")
        name_fields = [f for f in searchable if f.type in ("char", "text")]
        if name_fields:
            sections.append("### Text fields (use ilike for search):")
            for f in name_fields[:10]:
                sections.append(f"- `{f.name}` ({f.label})")

        state_field = model.fields.get("state")
        if state_field and state_field.selection:
            sections.append("\n### State values:")
            for val, label in state_field.selection:
                sections.append(f"- `{val}`: {label}")

        # Suggest a domain based on the query
        sections.append("\n## Suggested Approach")
        sections.append(f"Based on your query \"{query}\", consider:")
        sections.append(f'- Text search: `[(\'name\', \'ilike\', \'{query}\')]`')
        if state_field:
            sections.append(f"- State filter: `[('state', '=', '<state_value>')]`")

        # Recommended fields to return
        key_fields = ["id", "name", "display_name"]
        if state_field:
            key_fields.append("state")
        extra = [f.name for f in searchable if f.name not in key_fields][:5]
        key_fields.extend(extra)

        sections.append(f"\n## Recommended Fields")
        sections.append(f"`{key_fields}`")

        # Tool call
        sections.append("\n## Tool Call")
        sections.append(f"""\
```json
{{
  "tool": "odoo_core_search_read",
  "arguments": {{
    "model": "{model.model}",
    "domain": [["name", "ilike", "{query}"]],
    "fields": {key_fields},
    "limit": 20
  }}
}}
```""")

        text = "\n".join(sections)
        return [{"role": "user", "content": {"type": "text", "text": text}}]
