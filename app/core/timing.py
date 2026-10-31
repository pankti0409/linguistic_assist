"""Monotonic clock, per-turn stage timing and the /metrics store (section 10).

Only measured values are stored. Stages that did not run are absent, never zero.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any


def now_ms() -> int:
    """Monotonic milliseconds. Only meaningful for differences within one process."""
    return time.monotonic_ns() // 1_000_000


class TurnTimer:
    """Stamps named points in time for one turn; durations are derived from them."""

    def __init__(self, turn_id: str, speaker: str) -> None:
        self.turn_id = turn_id
        self.speaker = speaker
        self.marks: dict[str, int] = {"start": now_ms()}
        self.counters: dict[str, int] = {"taps": 0, "edits": 0, "clarify_rounds": 0}
        self.tier: str | None = None

    def mark(self, name: str, ts_ms: int | None = None) -> None:
        self.marks.setdefault(name, ts_ms if ts_ms is not None else now_ms())

    def span(self, a: str, b: str) -> int | None:
        if a in self.marks and b in self.marks:
            return self.marks[b] - self.marks[a]
        return None

    def summary(self) -> dict[str, Any]:
        stages = {
            "scribe_ms": self.span("end", "scribe_done"),
            "lip_ms": self.span("end", "lip_done"),
            "fusion_ms": self.span("fusion_start", "fusion_done"),
            "tts_ms": self.span("speak_start", "tts_done"),
            "avatar_ms": self.span("tts_done", "avatar_started"),
            # end of the turn's capture to the first point audio could be heard; see D-034
            "e2e_ms": self.span("end", "audible"),
            "confirm_wait_ms": self.span("candidates", "confirmed"),
        }
        return {
            "turn_id": self.turn_id,
            "speaker": self.speaker,
            "stages": {k: v for k, v in stages.items() if v is not None},
            "tier": self.tier,
            **self.counters,
        }


class Metrics:
    def __init__(self, keep: int = 100) -> None:
        self._lock = threading.Lock()
        self._turns: deque[dict[str, Any]] = deque(maxlen=keep)
        self.counters: dict[str, int] = {}

    def record(self, timer: TurnTimer) -> None:
        with self._lock:
            self._turns.append(timer.summary())

    def bump(self, name: str, n: int = 1) -> None:
        with self._lock:
            self.counters[name] = self.counters.get(name, 0) + n

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            turns = list(self._turns)
            counters = dict(self.counters)
        return {"turns": turns, "counters": counters, "summary": summarise(turns)}


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile; None when there is no data."""
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(p / 100 * len(s) + 0.5)) - 1))
    return float(s[k])


def summarise(turns: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    keys = {k for t in turns for k in t.get("stages", {})}
    for k in sorted(keys):
        vals = [t["stages"][k] for t in turns if k in t.get("stages", {})]
        out[k] = {"n": len(vals), "p50": percentile(vals, 50), "p95": percentile(vals, 95)}
    return out
