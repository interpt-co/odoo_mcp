"""AST-based static registry generator CLI tool.

Implements REQ-07-02 through REQ-07-06.
Parses Odoo addon source code to extract model/field/method metadata.
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from odoo_mcp.registry.model_registry import (
    FieldInfo,
    MethodInfo,
    ModelInfo,
    Registry,
    NO_KWARGS_METHODS,
)

logger = logging.getLogger(__name__)

GENERATOR_VERSION = "0.1.0"

# Odoo field class names -> type strings
FIELD_CLASS_MAP: dict[str, str] = {
    "Char": "char", "Text": "text", "Html": "html",
    "Integer": "integer", "Float": "float", "Monetary": "monetary",
    "Boolean": "boolean", "Date": "date", "Datetime": "datetime",
    "Binary": "binary", "Selection": "selection",
    "Many2one": "many2one", "One2many": "one2many", "Many2many": "many2many",
    "Reference": "reference", "Properties": "properties",
}


def _get_str_value(node: ast.expr) -> str | None:
    """Extract a string value from an AST node."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _get_bool_value(node: ast.expr) -> bool | None:
    """Extract a boolean value from an AST node."""
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.NameConstant):  # Python 3.7 compat
        if isinstance(node.value, bool):
            return node.value
    return None


def _get_list_value(node: ast.expr) -> list[str] | None:
    """Extract a list of strings from an AST node."""
    if isinstance(node, ast.List):
        result = []
        for elt in node.elts:
            s = _get_str_value(elt)
            if s is not None:
                result.append(s)
        return result
    return None


def _get_selection_value(node: ast.expr) -> list[tuple[str, str]] | None:
    """Extract selection values from an AST node."""
    if isinstance(node, ast.List):
        result: list[tuple[str, str]] = []
        for elt in node.elts:
            if isinstance(elt, ast.Tuple) and len(elt.elts) == 2:
                val = _get_str_value(elt.elts[0])
                label = _get_str_value(elt.elts[1])
                if val is not None and label is not None:
                    result.append((val, label))
        return result if result else None
    return None


def _parse_field_call(node: ast.Call) -> dict[str, Any] | None:
    """Parse a fields.Xxx(...) call to extract field metadata."""
    if not isinstance(node.func, ast.Attribute):
        return None
    attr = node.func
    if not isinstance(attr.value, ast.Name) or attr.value.id != "fields":
        return None

    field_type = FIELD_CLASS_MAP.get(attr.attr)
    if field_type is None:
        return None

    info: dict[str, Any] = {"type": field_type}

    # Parse keyword arguments
    for kw in node.keywords:
        if kw.arg == "string":
            info["label"] = _get_str_value(kw.value) or ""
        elif kw.arg == "required":
            val = _get_bool_value(kw.value)
            if val is not None:
                info["required"] = val
        elif kw.arg == "readonly":
            val = _get_bool_value(kw.value)
            if val is not None:
                info["readonly"] = val
        elif kw.arg == "store":
            val = _get_bool_value(kw.value)
            if val is not None:
                info["store"] = val
        elif kw.arg == "help":
            info["help"] = _get_str_value(kw.value)
        elif kw.arg == "selection":
            info["selection"] = _get_selection_value(kw.value)
        elif kw.arg == "comodel_name":
            info["relation"] = _get_str_value(kw.value)
        elif kw.arg == "compute":
            info["compute"] = True
        elif kw.arg == "related":
            info["compute"] = True
        elif kw.arg == "groups":
            info["groups"] = _get_str_value(kw.value)
        elif kw.arg == "depends":
            info["depends"] = _get_list_value(kw.value)

    # For relational fields, first positional arg is comodel_name
    if field_type in ("many2one", "one2many", "many2many") and not info.get("relation"):
        if node.args:
            info["relation"] = _get_str_value(node.args[0])

    # For Selection, first positional arg can be selection list
    if field_type == "selection" and not info.get("selection"):
        if node.args:
            info["selection"] = _get_selection_value(node.args[0])

    # First positional arg for regular fields can be the string/label
    if field_type not in ("many2one", "one2many", "many2many", "selection"):
        if node.args and not info.get("label"):
            info["label"] = _get_str_value(node.args[0]) or ""

    return info


def _extract_docstring_first_line(node: ast.FunctionDef) -> str:
    """Extract the first line of a method's docstring."""
    if (
        node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    ):
        lines = node.body[0].value.value.strip().split("\n")
        return lines[0].strip()
    return ""


