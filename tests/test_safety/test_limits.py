"""Tests for rate limiting."""

import time

import pytest

from odoo_mcp.errors import ErrorCategory, ErrorCode, RateLimitError
from odoo_mcp.safety.limits import RateLimiter, RateLimitConfig


class TestRateLimitConfig:
    def test_defaults(self):
        config = RateLimitConfig()
        assert config.enabled is False
        assert config.calls_per_minute == 60
        assert config.calls_per_hour == 1000
        assert config.burst == 10
        assert config.read_calls_per_minute == 120
        assert config.write_calls_per_minute == 30

    def test_custom_config(self):
        config = RateLimitConfig(
            enabled=True,
            calls_per_minute=30,
            burst=5,
        )
        assert config.enabled is True
        assert config.calls_per_minute == 30
        assert config.burst == 5


class TestRateLimiterDisabled:
    def test_disabled_allows_unlimited(self):
        limiter = RateLimiter(RateLimitConfig(enabled=False))
        for _ in range(200):
            limiter.check_rate_limit("read")  # Should never raise


class TestRateLimiterBurst:
    def test_burst_limit(self):
        config = RateLimitConfig(enabled=True, burst=3, calls_per_minute=1000)
        limiter = RateLimiter(config)

        # First 3 should pass
        for _ in range(3):
            limiter.check_rate_limit("read")

        # 4th should fail (burst limit)
        with pytest.raises(RateLimitError) as exc_info:
            limiter.check_rate_limit("read")
        assert exc_info.value.retry_after > 0


class TestRateLimiterPerMinute:
    def test_global_per_minute_limit(self):
        config = RateLimitConfig(
            enabled=True,
            calls_per_minute=5,
            burst=100,  # high burst to not interfere
            read_calls_per_minute=100,
            calls_per_hour=10000,
        )
        limiter = RateLimiter(config)

        for _ in range(5):
            limiter.check_rate_limit("read")

        with pytest.raises(RateLimitError) as exc_info:
            limiter.check_rate_limit("read")
        assert exc_info.value.retry_after > 0

    def test_read_per_minute_limit(self):
        config = RateLimitConfig(
            enabled=True,
            calls_per_minute=1000,
            burst=100,
            read_calls_per_minute=3,
            calls_per_hour=10000,
        )
        limiter = RateLimiter(config)

        for _ in range(3):
            limiter.check_rate_limit("read")

        with pytest.raises(RateLimitError):
            limiter.check_rate_limit("read")

    def test_write_per_minute_limit(self):
        config = RateLimitConfig(
            enabled=True,
            calls_per_minute=1000,
            burst=100,
            write_calls_per_minute=2,
            calls_per_hour=10000,
        )
        limiter = RateLimiter(config)

        for _ in range(2):
            limiter.check_rate_limit("write")

        with pytest.raises(RateLimitError):
            limiter.check_rate_limit("write")


class TestRateLimiterSeparateReadWrite:
    def test_read_and_write_tracked_separately(self):
        config = RateLimitConfig(
            enabled=True,
            calls_per_minute=1000,
            burst=100,
            read_calls_per_minute=3,
            write_calls_per_minute=3,
            calls_per_hour=10000,
        )
        limiter = RateLimiter(config)

        # Use up all read budget
        for _ in range(3):
            limiter.check_rate_limit("read")

        # Write should still work
        limiter.check_rate_limit("write")

        # But read should fail
        with pytest.raises(RateLimitError):
            limiter.check_rate_limit("read")


class TestRateLimiterReset:
    def test_reset_clears_counters(self):
        config = RateLimitConfig(
            enabled=True,
            calls_per_minute=2,
            burst=100,
            read_calls_per_minute=100,
            calls_per_hour=10000,
        )
        limiter = RateLimiter(config)

        for _ in range(2):
            limiter.check_rate_limit("read")

        with pytest.raises(RateLimitError):
            limiter.check_rate_limit("read")

        limiter.reset()
        limiter.check_rate_limit("read")  # Should work again


class TestRateLimiterRetryAfter:
    def test_retry_after_is_positive(self):
        config = RateLimitConfig(
            enabled=True,
            calls_per_minute=1,
            burst=100,
            read_calls_per_minute=100,
            calls_per_hour=10000,
        )
        limiter = RateLimiter(config)
        limiter.check_rate_limit("read")

        with pytest.raises(RateLimitError) as exc_info:
            limiter.check_rate_limit("read")
        assert exc_info.value.retry_after > 0
        assert exc_info.value.retry_after <= 60


class TestRateLimiterErrorResponse:
    def test_make_rate_limit_error_response(self):
        config = RateLimitConfig(enabled=True)
        limiter = RateLimiter(config)
        exc = RateLimitError("Rate limit exceeded", retry_after=5.0)
        resp = limiter.make_rate_limit_error_response(exc)
        assert resp.category == ErrorCategory.RATE_LIMIT
        assert resp.code == ErrorCode.RATE_LIMITED
        assert resp.retry is True
        assert resp.details["retry_after"] == 5.0


class TestRateLimiterThreadSafety:
    def test_concurrent_access(self):
        """Basic thread safety test."""
        import threading

        config = RateLimitConfig(
            enabled=True,
            calls_per_minute=1000,
            burst=100,
            read_calls_per_minute=1000,
            calls_per_hour=10000,
        )
        limiter = RateLimiter(config)
        errors = []

        def worker():
            try:
                for _ in range(10):
                    limiter.check_rate_limit("read")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should not have any unexpected errors (RateLimitError is expected)
        for e in errors:
            assert isinstance(e, RateLimitError)
