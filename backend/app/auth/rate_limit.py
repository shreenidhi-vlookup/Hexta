"""In-memory rate limiting and brute-force lockout for login.

Designed for the single-worker FastAPI deployment (``--workers 1``), so a
process-local store is safe. Tracks:

* A per-IP request budget (basic throttling of login attempts).
* A per-(email, IP) failure window that, when exceeded, locks that email
  and IP out for a cooldown period.

All state is transient — lost on restart, which is acceptable for this
deployment model.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict

# --- Tunables ---
MAX_REQUESTS = 30          # login requests allowed per IP per request window
REQUEST_WINDOW_SEC = 60    # request budget window
MAX_FAILURES = 5           # failed logins before lockout
FAILURE_WINDOW_SEC = 900   # window over which failures are counted (15 min)
LOCKOUT_SEC = 900          # lockout duration after threshold (15 min)

_key = tuple[str, ...]


class _LoginLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._request_log: defaultdict[_key, list[float]] = defaultdict(list)
        self._failures: defaultdict[_key, list[float]] = defaultdict(list)
        self._lockouts: dict[_key, float] = {}

    def reset(self) -> None:
        """Clear all state (used by tests)."""
        with self._lock:
            self._request_log.clear()
            self._failures.clear()
            self._lockouts.clear()

    def check_request(self, ip: str) -> bool:
        """Consume one request budget unit for the IP; False if over budget."""
        key = ("req", ip)
        now = time.time()
        with self._lock:
            self._request_log[key] = [
                t for t in self._request_log[key] if now - t < REQUEST_WINDOW_SEC
            ]
            if len(self._request_log[key]) >= MAX_REQUESTS:
                return False
            self._request_log[key].append(now)
            return True

    def is_locked(self, ip: str, email: str) -> bool:
        now = time.time()
        with self._lock:
            for key in (("lock", ip), ("lock", email)):
                if self._lockouts.get(key, 0) > now:
                    return True
        return False

    def register_failure(self, ip: str, email: str) -> bool:
        """Record a failed attempt; returns True if it triggers a lockout."""
        key = ("fail", email, ip)
        now = time.time()
        with self._lock:
            self._failures[key] = [
                t for t in self._failures[key] if now - t < FAILURE_WINDOW_SEC
            ]
            self._failures[key].append(now)
            if len(self._failures[key]) >= MAX_FAILURES:
                until = now + LOCKOUT_SEC
                self._lockouts[("lock", ip)] = until
                self._lockouts[("lock", email)] = until
                self._failures[key] = []
                return True
        return False

    def clear(self, ip: str, email: str) -> None:
        """Reset failure state after a successful login."""
        with self._lock:
            self._failures.pop(("fail", email, ip), None)
            self._lockouts.pop(("lock", email), None)


limiter = _LoginLimiter()
