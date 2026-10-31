"""Confirmation gate (R2, section 8.7).

`issue(turn_id, text)` binds a one-time ID to the sha256 of the exact text. Speaking code
gets the text only through `consume(id)`. A missing, used, expired or mismatched ID raises,
so nothing can be spoken.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.core.errors import AppError


class ConfirmationError(AppError):
    status_code = 403
    error_code = "confirmation_invalid"
    recoverable = True


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class _Entry:
    turn_id: str
    text: str
    digest: str
    expires_at: float
    used: bool = False


class ConfirmationRegistry:
    def __init__(self, ttl_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl_s = ttl_s
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, _Entry] = {}

    def issue(self, turn_id: str, text: str) -> str:
        if not text.strip():
            raise ConfirmationError("cannot confirm empty text")
        cid = secrets.token_urlsafe(16)
        with self._lock:
            self._purge()
            self._entries[cid] = _Entry(turn_id, text, sha256(text), self._clock() + self.ttl_s)
        return cid

    def consume(self, confirmation_id: str | None) -> tuple[str, str]:
        """Single use. Returns (turn_id, text). Raises ConfirmationError otherwise."""
        if not confirmation_id:
            raise ConfirmationError("no confirmation_id")
        with self._lock:
            e = self._entries.get(confirmation_id)
            if e is None:
                raise ConfirmationError("unknown confirmation_id")
            if e.used:
                raise ConfirmationError("confirmation_id already used")
            if self._clock() > e.expires_at:
                raise ConfirmationError("confirmation_id expired")
            if sha256(e.text) != e.digest:
                raise ConfirmationError("confirmed text does not match its hash")
            e.used = True
            return e.turn_id, e.text

    def _purge(self) -> None:
        now = self._clock()
        for k in [k for k, e in self._entries.items() if e.used or now > e.expires_at + 60]:
            del self._entries[k]
