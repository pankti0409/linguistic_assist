"""Personalisation (section 8.6 C): the confirmed-sentence phrasebook and profile terms.

Both are local JSON files under data/ (gitignored) and need `personalization` consent to be
read, used or written. Deleting is always allowed. Retrieval is Jaccard token overlap, no
embeddings.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from app.core.consent import ConsentRegistry
from app.core.errors import AppError
from app.core.fragments import tokens
from app.core.timing import now_ms
from app.schemas import PhraseEntry

MAX_TERMS = 200
MAX_TERM_LEN = 60


class InvalidProfileError(AppError):
    status_code = 422
    error_code = "invalid_profile_terms"
    recoverable = True


def _atomic_write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


class Phrasebook:
    def __init__(self, path: Path, consent: ConsentRegistry) -> None:
        self.path = path
        self._consent = consent
        self._lock = threading.Lock()
        self._entries: list[PhraseEntry] = []
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            self._entries = [PhraseEntry(**e) for e in raw]

    def entries(self) -> list[PhraseEntry]:
        self._consent.require("personalization")
        with self._lock:
            return list(self._entries)

    def add(self, text: str, edited: bool) -> PhraseEntry | None:
        """Record a confirmed sentence; an edited one counts double. Needs consent."""
        if not self._consent.has("personalization") or not text.strip():
            return None
        weight = 2 if edited else 1
        key = " ".join(tokens(text))
        with self._lock:
            for i, e in enumerate(self._entries):
                if " ".join(tokens(e.text)) == key:
                    self._entries[i] = PhraseEntry(
                        text=text, uses=e.uses + weight, last_used_ms=now_ms()
                    )
                    entry = self._entries[i]
                    break
            else:
                entry = PhraseEntry(text=text, uses=weight, last_used_ms=now_ms())
                self._entries.append(entry)
            data = [e.model_dump() for e in self._entries]
        _atomic_write(self.path, data)
        return entry

    def search(self, cleaned_fragments: list[str], k: int) -> list[PhraseEntry]:
        """Top-k entries by Jaccard overlap with the cleaned fragments (ties: more uses)."""
        if not self._consent.has("personalization"):
            return []
        query = {t for frag in cleaned_fragments for t in tokens(frag)}
        with self._lock:
            scored = [(jaccard(query, set(tokens(e.text))), e.uses, e) for e in self._entries]
        scored = [s for s in scored if s[0] > 0]
        scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
        return [e for _, _, e in scored[:k]]

    def wipe(self) -> int:
        with self._lock:
            n = len(self._entries)
            self._entries = []
        self.path.unlink(missing_ok=True)
        return n


class ProfileTerms:
    """Names, places, items and needs entered by the patient or caregiver."""

    def __init__(self, path: Path, consent: ConsentRegistry) -> None:
        self.path = path
        self._consent = consent
        self._lock = threading.Lock()
        self._terms: list[str] = []
        if path.is_file():
            self._terms = json.loads(path.read_text(encoding="utf-8"))

    def get(self) -> list[str]:
        self._consent.require("personalization")
        with self._lock:
            return list(self._terms)

    def for_packet(self) -> list[str]:
        if not self._consent.has("personalization"):
            return []
        with self._lock:
            return list(self._terms)

    def put(self, terms: list[str]) -> list[str]:
        self._consent.require("personalization")
        clean: list[str] = []
        for t in terms:
            if not isinstance(t, str):
                raise InvalidProfileError("terms must be strings")
            t = " ".join(t.split())
            if not t:
                continue
            if len(t) > MAX_TERM_LEN:
                raise InvalidProfileError(f"term longer than {MAX_TERM_LEN} chars: {t[:20]}...")
            if t not in clean:
                clean.append(t)
        if len(clean) > MAX_TERMS:
            raise InvalidProfileError(f"at most {MAX_TERMS} terms")
        with self._lock:
            self._terms = clean
        _atomic_write(self.path, clean)
        return clean
