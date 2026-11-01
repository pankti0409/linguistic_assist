"""Consent gate (R3). Services call `require(purpose)` before they start.

Consent is held in memory only, so it must be given again after every restart.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from app.core.errors import ConsentRequiredError
from app.core.timing import now_ms
from app.schemas import CONSENT_PURPOSES, ConsentRecord

log = logging.getLogger(__name__)

Listener = Callable[[str], None]


class ConsentRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._granted: dict[str, int] = {}
        self._on_revoke: list[Listener] = []
        self._on_grant: list[Listener] = []

    def grant(self, purpose: str) -> ConsentRecord:
        self._check(purpose)
        with self._lock:
            new = purpose not in self._granted
            self._granted[purpose] = now_ms()
            listeners = list(self._on_grant)
        if new:
            self._notify(listeners, purpose)  # e.g. camera consent starts the CameraHub
        return self.record(purpose)

    def revoke(self, purpose: str) -> ConsentRecord:
        self._check(purpose)
        with self._lock:
            had = self._granted.pop(purpose, None) is not None
            listeners = list(self._on_revoke)
        if had:
            self._notify(listeners, purpose)  # running services stop themselves here
        return self.record(purpose)

    @staticmethod
    def _notify(listeners: list[Listener], purpose: str) -> None:
        for cb in listeners:
            try:
                cb(purpose)
            except Exception:  # one failing service must not block the others
                log.exception("consent listener failed for %s", purpose)

    def has(self, purpose: str) -> bool:
        self._check(purpose)
        with self._lock:
            return purpose in self._granted

    def require(self, purpose: str) -> None:
        if not self.has(purpose):
            raise ConsentRequiredError(purpose)

    def record(self, purpose: str) -> ConsentRecord:
        with self._lock:
            ts = self._granted.get(purpose)
        return ConsentRecord(purpose=purpose, granted=ts is not None, ts_ms=ts)  # type: ignore[arg-type]

    def all(self) -> list[ConsentRecord]:
        return [self.record(p) for p in CONSENT_PURPOSES]

    def on_revoke(self, cb: Listener) -> None:
        with self._lock:
            self._on_revoke.append(cb)

    def on_grant(self, cb: Listener) -> None:
        with self._lock:
            self._on_grant.append(cb)

    @staticmethod
    def _check(purpose: str) -> None:
        if purpose not in CONSENT_PURPOSES:
            raise ValueError(f"unknown consent purpose '{purpose}'")
