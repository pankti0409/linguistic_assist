"""Recent dialogue context: the last CONTEXT_TURNS labelled turns (section 8.6 C)."""

from __future__ import annotations

import threading
from collections import deque

from app.core.timing import now_ms
from app.schemas import DialogueTurn, Speaker


class Conversation:
    def __init__(self, max_turns: int) -> None:
        self._lock = threading.Lock()
        self._turns: deque[DialogueTurn] = deque(maxlen=max(1, max_turns))

    def add(self, speaker: Speaker, text: str, ts_ms: int | None = None) -> DialogueTurn | None:
        text = text.strip()
        if not text:
            return None
        turn = DialogueTurn(speaker=speaker, text=text, ts_ms=ts_ms or now_ms())
        with self._lock:
            self._turns.append(turn)
        return turn

    def recent(self) -> list[DialogueTurn]:
        with self._lock:
            return list(self._turns)

    def last_partner_line(self) -> str | None:
        with self._lock:
            for t in reversed(self._turns):
                if t.speaker == "PARTNER":
                    return t.text
        return None
