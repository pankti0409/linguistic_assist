"""Boundaries to every external dependency. Real adapters and fakes both implement these.

Adapters are dumb transports. Gates (consent, confirmation) live in the services that
call them, so a fake and a real adapter are held to the same rules.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol, runtime_checkable

import numpy as np

from app.schemas import LipEvidence, SpeechEvidence


@runtime_checkable
class FrameSource(Protocol):
    def open(self) -> bool: ...
    def read(self) -> tuple[bool, np.ndarray | None]: ...
    def close(self) -> None: ...


@runtime_checkable
class FaceDetector(Protocol):
    """Async face landmarker: results arrive later through the callback given at creation."""

    def detect_async(self, bgr: np.ndarray, ts_ms: int) -> None: ...
    def close(self) -> None: ...


@runtime_checkable
class SpeechToText(Protocol):
    def transcribe(
        self, pcm16: bytes, sample_rate: int, language: str | None = None
    ) -> SpeechEvidence: ...


@runtime_checkable
class LLMClient(Protocol):
    def complete_json(
        self, system: str, user: str, *, temperature: float, max_tokens: int
    ) -> str: ...


@runtime_checkable
class TextToSpeech(Protocol):
    def synthesize(self, text: str, voice_id: str) -> bytes: ...


@runtime_checkable
class AvatarTransport(Protocol):
    """Room transport for Tavus app messages (daily-python in production)."""

    def join(self, conversation_url: str, on_message: Callable[[dict], None]) -> None: ...
    def send(self, message: dict) -> None: ...
    def leave(self) -> None: ...


@runtime_checkable
class TavusREST(Protocol):
    def create_conversation(self, body: dict) -> dict: ...
    def end_conversation(self, conversation_id: str) -> None: ...


@runtime_checkable
class LipReader(Protocol):
    @property
    def available(self) -> bool: ...
    def read(
        self, frames: Sequence[np.ndarray], landmarks: Sequence[np.ndarray | None] = ()
    ) -> LipEvidence: ...
