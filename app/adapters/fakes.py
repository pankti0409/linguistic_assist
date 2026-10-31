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
        self.voices: list[str] = []

    def synthesize(self, text: str, voice_id: str, output_format: str = "mp3_44100_128") -> bytes:
        if self.fail:
            raise ConnectionError("FakeTTS configured to fail")
        self.spoken.append(text)
        self.voices.append(voice_id)
        return b"\x00\x00" * 160 * max(1, len(text.split()))


class FakeAvatar:
    """AvatarTransport stand-in. Records every app message and, like the Tavus PAL, answers
    an echo with started_speaking unless told to stay silent for that modality."""

    def __init__(self, silent_modalities: tuple[str, ...] = (), fail_join: bool = False):
        self.silent = set(silent_modalities)
        self.fail_join = fail_join
        self.sent: list[dict] = []
        self.joined: list[str] = []
        self.left = 0
        self._cb = None

    def join(self, conversation_url: str, on_message) -> None:
        if self.fail_join:
            raise ConnectionError("FakeAvatar join refused")
        self.joined.append(conversation_url)
        self._cb = on_message

    def send(self, message: dict) -> None:
        self.sent.append(message)
        props = message.get("properties") or {}
        if message.get("event_type") == "conversation.echo" and props.get("done", True):
            if props.get("modality", "text") not in self.silent and self._cb:
                self._cb({"event_type": "conversation.replica.started_speaking"})

    def leave(self) -> None:
        self.left += 1

    def echoes(self, modality: str | None = None) -> list[dict]:
        out = [m for m in self.sent if m.get("event_type") == "conversation.echo"]
        if modality:
            out = [m for m in out if m["properties"].get("modality") == modality]
        return out


class FakeTavusAPI:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.created: list[dict] = []
        self.ended: list[str] = []

    def create_conversation(self, body: dict) -> dict:
        if self.fail:
            raise ConnectionError("FakeTavusAPI down")
        self.created.append(body)
        cid = f"c{len(self.created):04d}"
        return {
            "conversation_id": cid,
            "conversation_url": f"https://tavus.daily.co/{cid}",
            "status": "active",
        }

    def end_conversation(self, conversation_id: str) -> None:
        self.ended.append(conversation_id)


@dataclass
class FakeLipReader:
    """Scripted lip reader. Default is `unavailable`, matching a missing checkpoint."""

    result: LipEvidence = field(default_factory=lambda: LipEvidence(status="unavailable"))
    available: bool = False
    calls: list[int] = field(default_factory=list)

    def read(self, frames: Sequence[np.ndarray], landmarks: Sequence = ()) -> LipEvidence:
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


def tone(ms: int, freq: float = 220.0, amp: float = 0.3, rate: int = 16_000) -> bytes:
    """Synthetic int16 sine burst (a stand-in for voiced audio in tests)."""
    n = int(rate * ms / 1000)
    x = amp * np.sin(2 * np.pi * freq * np.arange(n) / rate)
    return (x * 32767).astype(np.int16).tobytes()


def silence(ms: int, rate: int = 16_000) -> bytes:
    return np.zeros(int(rate * ms / 1000), np.int16).tobytes()


class FakeMic:
    """Feeds scripted int16 audio to the callback in 30 ms blocks from a thread.

    `realtime=True` paces it like a real mic, which the draft silence timer needs.
    """

    def __init__(self, audio: bytes = b"", realtime: bool = False) -> None:
        import threading

        self.audio = audio
        self.realtime = realtime
        self._stop = threading.Event()
        self._thread = None
        self.started = 0

    def start(self, on_audio) -> None:
        import threading
        import time

        self.started += 1
        self._stop.clear()

        def run():
            block = 960  # 30 ms of int16 at 16 kHz
            for i in range(0, len(self.audio), block):
                if self._stop.is_set():
                    return
                on_audio(self.audio[i : i + block])
                if self.realtime:
                    time.sleep(0.03)

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def wait_done(self, timeout: float = 10.0) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(2)


class SimulatedLLM:
    """SIMULATE=1 stand-in for Groq. It builds two candidates from the cleaned fragments
    only, so it can never invent a word. Health and events label it as a fake."""

    def complete_json(self, system: str, user: str, *, temperature: float, max_tokens: int):
        import json

        p = json.loads(user)
        ids = [f["id"] for f in p["fragments"] if "filler" not in f["flags"]]
        text = " ".join(p["cleaned_fragments"]).strip()
        if not text:
            return json.dumps(
                {
                    "intent": "unclear",
                    "candidates": [],
                    "unexplained_fragment_ids": ids,
                    "clarifying_question": None,
                    "clarification_required": True,
                    "reasoning_summary": "simulated: no content",
                }
            )
        first = text[0].upper() + text[1:]
        return json.dumps(
            {
                "intent": "simulated",
                "candidates": [
                    {"text": f"{first}.", "covers": ids, "added_words": []},
                    {"text": f"{first}, please.", "covers": ids, "added_words": []},
                ],
                "unexplained_fragment_ids": [],
                "clarifying_question": None,
                "clarification_required": False,
                "reasoning_summary": "simulated reconstruction (SIMULATE=1, not an LLM)",
            }
        )


def simulation_overrides():
    """SIMULATE=1: the video-file camera with real MediaPipe, and labelled fakes for the mic,
    Scribe, LLM, TTS and Tavus. Nothing leaves the machine."""
    from app.main import Overrides

    return Overrides(
        stt=FakeScribe(),
        mic_factory=lambda: FakeMic(silence(500)),
        llm=SimulatedLLM(),
        tts=FakeTTS(),
        tavus_api=FakeTavusAPI(),
        avatar_transport_factory=FakeAvatar,
    )
