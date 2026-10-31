"""Offline fakes for tests and SIMULATE=1. They record calls and return scripted output.

None of these pretend to be real: health reports them with backend="fake".
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

import numpy as np

from app.schemas import LipEvidence, SpeechEvidence


class FakeScribe:
    """Returns scripted transcripts in order; empty string once the script runs out."""

    def __init__(self, transcripts: Iterable[str] = ()) -> None:
        self._script: deque[str] = deque(transcripts)
        self.calls: list[int] = []  # byte length of each request, never the audio itself

    def transcribe(
        self, pcm16: bytes, sample_rate: int, language: str | None = None
    ) -> SpeechEvidence:
        self.calls.append(len(pcm16))
        text = self._script.popleft() if self._script else ""
        return SpeechEvidence(text=text, is_final=True, language=language)


class FakeGroq:
    """Returns scripted raw JSON strings (valid or not, so retry paths can be tested)."""

    def __init__(self, responses: Iterable[str] = ()) -> None:
        self._script: deque[str] = deque(responses)
        self.requests: list[dict[str, object]] = []

    def push(self, response: str) -> None:
        self._script.append(response)

    def complete_json(self, system: str, user: str, *, temperature: float, max_tokens: int) -> str:
        self.requests.append(
            {"system": system, "user": user, "temperature": temperature, "max_tokens": max_tokens}
        )
        if not self._script:
            raise RuntimeError("FakeGroq script exhausted")
        return self._script.popleft()


class FakeTTS:
    """Synthesises deterministic silence-like PCM and records every text it was asked to say."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.spoken: list[str] = []

    def synthesize(self, text: str, voice_id: str) -> bytes:
        if self.fail:
            raise ConnectionError("FakeTTS configured to fail")
        self.spoken.append(text)
        return b"\x00\x00" * 160 * max(1, len(text.split()))


class FakeAvatar:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.spoken: list[tuple[str, str]] = []
        self.interrupts: list[str] = []

    def echo_text(self, conversation_id: str, text: str) -> None:
        if self.fail:
            raise ConnectionError("FakeAvatar configured to fail")
        self.spoken.append((conversation_id, text))

    def interrupt(self, conversation_id: str) -> None:
        self.interrupts.append(conversation_id)


@dataclass
class FakeLipReader:
    """Scripted lip reader. Default is `unavailable`, matching a missing checkpoint."""

    result: LipEvidence = field(default_factory=lambda: LipEvidence(status="unavailable"))
    available: bool = False
    calls: list[int] = field(default_factory=list)

    def read(self, frames: Sequence[np.ndarray]) -> LipEvidence:
        self.calls.append(len(frames))
        return self.result.model_copy(update={"frames": len(frames)})


class VideoFileCamera:
    """FrameSource over a video file, looping at the end (SIMULATE=1 camera)."""

    description = "video file (SIMULATE=1)"

    def __init__(self, path: str, loop: bool = True) -> None:
        self.path = path
        self.loop = loop
        self._cap = None

    def open(self) -> bool:
        import cv2

        self._cap = cv2.VideoCapture(self.path)
        return bool(self._cap.isOpened())

    def read(self) -> tuple[bool, np.ndarray | None]:
        import cv2

        if self._cap is None:
            return False, None
        ok, frame = self._cap.read()
        if not ok and self.loop:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self._cap.read()
        return (True, frame) if ok else (False, None)

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


class SyntheticCamera:
    """FrameSource that makes plain numbered frames in memory. `fail_opens` simulates a
    busy camera, and `fail_after` simulates a camera that stops delivering frames."""

    description = "synthetic frames (test)"

    def __init__(
        self, size: tuple[int, int] = (64, 48), fail_opens: int = 0, fail_after: int | None = None
    ) -> None:
        self.size = size
        self.fail_opens = fail_opens
        self.fail_after = fail_after
        self.opens = 0
        self.reads = 0
        self.closed = 0
        self._open = False

    def open(self) -> bool:
        self.opens += 1
        if self.opens <= self.fail_opens:
            return False
        self._open = True
        return True

    def read(self) -> tuple[bool, np.ndarray | None]:
        if not self._open or (self.fail_after is not None and self.reads >= self.fail_after):
            return False, None
        self.reads += 1
        w, h = self.size
        return True, np.full((h, w, 3), self.reads % 256, np.uint8)

    def close(self) -> None:
        self._open = False
        self.closed += 1


class FakeFaceDetector:
    """FaceDetector that answers each frame synchronously with a scripted FaceObservation.

    `script(ts_ms, call_index)` returns the observation; the default reports no face.
    Use `FakeFaceDetector.factory(...)` where a DetectorFactory is expected.
    """

    def __init__(self, on_observation, script=None) -> None:
        from app.services.face import FaceObservation

        self._cb = on_observation
        self._script = script or (lambda ts, i: FaceObservation(ts_ms=ts, face_present=False))
        self.timestamps: list[int] = []
        self.closed = False

    @classmethod
    def factory(cls, script=None, created: list | None = None):
        def make(_model_path, on_observation):
            det = cls(on_observation, script)
            if created is not None:
                created.append(det)
            return det

        return make

    def detect_async(self, bgr: np.ndarray, ts_ms: int) -> None:
        if self.timestamps and ts_ms <= self.timestamps[-1]:
            raise ValueError("timestamps must be strictly increasing (MediaPipe contract)")
        self.timestamps.append(ts_ms)
        self._cb(self._script(ts_ms, len(self.timestamps) - 1))

    def close(self) -> None:
        self.closed = True


class FakeGestureRecognizer:
    """GestureRecognizer that answers each frame with scripted HandReadings.

    `script(ts_ms, call_index)` returns a list of HandReading; the default sees no hands.
    """

    def __init__(self, on_readings, script=None) -> None:
        self._cb = on_readings
        self._script = script or (lambda ts, i: [])
        self.timestamps: list[int] = []
        self.closed = False

    @classmethod
    def factory(cls, script=None, created: list | None = None):
        def make(_model_path, on_readings):
            rec = cls(on_readings, script)
            if created is not None:
                created.append(rec)
            return rec

        return make

    def recognize_async(self, bgr: np.ndarray, ts_ms: int) -> None:
        if self.timestamps and ts_ms <= self.timestamps[-1]:
            raise ValueError("timestamps must be strictly increasing (MediaPipe contract)")
        self.timestamps.append(ts_ms)
        self._cb(self._script(ts_ms, len(self.timestamps) - 1), ts_ms)

    def close(self) -> None:
        self.closed = True
