"""Tests for odoo_mcp.search.progressive — ProgressiveSearch, all 5 levels."""

import json

import pytest

from odoo_mcp.search.progressive import (
    ModelSearchConfig,
    ProgressiveSearch,
    SEARCH_CONFIGS,
    _get_config,
)


# ---------------------------------------------------------------------------
# Mock connection
# ---------------------------------------------------------------------------

class MockSearchConnection:
    """Simulates Odoo responses for progressive search testing."""

    def __init__(self):
        self.calls = []
        self._responses = {}

    def set_response(self, model, method, response):
        self._responses[(model, method)] = response

    async def execute_kw(self, model, method, args, kwargs=None):
        self.calls.append((model, method, args, kwargs or {}))
        key = (model, method)
        if key in self._responses:
            resp = self._responses[key]
            if callable(resp):
                return resp(args, kwargs)
            return resp
        # Default responses
        if method == "fields_get":
            return {
                "name": {"type": "char"},
                "email": {"type": "char"},
                "phone": {"type": "char"},
                "description": {"type": "text"},
            }
        if method == "search":
            return []
        if method == "search_read":
            return []
        if method == "read":
            ids = args[0] if args else []
            return [{"id": i, "name": f"Record {i}"} for i in ids]
        return []


class MockConfig:
    mode = "full"
    model_blocklist = []
    model_allowlist = []
    search_max_limit = 500
    strip_html = True


# ---------------------------------------------------------------------------
# Search config
# ---------------------------------------------------------------------------

class TestModelSearchConfig:
    def test_default_configs_exist(self):
        assert "res.partner" in SEARCH_CONFIGS
        assert "sale.order" in SEARCH_CONFIGS
        assert "account.move" in SEARCH_CONFIGS
        assert "product.product" in SEARCH_CONFIGS

    def test_partner_config(self):
        cfg = SEARCH_CONFIGS["res.partner"]
        assert cfg.name_field == "name"
        assert "email" in cfg.deep_search_fields
        assert cfg.has_chatter is True
        assert len(cfg.related_models) > 0

    def test_product_no_chatter(self):
        cfg = SEARCH_CONFIGS["product.product"]
        assert cfg.has_chatter is False
        assert cfg.related_models == []

    def test_fallback_for_unknown(self):
        cfg = _get_config("custom.model")
        assert cfg.name_field == "name"
        assert cfg.search_fields == ["name"]


# ---------------------------------------------------------------------------
# Level 1 — Exact match
# ---------------------------------------------------------------------------

class TestLevel1ExactMatch:
    @pytest.mark.asyncio
    async def test_exact_match_found(self):
        conn = MockSearchConnection()
        conn.set_response("res.partner", "search_read", [
            {"id": 1, "name": "Acme Corp", "email": "info@acme.com"},
        ])

        engine = ProgressiveSearch(conn, MockConfig())
        result = await engine.search(query="Acme Corp", model="res.partner", max_depth=1)

        assert result["total_results"] == 1
        assert result["depth_reached"] == 1
        assert "exact_match" in result["strategies_used"]
        assert "res.partner" in result["results"]

    @pytest.mark.asyncio
    async def test_exact_match_not_found_stops(self):
        conn = MockSearchConnection()
        engine = ProgressiveSearch(conn, MockConfig())
        result = await engine.search(query="NonexistentXYZ", model="res.partner", max_depth=1)

        assert result["total_results"] == 0
        assert len(result["suggestions"]) > 0


# ---------------------------------------------------------------------------
# Level 2 — Standard ilike
# ---------------------------------------------------------------------------

class TestLevel2StandardIlike:
    @pytest.mark.asyncio
    async def test_ilike_found(self):
        conn = MockSearchConnection()

        def search_read_handler(args, kwargs):
            domain = args[0] if args else []
            # Level 1 exact match returns nothing
            for cond in domain:
                if isinstance(cond, tuple) and cond[1] == "=":
                    return []
            # Level 2 ilike returns results
            return [{"id": 1, "name": "Acme Corp"}]

        conn.set_response("res.partner", "search_read", search_read_handler)

        engine = ProgressiveSearch(conn, MockConfig())
        result = await engine.search(query="acme", model="res.partner", max_depth=2)

        assert result["total_results"] >= 1
        assert "standard_ilike" in result["strategies_used"]


# ---------------------------------------------------------------------------
# Level 3 — Extended fields
# ---------------------------------------------------------------------------

class TestLevel3ExtendedFields:
    @pytest.mark.asyncio
    async def test_deep_fields_searched(self):
        conn = MockSearchConnection()
        call_count = {"n": 0}

        def search_read_handler(args, kwargs):
            call_count["n"] += 1
            # First 2 calls (level 1 & 2) return empty
            if call_count["n"] <= 2:
                return []
            # Level 3 returns results
            return [{"id": 5, "name": "Found via email"}]

        conn.set_response("res.partner", "search_read", search_read_handler)

        engine = ProgressiveSearch(conn, MockConfig())
        result = await engine.search(
            query="john@example.com", model="res.partner", max_depth=3,
        )

        assert result["total_results"] >= 1
        assert "extended_fields" in result["strategies_used"]


