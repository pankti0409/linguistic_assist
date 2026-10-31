"""Fragments (section 8.6 A-B): collection across pauses, and deterministic cleanup (no LLM).

Cleanup only collapses exact repeats, drops stutter prefixes and standalone fillers from
the *cleaned* list, and flags the raw fragments. Nothing else is removed: unknown
fragments always reach the LLM.
"""

from __future__ import annotations

import re
import threading

from app.core.timing import now_ms
from app.schemas import Fragment

FILLERS = {"um", "uh", "hmm", "mm", "umm", "uhh", "hm", "erm", "er"}
# Latin + Devanagari letters (incl. matras), digits and inner apostrophes ("don't").
# The danda punctuation marks U+0964 / U+0965 are excluded.
_WORD_RE = re.compile(r"[0-9A-Za-zÀ-ɏऀ-ॣ०-ॿ]+(?:'[A-Za-z]+)?")


def tokens(text: str) -> list[str]:
    return [t.lower() for t in _WORD_RE.findall(text or "")]


def _collapse_inner(toks: list[str], speech: bool) -> tuple[list[str], bool, bool]:
    """Within one fragment: collapse consecutive repeats; drop a token that is a strict
    prefix of the next one (speech only). Returns (tokens, had_repeat, had_stutter)."""
    out: list[str] = []
    repeat = stutter = False
    for t in toks:
        if out and t == out[-1]:
            repeat = True
            continue
        if speech and out and t.startswith(out[-1]) and t != out[-1]:
            out[-1] = t  # "wa water" -> "water"
            stutter = True
            continue
        out.append(t)
    return out, repeat, stutter


def clean(fragments: list[Fragment]) -> tuple[list[Fragment], list[str]]:
    """Return (flagged copies of the raw fragments, cleaned_fragments)."""
    flagged = [f.model_copy(deep=True) for f in fragments]
    norm: list[list[str]] = []
    for f in flagged:
        toks, rep, stut = _collapse_inner(tokens(f.text), f.source == "speech")
        if rep and "repeat" not in f.flags:
            f.flags.append("repeat")
        if stut and "stutter_prefix" not in f.flags:
            f.flags.append("stutter_prefix")
        norm.append(toks)

    keep = [True] * len(flagged)
    for i, f in enumerate(flagged):
        if norm[i] and all(t in FILLERS for t in norm[i]):
            if "filler" not in f.flags:
                f.flags.append("filler")
            keep[i] = False
        if not norm[i]:
            keep[i] = False  # empty text has nothing to clean; the raw fragment stays

    content = [i for i in range(len(flagged)) if keep[i]]
    last_kept: list[str] | None = None
    for pos, i in enumerate(content):
        if "answer_to_question" in flagged[i].flags:
            last_kept = norm[i]
            continue
        nxt = content[pos + 1] if pos + 1 < len(content) else None
        if last_kept is not None and norm[i] == last_kept:
            if "repeat" not in flagged[i].flags:
                flagged[i].flags.append("repeat")
            keep[i] = False  # exact repeat of the last kept fragment
            continue
        if (
            nxt is not None
            and flagged[i].source == "speech"
            and flagged[nxt].source == "speech"
            and len(norm[i]) == 1
            and norm[nxt]
            and norm[nxt][0].startswith(norm[i][0])
            and norm[nxt][0] != norm[i][0]
        ):
            if "stutter_prefix" not in flagged[i].flags:
                flagged[i].flags.append("stutter_prefix")
            keep[i] = False  # "wa" then "water"
            continue
        last_kept = norm[i]

    cleaned = [" ".join(norm[i]) for i in range(len(flagged)) if keep[i]]
    return flagged, cleaned


class FragmentCollector:
    """Ordered, timestamped fragments of one PATIENT draft. Never merges them."""

    def __init__(self, started_ms: int | None = None) -> None:
        self._lock = threading.Lock()
        self._items: list[Fragment] = []
        self._next_id = 1
        self.started_ms = started_ms if started_ms is not None else now_ms()
        self.last_ms = self.started_ms

    def add(
        self,
        source: str,
        text: str,
        *,
        ts_ms: int | None = None,
        confidence: float | None = None,
        flags: list[str] | None = None,
    ) -> Fragment:
        ts = ts_ms if ts_ms is not None else now_ms()
        with self._lock:
            frag = Fragment(
                id=self._next_id,
                ts_ms=ts,
                gap_ms=max(0, ts - self.last_ms),
                source=source,  # type: ignore[arg-type]
                text=text,
                confidence=confidence,
                flags=list(flags or []),  # type: ignore[arg-type]
            )
            self._next_id += 1
            self._items.append(frag)
            self.last_ms = max(self.last_ms, ts)
        return frag

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def items(self) -> list[Fragment]:
        with self._lock:
            return list(self._items)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
