"""Tests for the AST-based static registry generator (Task 3.4)."""

from __future__ import annotations

import json
import textwrap
import tempfile
from pathlib import Path

import pytest

from odoo_mcp.registry.generator import (
    parse_addon_file,
    parse_addons_path,
    build_registry,
    main,
)


def _write_addon(tmp_path: Path, addon_name: str, model_code: str) -> Path:
    """Create a minimal addon structure with the given model code."""
    addon_dir = tmp_path / "addons" / addon_name
    addon_dir.mkdir(parents=True)
    (addon_dir / "__manifest__.py").write_text("{'name': '%s'}" % addon_name)
    (addon_dir / "__init__.py").write_text("")
    models_dir = addon_dir / "models"
    models_dir.mkdir()
    (models_dir / "__init__.py").write_text("")
    (models_dir / "models.py").write_text(textwrap.dedent(model_code))
    return tmp_path / "addons"


class TestParseAddonFile:
    def test_simple_model(self, tmp_path):
        code = '''\
        from odoo import models, fields

        class SaleOrder(models.Model):
            _name = 'sale.order'
            _description = 'Sales Order'

            name = fields.Char(string='Order Reference', required=True, readonly=True)
            partner_id = fields.Many2one('res.partner', string='Customer', required=True)
            state = fields.Selection([
                ('draft', 'Quotation'),
                ('sale', 'Sales Order'),
                ('cancel', 'Cancelled'),
            ], string='Status')
        '''
        p = tmp_path / "model.py"
        p.write_text(textwrap.dedent(code))
        result = parse_addon_file(p)

        assert "sale.order" in result
        m = result["sale.order"]
        assert m["name"] == "Sales Order"
        assert "name" in m["fields"]
        assert m["fields"]["name"]["type"] == "char"
        assert m["fields"]["name"]["required"] is True
        assert m["fields"]["partner_id"]["type"] == "many2one"
        assert m["fields"]["partner_id"]["relation"] == "res.partner"
        assert m["fields"]["state"]["type"] == "selection"
        assert len(m["fields"]["state"]["selection"]) == 3

    def test_inheritance_single(self, tmp_path):
        code = '''\
        from odoo import models, fields

        class SaleOrderExtend(models.Model):
            _inherit = 'sale.order'

            custom_field = fields.Char(string='Custom')
        '''
        p = tmp_path / "ext.py"
        p.write_text(textwrap.dedent(code))
        result = parse_addon_file(p)
        assert "sale.order" in result
        assert "custom_field" in result["sale.order"]["fields"]

    def test_inheritance_multiple(self, tmp_path):
        code = '''\
        from odoo import models, fields

        class MyModel(models.Model):
            _name = 'my.model'
            _inherit = ['mail.thread', 'mail.activity.mixin']
            _description = 'My Model'

            name = fields.Char(string='Name')
        '''
        p = tmp_path / "my.py"
        p.write_text(textwrap.dedent(code))
        result = parse_addon_file(p)
        assert "my.model" in result
        assert "mail.thread" in result["my.model"]["parent_models"]
        assert result["my.model"]["has_chatter"] is True

    def test_method_extraction(self, tmp_path):
        code = '''\
        from odoo import models, api

        class SaleOrder(models.Model):
            _inherit = 'sale.order'

            def action_confirm(self):
                """Confirm the quotation into a sales order."""
                pass

            def button_custom(self):
                """Custom button action."""
                pass

            def _private_method(self):
                """Should not be extracted."""
                pass
        '''
        p = tmp_path / "methods.py"
        p.write_text(textwrap.dedent(code))
        result = parse_addon_file(p)
        m = result["sale.order"]
        assert "action_confirm" in m["methods"]
        assert m["methods"]["action_confirm"]["description"] == "Confirm the quotation into a sales order."
        assert "button_custom" in m["methods"]
        assert "_private_method" not in m["methods"]

    def test_transient_model(self, tmp_path):
        code = '''\
        from odoo import models, fields

        class SaleOrderWizard(models.TransientModel):
            _name = 'sale.order.wizard'
            _description = 'Sale Order Wizard'

            name = fields.Char()
        '''
        p = tmp_path / "wiz.py"
        p.write_text(textwrap.dedent(code))
        result = parse_addon_file(p)
        assert result["sale.order.wizard"]["transient"] is True

    def test_delegated_inheritance(self, tmp_path):
        code = '''\
        from odoo import models, fields

        class ProductProduct(models.Model):
            _name = 'product.product'
            _inherits = {'product.template': 'product_tmpl_id'}

            product_tmpl_id = fields.Many2one('product.template', required=True)
        '''
        p = tmp_path / "prod.py"
        p.write_text(textwrap.dedent(code))
        result = parse_addon_file(p)
        assert "product.product" in result

    def test_invalid_file(self, tmp_path):
        p = tmp_path / "bad.py"
        p.write_text("this is not valid python {{{")
        result = parse_addon_file(p)
        assert result == {}