# ---------------------------------------------------------------------------
# Level 5 — Chatter search
# ---------------------------------------------------------------------------

class TestLevel5ChatterSearch:
    @pytest.mark.asyncio
    async def test_chatter_search(self):
        conn = MockSearchConnection()
        call_count = {"n": 0}

        def partner_search_handler(args, kwargs):
            call_count["n"] += 1
            if call_count["n"] <= 4:
                return []
            return []

        conn.set_response("res.partner", "search_read", partner_search_handler)
        conn.set_response("mail.message", "search_read", [
            {"id": 100, "res_id": 7},
            {"id": 101, "res_id": 8},
        ])
        conn.set_response("res.partner", "read", [
            {"id": 7, "name": "Found in chatter"},
            {"id": 8, "name": "Also in chatter"},
        ])

        engine = ProgressiveSearch(conn, MockConfig())
        result = await engine.search(
            query="special keyword", model="res.partner", max_depth=5,
        )

        assert result["depth_reached"] == 5
        assert "chatter_search" in result["strategies_used"]


# ---------------------------------------------------------------------------
# Exhaustive mode
# ---------------------------------------------------------------------------

class TestExhaustiveMode:
    @pytest.mark.asyncio
    async def test_exhaustive_runs_all_levels(self):
        conn = MockSearchConnection()
        conn.set_response("res.partner", "search_read", [
            {"id": 1, "name": "Found early"},
        ])

        engine = ProgressiveSearch(conn, MockConfig())
        result = await engine.search(
            query="Found early", model="res.partner",
            max_depth=3, exhaustive=True,
        )

        # Should have log entries for all 3 levels even though level 1 found results
        levels_in_log = {entry["level"] for entry in result["search_log"]}
        assert 1 in levels_in_log
        assert 2 in levels_in_log
        assert 3 in levels_in_log


# ---------------------------------------------------------------------------
# Stop on results (non-exhaustive)
# ---------------------------------------------------------------------------

class TestStopOnResults:
    @pytest.mark.asyncio
    async def test_stops_after_first_results(self):
        conn = MockSearchConnection()
        conn.set_response("res.partner", "search_read", [
            {"id": 1, "name": "Acme"},
        ])

        engine = ProgressiveSearch(conn, MockConfig())
        result = await engine.search(
            query="Acme", model="res.partner",
            max_depth=5, exhaustive=False,
        )

        # Should stop at level 1
        assert result["depth_reached"] == 1
        levels_in_log = [e["level"] for e in result["search_log"] if e["model"] == "res.partner"]
        assert levels_in_log == [1]


# ---------------------------------------------------------------------------
# Multi-model search
# ---------------------------------------------------------------------------

class TestMultiModelSearch:
    @pytest.mark.asyncio
    async def test_searches_all_configured_models(self):
        conn = MockSearchConnection()

        def handler(args, kwargs):
            return [{"id": 1, "name": "Test"}]

        for model in SEARCH_CONFIGS:
            conn.set_response(model, "search_read", handler)

        engine = ProgressiveSearch(conn, MockConfig())
        result = await engine.search(query="test", max_depth=1)

        # Should have results from multiple models
        assert len(result["results"]) >= 1


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------

class TestSuggestions:
    @pytest.mark.asyncio
    async def test_no_results_suggestions(self):
        conn = MockSearchConnection()
        engine = ProgressiveSearch(conn, MockConfig())
        result = await engine.search(query="zzznonexistent", model="res.partner", max_depth=1)

        assert len(result["suggestions"]) > 0
        assert any("No results" in s for s in result["suggestions"])

    @pytest.mark.asyncio
    async def test_partner_found_suggestion(self):
        conn = MockSearchConnection()
        conn.set_response("res.partner", "search_read", [
            {"id": 42, "name": "Acme Corp"},
        ])

        engine = ProgressiveSearch(conn, MockConfig())
        result = await engine.search(query="Acme", model="res.partner", max_depth=1)

        assert any("partner" in s.lower() or "Acme" in s for s in result["suggestions"])


# ---------------------------------------------------------------------------
# Search log
# ---------------------------------------------------------------------------

class TestSearchLog:
    @pytest.mark.asyncio
    async def test_log_contains_entries(self):
        conn = MockSearchConnection()
        conn.set_response("res.partner", "search_read", [])

        engine = ProgressiveSearch(conn, MockConfig())
        result = await engine.search(query="test", model="res.partner", max_depth=2)

        assert len(result["search_log"]) == 2
        assert result["search_log"][0]["level"] == 1
        assert result["search_log"][0]["strategy"] == "exact_match"
        assert result["search_log"][1]["level"] == 2
        assert result["search_log"][1]["strategy"] == "standard_ilike"
