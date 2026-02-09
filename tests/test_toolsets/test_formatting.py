"""Tests for odoo_mcp.toolsets.formatting — response normalisation."""

import pytest

from odoo_mcp.toolsets.formatting import (
    normalize_datetime,
    normalize_record,
    normalize_records,
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
