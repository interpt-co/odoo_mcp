#!/usr/bin/env python3
"""Runtime introspection script for Odoo shell.

REQ-07-06: Standalone script to be run inside an Odoo shell to generate
registry data from a live instance.

Usage:
    odoo shell -d mydb < scripts/runtime_introspect.py
    # or
    odoo-bin shell -d mydb --no-http -c odoo.conf < scripts/runtime_introspect.py

Output is JSON delimited by markers for easy parsing.
"""

import json
import inspect
from datetime import datetime

# REQ-07-07: Default target models
DEFAULT_MODELS = [
    'res.partner', 'res.users', 'res.company',
    'sale.order', 'sale.order.line',
    'purchase.order', 'purchase.order.line',
    'account.move', 'account.move.line',
    'stock.picking', 'stock.move', 'stock.move.line',
    'stock.quant', 'stock.warehouse', 'stock.location',
    'product.template', 'product.product', 'product.category',
    'crm.lead', 'crm.stage',
    'helpdesk.ticket', 'helpdesk.stage', 'helpdesk.team',
    'project.project', 'project.task', 'project.milestone',
    'hr.employee', 'hr.department', 'hr.leave',
    'calendar.event',
    'mail.message', 'mail.activity',
    'ir.attachment',
]

START_MARKER = '=== RUNTIME_REGISTRY_JSON_START ==='
END_MARKER = '=== RUNTIME_REGISTRY_JSON_END ==='


def introspect_model(env, model_name):
    """Introspect a single model and return its metadata."""
    try:
        Model = env[model_name]
    except KeyError:
        return None

    # Fields
    fields = {}
    for fname, field_obj in Model._fields.items():
        fdata = {
            'label': field_obj.string or fname,
            'type': field_obj.type,
            'required': field_obj.required,
            'readonly': field_obj.readonly,
            'store': field_obj.store,
            'help': field_obj.help or None,
            'relation': getattr(field_obj, 'comodel_name', None),
            'compute': bool(field_obj.compute),
        }
        if field_obj.type == 'selection':
            sel = field_obj.selection
            if callable(sel):
                try:
                    sel = sel(Model)
                except Exception:
                    sel = []
            fdata['selection'] = [[str(v), str(l)] for v, l in (sel or [])]
        if hasattr(field_obj, 'depends') and field_obj.depends:
            fdata['depends'] = list(field_obj.depends)
        if hasattr(field_obj, 'groups') and field_obj.groups:
            fdata['groups'] = field_obj.groups
        fields[fname] = fdata

    # Methods (action_* and button_*)
    methods = {}
    for attr_name in dir(Model):
        if attr_name.startswith('action_') or attr_name.startswith('button_'):
            try:
                attr = getattr(type(Model), attr_name, None)
                if attr is None or not callable(attr):
                    continue
                doc = ''
                if hasattr(attr, '__doc__') and attr.__doc__:
                    doc = attr.__doc__.strip().split('\n')[0]
                methods[attr_name] = {
                    'description': doc,
                    'accepts_kwargs': True,  # Conservative default
                }
            except Exception:
                pass

    # States
    states = None
    if 'state' in fields and fields['state'].get('selection'):
        states = fields['state']['selection']

    # Parent models
    parent_models = list(getattr(Model, '_inherit', []) or [])
    if isinstance(parent_models, str):
        parent_models = [parent_models]

    has_chatter = 'message_ids' in fields

    return {
        'model': model_name,
        'name': Model._description or model_name,
        'description': Model._description or None,
        'transient': getattr(Model, '_transient', False),
        'fields': fields,
        'methods': methods,
        'states': states,
        'parent_models': parent_models,
        'has_chatter': has_chatter,
    }


def main():
    """Run introspection and output JSON."""
    # 'env' should be available in Odoo shell context
    try:
        env  # noqa: F821
    except NameError:
        print("ERROR: This script must be run inside an Odoo shell.")
        print("Usage: odoo shell -d mydb < scripts/runtime_introspect.py")
        return

    models = {}
    errors = []

    for model_name in DEFAULT_MODELS:
        try:
            result = introspect_model(env, model_name)  # noqa: F821
            if result:
                models[model_name] = result
        except Exception as exc:
            errors.append({'model': model_name, 'error': str(exc)})

    output = {
        'version': env['ir.module.module'].sudo().search(  # noqa: F821
            [('name', '=', 'base')], limit=1
        ).latest_version or '',
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'source': 'runtime_introspect',
        'models': models,
        'errors': errors,
        'model_count': len(models),
    }

    print(START_MARKER)
    print(json.dumps(output, indent=2, ensure_ascii=False))
    print(END_MARKER)


main()
