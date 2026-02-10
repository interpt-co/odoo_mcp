"""Tests for odoo_mcp.toolsets.formatting — response normalisation."""

import base64
import os

import pytest

from odoo_mcp.toolsets.formatting import (
    normalize_datetime,
    normalize_record,
    normalize_records,
    save_binary_to_file,
    strip_html,
)


# ---------------------------------------------------------------------------
# strip_html
# ---------------------------------------------------------------------------

class TestStripHtml:
    def test_empty(self):
        assert strip_html("") == ""
        assert strip_html(None) == ""

    def test_plain_text(self):
        assert strip_html("Hello world") == "Hello world"

    def test_basic_tags(self):
        assert strip_html("<p>Hello</p>") == "Hello"

    def test_br_tags(self):
        assert "Hello\nWorld" == strip_html("Hello<br>World")
        assert "Hello\nWorld" == strip_html("Hello<br/>World")
        assert "Hello\nWorld" == strip_html("Hello<BR />World")

    def test_paragraph_newlines(self):
        result = strip_html("<p>First</p><p>Second</p>")
        assert "First" in result
        assert "Second" in result

    def test_entities(self):
        assert strip_html("&amp; &lt; &gt;") == "& < >"
        assert strip_html("caf&eacute;") == "caf\u00e9"

    def test_nested_tags(self):
        assert strip_html("<div><b>Bold</b> text</div>") == "Bold text"

    def test_whitespace_cleanup(self):
        result = strip_html("<p>A</p>\n\n\n<p>B</p>")
        # Excessive newlines should be collapsed
        assert "\n\n\n" not in result


# ---------------------------------------------------------------------------
# normalize_datetime
# ---------------------------------------------------------------------------

class TestNormalizeDatetime:
    def test_standard_odoo_format(self):
        assert normalize_datetime("2025-02-09 14:30:00") == "2025-02-09T14:30:00Z"

    def test_already_iso(self):
        # Should not double-append Z
        assert normalize_datetime("2025-02-09T14:30:00Z") == "2025-02-09T14:30:00Z"

    def test_date_only(self):
        # Date-only strings should not be modified
        assert normalize_datetime("2025-02-09") == "2025-02-09"


# ---------------------------------------------------------------------------
# normalize_record
# ---------------------------------------------------------------------------

class TestNormalizeRecord:
    def test_many2one_tuple(self):
        record = {"partner_id": [42, "Acme Corp"]}
        result = normalize_record(record, {"partner_id": "many2one"})
        assert result["partner_id"] == {"id": 42, "name": "Acme Corp"}

    def test_many2one_false(self):
        record = {"partner_id": False}
        result = normalize_record(record, {"partner_id": "many2one"})
        assert result["partner_id"] is None

    def test_false_empty_string_field(self):
        record = {"name": False}
        result = normalize_record(record, {"name": "char"})
        assert result["name"] == ""

    def test_false_empty_text_field(self):
        record = {"description": False}
        result = normalize_record(record, {"description": "text"})
        assert result["description"] == ""

    def test_false_empty_date_field(self):
        record = {"date_order": False}
        result = normalize_record(record, {"date_order": "date"})
        assert result["date_order"] is None

    def test_false_empty_datetime_field(self):
        record = {"create_date": False}
        result = normalize_record(record, {"create_date": "datetime"})
        assert result["create_date"] is None

    def test_x2many_unchanged(self):
        record = {"tag_ids": [1, 2, 3]}
        result = normalize_record(record, {"tag_ids": "many2many"})
        assert result["tag_ids"] == [1, 2, 3]

    def test_datetime_normalisation(self):
        record = {"create_date": "2025-02-09 14:30:00"}
        result = normalize_record(record, {"create_date": "datetime"})
        assert result["create_date"] == "2025-02-09T14:30:00Z"

    def test_html_stripping(self):
        record = {"body": "<p>Hello <b>world</b></p>"}
        result = normalize_record(record, {"body": "html"})
        assert "<" not in result["body"]
        assert "Hello" in result["body"]

    def test_known_html_field_name(self):
        record = {"description": "<p>Test</p>"}
        result = normalize_record(record, {})  # no type info
        assert "<" not in result["description"]

    def test_binary_excluded_by_default(self):
        record = {"image": "base64data", "name": "Test"}
        result = normalize_record(record, {"image": "binary", "name": "char"})
        assert "image" not in result
        assert result["name"] == "Test"

    def test_binary_kept_when_requested(self):
        record = {"image": "base64data"}
        result = normalize_record(
            record,
            {"image": "binary"},
            requested_fields={"image"},
        )
        assert result["image"] == "base64data"

    def test_heuristic_many2one_detection(self):
        """Without field_types, detect [int, str] tuples as many2one."""
        record = {"partner_id": [1, "John"]}
        result = normalize_record(record, {})
        assert result["partner_id"] == {"id": 1, "name": "John"}

    def test_heuristic_datetime_detection(self):
        """Without field_types, detect Odoo datetime strings."""
        record = {"write_date": "2025-01-15 09:00:00"}
        result = normalize_record(record, {})
        assert result["write_date"] == "2025-01-15T09:00:00Z"


