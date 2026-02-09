"""
Rate limiting for the Odoo MCP server.

Implements per-session sliding window rate limiting with separate
read/write limits (REQ-11-19 through REQ-11-21).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

from odoo_mcp.errors import ErrorCategory, ErrorCode, ErrorResponse, RateLimitError


@dataclass
class RateLimitConfig:
    """Rate limit configuration (REQ-11-19)."""

    enabled: bool = False
    calls_per_minute: int = 60
    calls_per_hour: int = 1000
    burst: int = 10
    read_calls_per_minute: int = 120
    write_calls_per_minute: int = 30


class RateLimiter:
    """Per-session sliding window rate limiter (REQ-11-19 through REQ-11-21).

    Thread-safe for concurrent requests.
    """

    def __init__(self, config: RateLimitConfig | None = None):
        self._config = config or RateLimitConfig()
        self._lock = threading.Lock()
        # Separate tracking for read and write operations
        self._read_timestamps: deque[float] = deque()
        self._write_timestamps: deque[float] = deque()
        # Combined tracking for global limits
        self._all_timestamps: deque[float] = deque()
        # Burst tracking: timestamps within last second
        self._burst_timestamps: deque[float] = deque()

    @property
    def config(self) -> RateLimitConfig:
        return self._config

    def check_rate_limit(self, operation_type: str = "read") -> None:
        """Check if the rate limit has been exceeded.

        Args:
            operation_type: "read" or "write".

        Raises:
            RateLimitError: When the limit is exceeded, includes retry_after.
        """
        if not self._config.enabled:
            return

        now = time.monotonic()

        with self._lock:
            # Clean up old entries
            self._cleanup(now)

            # Check burst limit (per-second)
            if len(self._burst_timestamps) >= self._config.burst:
                oldest_burst = self._burst_timestamps[0]
                retry_after = max(0.1, 1.0 - (now - oldest_burst))
                raise RateLimitError(
                    f"Burst limit exceeded ({self._config.burst} calls/second)",
                    retry_after=retry_after,
                )

            # Check per-minute limits
            if operation_type == "read":
                timestamps = self._read_timestamps
                limit = self._config.read_calls_per_minute
            else:
                timestamps = self._write_timestamps
                limit = self._config.write_calls_per_minute

            minute_count = sum(1 for t in timestamps if now - t < 60)
            if minute_count >= limit:
                oldest_in_minute = next(t for t in timestamps if now - t < 60)
                retry_after = max(0.1, 60.0 - (now - oldest_in_minute))
                raise RateLimitError(
                    f"{operation_type.title()} rate limit exceeded "
                    f"({limit} calls/minute)",
                    retry_after=retry_after,
                )

            # Check global per-minute limit
            global_minute = sum(1 for t in self._all_timestamps if now - t < 60)
            if global_minute >= self._config.calls_per_minute:
                oldest_in_minute = next(t for t in self._all_timestamps if now - t < 60)
                retry_after = max(0.1, 60.0 - (now - oldest_in_minute))
                raise RateLimitError(
                    f"Global rate limit exceeded "
                    f"({self._config.calls_per_minute} calls/minute)",
                    retry_after=retry_after,
                )

            # Check per-hour limit
            hour_count = len(self._all_timestamps)  # after cleanup, all are within 1h
            if hour_count >= self._config.calls_per_hour:
                oldest = self._all_timestamps[0]
                retry_after = max(0.1, 3600.0 - (now - oldest))
                raise RateLimitError(
                    f"Hourly rate limit exceeded "
                    f"({self._config.calls_per_hour} calls/hour)",
                    retry_after=retry_after,
                )

            # Record the call
            self._all_timestamps.append(now)
            self._burst_timestamps.append(now)
            if operation_type == "read":
                self._read_timestamps.append(now)
            else:
                self._write_timestamps.append(now)

    def _cleanup(self, now: float) -> None:
        """Remove entries older than 1 hour (or 1 second for burst)."""
        one_hour_ago = now - 3600
        one_second_ago = now - 1.0

        while self._all_timestamps and self._all_timestamps[0] < one_hour_ago:
            self._all_timestamps.popleft()
        while self._read_timestamps and self._read_timestamps[0] < one_hour_ago:
            self._read_timestamps.popleft()
        while self._write_timestamps and self._write_timestamps[0] < one_hour_ago:
            self._write_timestamps.popleft()
        while self._burst_timestamps and self._burst_timestamps[0] < one_second_ago:
            self._burst_timestamps.popleft()

    def reset(self) -> None:
        """Reset all rate limit counters."""
        with self._lock:
            self._all_timestamps.clear()
            self._read_timestamps.clear()
            self._write_timestamps.clear()
            self._burst_timestamps.clear()

    def make_rate_limit_error_response(self, exc: RateLimitError) -> ErrorResponse:
        """Convert a RateLimitError into an ErrorResponse."""
        return ErrorResponse(
            category=ErrorCategory.RATE_LIMIT,
            code=ErrorCode.RATE_LIMITED,
            message=str(exc),
            suggestion=f"Rate limit exceeded. Wait {exc.retry_after:.1f} seconds before retrying.",
            retry=True,
            details={"retry_after": exc.retry_after},
        )
