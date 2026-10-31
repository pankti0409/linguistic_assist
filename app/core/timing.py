"""Monotonic clock helpers. Per-turn stage timing is added in M4."""

from __future__ import annotations

import time


def now_ms() -> int:
    """Monotonic milliseconds. Only meaningful for differences within one process."""
    return time.monotonic_ns() // 1_000_000