# ---------------------------------------------------------------------------
# normalize_records
# ---------------------------------------------------------------------------

class TestNormalizeRecords:
    def test_empty_list(self):
        assert normalize_records([]) == []

    def test_multiple_records(self):
        records = [
            {"id": 1, "name": False, "partner_id": [2, "X"]},
            {"id": 2, "name": "Test", "partner_id": False},
        ]
        result = normalize_records(
            records,
            {"name": "char", "partner_id": "many2one"},
        )
        assert result[0]["name"] == ""
        assert result[0]["partner_id"] == {"id": 2, "name": "X"}
        assert result[1]["name"] == "Test"
        assert result[1]["partner_id"] is None


# ---------------------------------------------------------------------------
# save_binary_to_file
# ---------------------------------------------------------------------------

class TestSaveBinaryToFile:
    def test_basic_save(self, tmp_path):
        data = base64.b64encode(b"hello world").decode()
        path = save_binary_to_file(data, "datas", record_id=42, model="ir.attachment")
        assert path != ""
        assert os.path.isfile(path)
        with open(path, "rb") as f:
            assert f.read() == b"hello world"
        os.unlink(path)

    def test_meaningful_filename(self):
        data = base64.b64encode(b"test").decode()
        path = save_binary_to_file(data, "image_1920", record_id=7, model="res.partner")
        assert "res_partner" in os.path.basename(path)
        assert "7" in os.path.basename(path)
        assert "image_1920" in os.path.basename(path)
        os.unlink(path)

    def test_invalid_base64_returns_empty(self):
        assert save_binary_to_file("not-valid-base64!!!", "datas") == ""

    def test_empty_data(self):
        # Empty string is valid base64 (decodes to b"")
        path = save_binary_to_file("", "datas")
        # Empty string has length 0, but save_binary_to_file accepts it
        if path:
            os.unlink(path)

    def test_no_model_no_record(self):
        data = base64.b64encode(b"abc").decode()
        path = save_binary_to_file(data, "file_data")
        assert path != ""
        assert "file_data" in os.path.basename(path)
        os.unlink(path)


# ---------------------------------------------------------------------------
# Binary auto-save in normalize_record
# ---------------------------------------------------------------------------

class TestBinaryAutoSave:
    def test_auto_save_creates_file(self):
        b64 = base64.b64encode(b"PDF content here").decode()
        record = {"id": 5, "datas": b64, "name": "test.pdf"}
        result = normalize_record(
            record,
            {"datas": "binary", "name": "char"},
            requested_fields={"datas", "name"},
            auto_save_binary=True,
            model="ir.attachment",
        )
        assert result["datas"]["type"] == "binary_file"
        assert os.path.isfile(result["datas"]["path"])
        with open(result["datas"]["path"], "rb") as f:
            assert f.read() == b"PDF content here"
        os.unlink(result["datas"]["path"])
        assert result["name"] == "test.pdf"

    def test_auto_save_disabled_keeps_raw(self):
        b64 = base64.b64encode(b"raw").decode()
        record = {"id": 1, "datas": b64}
        result = normalize_record(
            record,
            {"datas": "binary"},
            requested_fields={"datas"},
            auto_save_binary=False,
        )
        assert result["datas"] == b64

    def test_auto_save_default_off(self):
        b64 = base64.b64encode(b"raw").decode()
        record = {"id": 1, "datas": b64}
        result = normalize_record(
            record,
            {"datas": "binary"},
            requested_fields={"datas"},
        )
        # Default auto_save_binary is False, so raw data kept
        assert result["datas"] == b64

    def test_auto_save_empty_value_no_save(self):
        record = {"id": 1, "datas": ""}
        result = normalize_record(
            record,
            {"datas": "binary"},
            requested_fields={"datas"},
            auto_save_binary=True,
        )
        # Empty string should not trigger auto-save
        assert result["datas"] == ""

    def test_auto_save_false_value(self):
        record = {"id": 1, "datas": False}
        result = normalize_record(
            record,
            {"datas": "binary"},
            requested_fields={"datas"},
            auto_save_binary=True,
        )
        # False → None via _normalize_false
        assert result["datas"] is None

    def test_binary_excluded_when_not_requested(self):
        b64 = base64.b64encode(b"data").decode()
        record = {"id": 1, "image": b64, "name": "Test"}
        result = normalize_record(
            record,
            {"image": "binary", "name": "char"},
            auto_save_binary=True,
        )
        assert "image" not in result
        assert result["name"] == "Test"