class TestBuildRegistry:
    def test_full_addon(self, tmp_path):
        code = '''\
        from odoo import models, fields

        class ResPartner(models.Model):
            _name = 'res.partner'
            _description = 'Contact'

            name = fields.Char(string='Name', required=True)
            email = fields.Char(string='Email')
            phone = fields.Char(string='Phone')
        '''
        addons_path = _write_addon(tmp_path, "base", code)
        registry = build_registry([str(addons_path)], version="17.0")
        assert registry.version == "17.0"
        assert registry.build_mode == "static"
        assert "res.partner" in registry.models
        assert registry.model_count == 1
        assert registry.field_count == 3

    def test_model_filter(self, tmp_path):
        code = '''\
        from odoo import models, fields

        class A(models.Model):
            _name = 'mod.a'
            name = fields.Char()

        class B(models.Model):
            _name = 'mod.b'
            name = fields.Char()
        '''
        addons_path = _write_addon(tmp_path, "mymod", code)
        registry = build_registry([str(addons_path)], model_filter=["mod.a"])
        assert "mod.a" in registry.models
        assert "mod.b" not in registry.models

    def test_inheritance_merge(self, tmp_path):
        code1 = '''\
        from odoo import models, fields

        class SaleOrder(models.Model):
            _name = 'sale.order'
            _description = 'Sales Order'
            name = fields.Char(string='Name', required=True)
        '''
        code2 = '''\
        from odoo import models, fields

        class SaleOrderExt(models.Model):
            _inherit = 'sale.order'
            custom = fields.Char(string='Custom Field')
        '''
        addon_dir = tmp_path / "addons" / "sale"
        addon_dir.mkdir(parents=True)
        (addon_dir / "__manifest__.py").write_text("{'name': 'sale'}")
        (addon_dir / "__init__.py").write_text("")
        models_dir = addon_dir / "models"
        models_dir.mkdir()
        (models_dir / "__init__.py").write_text("")
        (models_dir / "sale_order.py").write_text(textwrap.dedent(code1))
        (models_dir / "sale_order_ext.py").write_text(textwrap.dedent(code2))

        registry = build_registry([str(tmp_path / "addons")])
        assert "sale.order" in registry.models
        m = registry.models["sale.order"]
        assert "name" in m.fields
        assert "custom" in m.fields


class TestCLI:
    def test_main_generates_file(self, tmp_path):
        code = '''\
        from odoo import models, fields

        class ResPartner(models.Model):
            _name = 'res.partner'
            _description = 'Contact'
            name = fields.Char(string='Name', required=True)
        '''
        addons_path = _write_addon(tmp_path, "base", code)
        output = tmp_path / "output.json"

        main([
            "--addons-path", str(addons_path),
            "--output", str(output),
            "--version", "17.0",
        ])

        assert output.exists()
        with open(output) as f:
            data = json.load(f)
        assert data["version"] == "17.0"
        assert data["source"] == "ast_parse"
        assert "res.partner" in data["models"]