def parse_addon_file(filepath: Path) -> dict[str, dict[str, Any]]:
    """Parse a single Python file for Odoo model definitions.

    Returns a dict of model_name -> {name, description, transient, fields, methods,
    inherit, inherits, parent_models}.
    """
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError, OSError) as exc:
        logger.debug("Skipping %s: %s", filepath, exc)
        return {}

    models: dict[str, dict[str, Any]] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        model_name: str | None = None
        inherit: str | list[str] | None = None
        inherits: dict[str, str] | None = None
        description: str | None = None
        is_transient = False
        fields: dict[str, dict[str, Any]] = {}
        methods: dict[str, dict[str, Any]] = {}

        # Check base classes for TransientModel
        for base in node.bases:
            if isinstance(base, ast.Attribute):
                if base.attr == "TransientModel":
                    is_transient = True
            elif isinstance(base, ast.Name):
                if base.id == "TransientModel":
                    is_transient = True

        # Walk class body for assignments and methods
        for item in node.body:
            # _name / _inherit / _inherits / _description assignments
            if isinstance(item, ast.Assign) and len(item.targets) == 1:
                target = item.targets[0]
                if isinstance(target, ast.Name):
                    if target.id == "_name":
                        model_name = _get_str_value(item.value)
                    elif target.id == "_inherit":
                        s = _get_str_value(item.value)
                        if s:
                            inherit = s
                        else:
                            inherit = _get_list_value(item.value)
                    elif target.id == "_inherits":
                        if isinstance(item.value, ast.Dict):
                            inherits = {}
                            for k, v in zip(item.value.keys, item.value.values):
                                ks = _get_str_value(k) if k else None
                                vs = _get_str_value(v) if v else None
                                if ks and vs:
                                    inherits[ks] = vs
                    elif target.id == "_description":
                        description = _get_str_value(item.value)

                    # Field assignments: field_name = fields.Char(...)
                    elif isinstance(item.value, ast.Call):
                        field_info = _parse_field_call(item.value)
                        if field_info is not None:
                            field_info.setdefault("label", target.id)
                            fields[target.id] = field_info

            # Field assignments not caught above
            if isinstance(item, ast.Assign) and len(item.targets) == 1:
                target = item.targets[0]
                if (
                    isinstance(target, ast.Name)
                    and isinstance(item.value, ast.Call)
                    and target.id not in fields
                    and not target.id.startswith("_")
                ):
                    field_info = _parse_field_call(item.value)
                    if field_info is not None:
                        field_info.setdefault("label", target.id)
                        fields[target.id] = field_info

            # Method definitions
            if isinstance(item, ast.FunctionDef):
                if item.name.startswith("action_") or item.name.startswith("button_"):
                    doc = _extract_docstring_first_line(item)
                    # Check decorators
                    decorator = None
                    for dec in item.decorator_list:
                        if isinstance(dec, ast.Attribute):
                            if isinstance(dec.value, ast.Name) and dec.value.id == "api":
                                decorator = f"api.{dec.attr}"
                    methods[item.name] = {
                        "description": doc,
                        "accepts_kwargs": item.name not in NO_KWARGS_METHODS,
                        "decorator": decorator,
                    }

        # Determine effective model name
        effective_name = model_name
        if effective_name is None and inherit:
            if isinstance(inherit, str):
                effective_name = inherit
            elif isinstance(inherit, list) and len(inherit) == 1:
                effective_name = inherit[0]

        if effective_name is None:
            continue

        parent_models: list[str] = []
        if inherit:
            if isinstance(inherit, str):
                parent_models = [inherit]
            elif isinstance(inherit, list):
                parent_models = inherit

        has_chatter = "mail.thread" in parent_models

        model_data: dict[str, Any] = {
            "name": description or effective_name,
            "description": description,
            "transient": is_transient,
            "fields": fields,
            "methods": methods,
            "inherit": inherit,
            "inherits": inherits,
            "parent_models": parent_models,
            "has_chatter": has_chatter,
        }
        models[effective_name] = model_data

    return models


