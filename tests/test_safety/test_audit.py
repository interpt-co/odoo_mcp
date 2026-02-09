"""Tests for audit logging."""

import asyncio
import json
import os
import tempfile

import pytest

from odoo_mcp.safety.audit import AuditConfig, AuditLogger, _looks_like_base64


def _run(coro):
    """Helper to run async code in tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestAuditConfig:
    def test_defaults(self):
        config = AuditConfig()
        assert config.enabled is False
        assert config.log_file is None
        assert config.log_reads is False
        assert config.log_writes is True
        assert config.log_deletes is True


class TestAuditLoggerDisabled:
    def test_disabled_does_nothing(self):
        logger = AuditLogger(AuditConfig(enabled=False))
        # Should not raise
        _run(logger.log_operation(
            tool="odoo_core_create",
            model="sale.order",
            operation="create",
            values={"name": "test"},
            result=42,
            success=True,
            duration_ms=100,
            session_id="sess1",
            odoo_uid=2,
        ))


class TestAuditLoggerFiltering:
    def test_does_not_log_reads_by_default(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name

        try:
            config = AuditConfig(enabled=True, log_file=path, log_reads=False)
            logger = AuditLogger(config)
            _run(logger.log_operation(
                tool="odoo_core_search_read",
                model="sale.order",
                operation="read",
                values=None,
                result=[],
                success=True,
                duration_ms=50,
                session_id="sess1",
                odoo_uid=2,
            ))
            with open(path) as f:
                assert f.read().strip() == ""
        finally:
            os.unlink(path)

    def test_logs_reads_when_enabled(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name

        try:
            config = AuditConfig(enabled=True, log_file=path, log_reads=True)
            logger = AuditLogger(config)
            _run(logger.log_operation(
                tool="odoo_core_search_read",
                model="sale.order",
                operation="read",
                values=None,
                result=[{"id": 1, "name": "SO001"}],
                success=True,
                duration_ms=50,
                session_id="sess1",
                odoo_uid=2,
            ))
            with open(path) as f:
                line = f.readline()
            entry = json.loads(line)
            assert entry["tool"] == "odoo_core_search_read"
            assert entry["operation"] == "read"
            # Should not include full record data, just IDs
            assert "result_ids" in entry or "result_count" in entry
        finally:
            os.unlink(path)

    def test_logs_writes(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name

        try:
            config = AuditConfig(enabled=True, log_file=path, log_writes=True)
            logger = AuditLogger(config)
            _run(logger.log_operation(
                tool="odoo_core_create",
                model="sale.order",
                operation="create",
                values={"partner_id": 1, "note": "Test"},
                result=42,
                success=True,
                duration_ms=100,
                session_id="sess1",
                odoo_uid=2,
            ))
            with open(path) as f:
                line = f.readline()
            entry = json.loads(line)
            assert entry["tool"] == "odoo_core_create"
            assert entry["model"] == "sale.order"
            assert entry["result_id"] == 42
            assert entry["success"] is True
        finally:
            os.unlink(path)

    def test_logs_deletes(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name

        try:
            config = AuditConfig(enabled=True, log_file=path, log_deletes=True)
            logger = AuditLogger(config)
            _run(logger.log_operation(
                tool="odoo_core_unlink",
                model="sale.order",
                operation="unlink",
                values=None,
                result=True,
                success=True,
                duration_ms=50,
                session_id="sess1",
                odoo_uid=2,
            ))
            with open(path) as f:
                line = f.readline()
            entry = json.loads(line)
            assert entry["operation"] == "unlink"
        finally:
            os.unlink(path)


class TestAuditLoggerSanitization:
    """REQ-11-24: Sensitive data must never be logged."""

    def test_passwords_redacted(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name

        try:
            config = AuditConfig(enabled=True, log_file=path, log_writes=True)
            logger = AuditLogger(config)
            _run(logger.log_operation(
                tool="odoo_core_write",
                model="res.users",
                operation="write",
                values={"name": "Test", "password": "secret123", "api_key": "abcdef"},
                result=True,
                success=True,
                duration_ms=100,
                session_id="sess1",
                odoo_uid=2,
            ))
            with open(path) as f:
                line = f.readline()
            entry = json.loads(line)
            assert entry["values"]["password"] == "***REDACTED***"
            assert entry["values"]["api_key"] == "***REDACTED***"
            assert entry["values"]["name"] == "Test"
        finally:
            os.unlink(path)

    def test_binary_content_filtered(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name

        try:
            config = AuditConfig(enabled=True, log_file=path, log_writes=True)
            logger = AuditLogger(config)
            _run(logger.log_operation(
                tool="odoo_core_write",
                model="ir.attachment",
                operation="write",
                values={"name": "test.pdf", "datas": b"\x00\x01\x02" * 100},
                result=True,
                success=True,
                duration_ms=100,
                session_id="sess1",
                odoo_uid=2,
            ))
            with open(path) as f:
                line = f.readline()
            entry = json.loads(line)
            assert "binary" in entry["values"]["datas"].lower()
            assert entry["values"]["name"] == "test.pdf"
        finally:
            os.unlink(path)

    def test_read_only_logs_ids(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name

        try:
            config = AuditConfig(enabled=True, log_file=path, log_reads=True)
            logger = AuditLogger(config)
            _run(logger.log_operation(
                tool="odoo_core_read",
                model="res.partner",
                operation="read",
                values=None,
                result=[
                    {"id": 1, "name": "Alice", "email": "alice@test.com"},
                    {"id": 2, "name": "Bob", "email": "bob@test.com"},
                ],
                success=True,
                duration_ms=50,
                session_id="sess1",
                odoo_uid=2,
            ))
            with open(path) as f:
                line = f.readline()
            entry = json.loads(line)
            # Should have result_count and result_ids, not full data
            assert entry["result_count"] == 2
            assert entry["result_ids"] == [1, 2]
            assert "Alice" not in json.dumps(entry)
        finally:
            os.unlink(path)


class TestAuditEntryFormat:
    """REQ-11-23: Verify JSONL entry format."""

    def test_entry_has_required_fields(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name

        try:
            config = AuditConfig(enabled=True, log_file=path, log_writes=True)
            logger = AuditLogger(config)
            _run(logger.log_operation(
                tool="odoo_core_create",
                model="sale.order",
                operation="create",
                values={"partner_id": 1},
                result=42,
                success=True,
                duration_ms=150,
                session_id="abc123",
                odoo_uid=2,
            ))
            with open(path) as f:
                line = f.readline()
            entry = json.loads(line)
            assert "timestamp" in entry
            assert entry["session_id"] == "abc123"
            assert entry["tool"] == "odoo_core_create"
            assert entry["model"] == "sale.order"
            assert entry["operation"] == "create"
            assert entry["values"] == {"partner_id": 1}
            assert entry["result_id"] == 42
            assert entry["success"] is True
            assert entry["duration_ms"] == 150
            assert entry["odoo_uid"] == 2
        finally:
            os.unlink(path)

    def test_timestamp_is_iso8601(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name

        try:
            config = AuditConfig(enabled=True, log_file=path, log_writes=True)
            logger = AuditLogger(config)
            _run(logger.log_operation(
                tool="odoo_core_create",
                model="sale.order",
                operation="create",
                values={},
                result=1,
                success=True,
                duration_ms=10,
                session_id="s1",
                odoo_uid=1,
            ))
            with open(path) as f:
                line = f.readline()
            entry = json.loads(line)
            from datetime import datetime
            # Should not raise
            datetime.fromisoformat(entry["timestamp"])
        finally:
            os.unlink(path)


class TestBase64Detection:
    def test_detects_base64(self):
        b64 = "A" * 200
        assert _looks_like_base64(b64) is True

    def test_rejects_short_strings(self):
        assert _looks_like_base64("abc") is False

    def test_rejects_normal_text(self):
        text = "This is a normal text string with spaces and punctuation! " * 5
        assert _looks_like_base64(text) is False
