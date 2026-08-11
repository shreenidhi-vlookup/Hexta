"""Unit tests for the login rate limiter and brute-force lockout."""

from __future__ import annotations

from app.auth.rate_limit import (
    MAX_FAILURES,
    MAX_REQUESTS,
    limiter,
)


class TestRateLimit:
    def setup_method(self):
        limiter.reset()

    def test_request_budget_blocks_after_limit(self):
        ip = "10.0.0.1"
        allowed = sum(limiter.check_request(ip) for _ in range(MAX_REQUESTS + 5))
        assert allowed == MAX_REQUESTS

    def test_lockout_after_max_failures(self):
        ip = "10.0.0.2"
        email = "victim@example.com"
        triggered = None
        for _ in range(MAX_FAILURES):
            triggered = limiter.register_failure(ip, email)
        assert triggered is True
        assert limiter.is_locked(ip, email) is True

    def test_not_locked_below_threshold(self):
        ip = "10.0.0.3"
        email = "ok@example.com"
        for _ in range(MAX_FAILURES - 1):
            limiter.register_failure(ip, email)
        assert limiter.is_locked(ip, email) is False

    def test_success_clears_failures(self):
        ip = "10.0.0.4"
        email = "retry@example.com"
        for _ in range(MAX_FAILURES - 1):
            limiter.register_failure(ip, email)
        limiter.clear(ip, email)
        assert limiter.is_locked(ip, email) is False
        # remaining failure slots reset so a new login can succeed
        assert limiter.register_failure(ip, email) is False

    def test_isolated_keys(self):
        # Failures for one email/IP do not lock a different email/IP.
        limiter.register_failure("10.0.0.5", "a@example.com")
        assert limiter.is_locked("10.0.0.6", "a@example.com") is False
        assert limiter.is_locked("10.0.0.5", "b@example.com") is False