def parse_addons_path(addons_paths: list[str], model_filter: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """Parse all addon directories and merge model definitions.

    REQ-07-05: Handles inheritance resolution.
    """
    all_models: dict[str, dict[str, Any]] = {}

    for addons_path in addons_paths:
        path = Path(addons_path)
        if not path.is_dir():
            logger.warning("Addons path not found: %s", path)
            continue

        # Each subdirectory is an addon module
        for addon_dir in sorted(path.iterdir()):
            if not addon_dir.is_dir():
                continue
            manifest = addon_dir / "__manifest__.py"
            if not manifest.exists():
                manifest = addon_dir / "__openerp__.py"
                if not manifest.exists():
                    continue

            # Parse all .py files in the addon
            for py_file in sorted(addon_dir.rglob("*.py")):
                if py_file.name.startswith("test"):
                    continue
                file_models = parse_addon_file(py_file)
                for model_name, model_data in file_models.items():
                    if model_filter and model_name not in model_filter:
                        continue
                    _merge_model(all_models, model_name, model_data)

    return all_models


def _merge_model(
    all_models: dict[str, dict[str, Any]],
    model_name: str,
    new_data: dict[str, Any],
) -> None:
    """Merge a model definition into the collection, handling inheritance."""
    if model_name not in all_models:
        all_models[model_name] = new_data
        return

    existing = all_models[model_name]
    # Merge fields
    existing["fields"].update(new_data["fields"])
    # Merge methods
    existing["methods"].update(new_data["methods"])
    # Update parent models
    for p in new_data.get("parent_models", []):
        if p not in existing.get("parent_models", []):
            existing.setdefault("parent_models", []).append(p)
    # Update chatter
    if new_data.get("has_chatter"):
        existing["has_chatter"] = True
    # Update description if provided
    if new_data.get("description") and not existing.get("description"):
        existing["description"] = new_data["description"]
        existing["name"] = new_data["name"]


def build_registry(
    addons_paths: list[str],
    version: str = "",
    model_filter: list[str] | None = None,
) -> Registry:
    """Build a Registry from addon source code."""
    raw_models = parse_addons_path(addons_paths, model_filter)

    models: dict[str, ModelInfo] = {}
    for model_name, data in raw_models.items():
        fields: dict[str, FieldInfo] = {}
        for fname, fdata in data.get("fields", {}).items():
            fields[fname] = FieldInfo(
                name=fname,
                label=fdata.get("label", fname),
                type=fdata.get("type", "char"),
                required=fdata.get("required", False),
                readonly=fdata.get("readonly", False),
                store=fdata.get("store", True),
                help=fdata.get("help"),
                relation=fdata.get("relation"),
                selection=fdata.get("selection"),
                default=fdata.get("default"),
                groups=fdata.get("groups"),
                compute=fdata.get("compute", False),
                depends=fdata.get("depends"),
            )

        methods: dict[str, MethodInfo] = {}
        for mname, mdata in data.get("methods", {}).items():
            methods[mname] = MethodInfo(
                name=mname,
                description=mdata.get("description", ""),
                accepts_kwargs=mdata.get("accepts_kwargs", True),
                decorator=mdata.get("decorator"),
            )

        states = None
        state_field = fields.get("state")
        if state_field and state_field.selection:
            states = state_field.selection

        models[model_name] = ModelInfo(
            model=model_name,
            name=data.get("name", model_name),
            description=data.get("description"),
            transient=data.get("transient", False),
            fields=fields,
            methods=methods,
            states=states,
            parent_models=data.get("parent_models", []),
            has_chatter=data.get("has_chatter", False),
        )

    registry = Registry(
        models=models,
        version=version,
        build_mode="static",
        build_timestamp=datetime.now(timezone.utc).isoformat(),
    )
    registry.update_counts()
    return registry


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for odoo-mcp-registry."""
    parser = argparse.ArgumentParser(
        prog="odoo-mcp-registry",
        description="Generate a static model registry from Odoo addon source code",
    )
    parser.add_argument(
        "--addons-path",
        required=True,
        help="Comma-separated paths to Odoo addon directories",
    )
    parser.add_argument(
        "--output",
        default="odoo_mcp/registry/static_data.json",
        help="Output JSON file path",
    )
    parser.add_argument(
        "--models",
        default=None,
        help="Comma-separated model names to include (default: all)",
    )
    parser.add_argument(
        "--version",
        default="",
        help="Odoo version label",
    )

    args = parser.parse_args(argv)
    addons_paths = [p.strip() for p in args.addons_path.split(",")]
    model_filter = [m.strip() for m in args.models.split(",")] if args.models else None

    logging.basicConfig(level=logging.INFO)
    registry = build_registry(addons_paths, args.version, model_filter)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    data = registry.to_dict()
    data["generated_at"] = registry.build_timestamp
    data["generator_version"] = GENERATOR_VERSION
    data["source"] = "ast_parse"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(
        f"Generated registry: {registry.model_count} models, "
        f"{registry.field_count} fields -> {output_path}"
    )


if __name__ == "__main__":
    main()
