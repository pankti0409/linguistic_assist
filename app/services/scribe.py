"""ScribeService (section 8.5): laptop mic -> pause segmentation -> ElevenLabs Scribe (batch).

Batch transcription only for now; the realtime socket comes later (D-030). To get fragments
across pauses from a batch API, mic audio is cut into utterances at pauses with a simple
energy segmenter, and each utterance is transcribed on its own. Audio stays in memory and is
dropped right after its request (R8). The transcript is never post-processed: the raw text
is kept for WER scoring.
"""

from __future__ import annotations

import logging
import math
import sys
import threading
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np

from app.config import Settings
from app.core.consent import ConsentRegistry
from app.core.events import EventBus
from app.core.health import HealthRegistry
from app.core.timing import now_ms
from app.schemas import SpeechEvidence

log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
FRAME_MS = 30
FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000 * 2  # int16 mono
SCRIBE_MODEL = "scribe_v2"  # ElevenLabs models page, checked 2026-10-31
LOW_CONFIDENCE = 0.4
SHORT_FINAL_CHARS = 2

# --- segmentation -----------------------------------------------------------


def frame_dbfs(frame: bytes) -> float:
    a = np.frombuffer(frame, dtype=np.int16).astype(np.float64)
    if a.size == 0:
        return -120.0
    rms = math.sqrt(float(np.mean(a * a)))
    return 20 * math.log10(max(rms, 1e-9) / 32768.0)


@dataclass
class Segment:
    pcm: bytes
    start_ms: int  # monotonic time of the first voiced frame
    end_ms: int


@dataclass
class Segmenter:
    """Energy VAD that cuts utterances at pauses (D-031).

    Voice starts after `start_frames` loud frames; an utterance ends after `silence_ms` of
    quiet frames; utterances shorter than `min_ms` are dropped. The noise floor adapts on
    quiet frames, and a voiced frame must be `margin_db` above it (and above `abs_min_db`).
    """

    silence_ms: int = 700
    start_frames: int = 3
    min_ms: int = 250
    max_ms: int = 15_000
    preroll_ms: int = 240
    margin_db: float = 12.0
    abs_min_db: float = -50.0
    floor_db: float = -60.0
    _buf: bytearray = field(default_factory=bytearray)
    _pre: deque = field(default_factory=lambda: deque(maxlen=8))
    _cur: bytearray | None = None
    _loud_run: int = 0
    _quiet_run: int = 0
    _voiced: int = 0  # voiced frames in the open utterance
    _start_ms: int = 0
    _t_ms: int = 0

    def __post_init__(self) -> None:
        self._pre = deque(maxlen=max(1, self.preroll_ms // FRAME_MS))

    @property
    def threshold_db(self) -> float:
        return max(self.floor_db + self.margin_db, self.abs_min_db)

    @property
    def in_speech(self) -> bool:
        return self._cur is not None

    def feed(self, pcm: bytes, t_ms: int | None = None) -> tuple[list[Segment], bool]:
        """Feed raw int16 audio. Returns (finished segments, any voiced frame seen)."""
        if t_ms is not None:
            self._t_ms = t_ms
        self._buf.extend(pcm)
        out: list[Segment] = []
        voiced_any = False
        while len(self._buf) >= FRAME_BYTES:
            frame = bytes(self._buf[:FRAME_BYTES])
            del self._buf[:FRAME_BYTES]
            self._t_ms += FRAME_MS
            db = frame_dbfs(frame)
            loud = db > self.threshold_db
            voiced_any |= loud
            if self._cur is None:
                if not loud:  # adapt the floor only on quiet frames
                    self.floor_db = 0.95 * self.floor_db + 0.05 * db
                self._pre.append(frame)
                self._loud_run = self._loud_run + 1 if loud else 0
                if self._loud_run >= self.start_frames:
                    self._cur = bytearray(b"".join(self._pre))
                    self._start_ms = self._t_ms - len(self._pre) * FRAME_MS
                    self._quiet_run = 0
                    self._voiced = self._loud_run
                continue
            self._cur.extend(frame)
            self._quiet_run = 0 if loud else self._quiet_run + 1
            self._voiced += 1 if loud else 0
            dur = len(self._cur) // 2 * 1000 // SAMPLE_RATE
            if self._quiet_run * FRAME_MS >= self.silence_ms or dur >= self.max_ms:
                seg = self._close()
                if seg:
                    out.append(seg)
        return out, voiced_any

    def flush(self) -> list[Segment]:
        seg = self._close() if self._cur is not None else None
        return [seg] if seg else []

    def _close(self) -> Segment | None:
        pcm = bytes(self._cur or b"")
        voiced_ms = self._voiced * FRAME_MS
        self._cur, self._loud_run, self._quiet_run, self._voiced = None, 0, 0, 0
        self._pre.clear()
        dur = len(pcm) // 2 * 1000 // SAMPLE_RATE
        if voiced_ms < self.min_ms:  # judged on voiced audio, not preroll or trailing quiet
            return None
        return Segment(pcm=pcm, start_ms=self._start_ms, end_ms=self._start_ms + dur)


# --- adapters ----------------------------------------------------------------


def _select_mic_device(configured, devices, platform: str):
    """Respect explicit selection; avoid a Bluetooth default on Mac laptops."""
    if configured is not None and str(configured).strip():
        value = str(configured).strip()
        return int(value) if value.isdigit() else value
    if platform == "darwin":
        for index, device in enumerate(devices):
            name = device["name"].lower()
            if device["max_input_channels"] > 0 and (
                ("macbook" in name and "microphone" in name)
                or ("built-in" in name and ("microphone" in name or "input" in name))
            ):
                return index
    return None


class SounddeviceMic:
    """Laptop mic, 16 kHz mono int16. Audio goes straight to the callback, never to disk."""

    def __init__(self, device: str | int | None = None) -> None:
        self._stream = None
        self._device = device
        self.device_name = "default input"

    def start(self, on_audio: Callable[[bytes], None]) -> None:
        import sounddevice as sd

        device = _select_mic_device(self._device, sd.query_devices(), sys.platform)
        self.device_name = sd.query_devices(device, kind="input")["name"]

        def cb(indata, frames, time_info, status):  # noqa: ARG001
            on_audio(bytes(indata))

        self._stream = sd.RawInputStream(
            device=device,
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=FRAME_BYTES // 2,
            callback=cb,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None


class ElevenLabsScribe:
    """SpeechToText over ElevenLabs Scribe v2 batch (elevenlabs SDK 2.75 signature)."""

    def __init__(self, api_key: str, model_id: str = SCRIBE_MODEL) -> None:
        from elevenlabs.client import ElevenLabs

        self._client = ElevenLabs(api_key=api_key)
        self.model_id = model_id

    def transcribe(
        self, pcm16: bytes, sample_rate: int, language: str | None = None
    ) -> SpeechEvidence:
        if sample_rate != SAMPLE_RATE:
            raise ValueError("pcm_s16le_16 requires 16 kHz mono int16")
        kwargs = {}
        if language:
            kwargs["language_code"] = language
        res = self._client.speech_to_text.convert(
            model_id=self.model_id,
            file=("segment.pcm", pcm16, "application/octet-stream"),
            file_format="pcm_s16le_16",
            timestamps_granularity="word",
            tag_audio_events=False,
            **kwargs,
        )
        words = [w for w in (res.words or []) if getattr(w, "type", "word") == "word"]
        conf = None
        if words:
            conf = round(math.exp(sum(w.logprob for w in words) / len(words)), 4)
        return SpeechEvidence(
            text=res.text or "", is_final=True, language=res.language_code, confidence=conf
        )


# --- service -------------------------------------------------------------------

FinalCallback = Callable[[SpeechEvidence, Segment], None]


class ScribeService:
    def __init__(
        self,
        settings: Settings,
        bus: EventBus,
        health: HealthRegistry,
        consent: ConsentRegistry,
        stt=None,
        mic_factory: Callable[[], object] | None = None,
    ) -> None:
        self._s = settings
        self._bus = bus
        self._health = health
        self._consent = consent
        self._stt = stt
        self._backend = "fake" if stt is not None else "real"
        self._mic_factory = mic_factory or (lambda: SounddeviceMic(settings.mic_device))
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="scribe")  # keeps order
        self._lock = threading.Lock()
        self._mic = None
        self._mic_name = ""
        self._seg: Segmenter | None = None
        self._pending: list[Future] = []
        self._on_final: FinalCallback | None = None
        self._on_activity: Callable[[], None] | None = None
        self._speaker = "PATIENT"
        self._language: str | None = None
        if stt is not None:
            health.set("scribe", "ok", "fake transcriber", backend="fake")
        elif settings.elevenlabs_api_key:
            health.set("scribe", "degraded", f"{SCRIBE_MODEL} configured; not yet called")
        else:
            health.set("scribe", "unavailable", "ELEVENLABS_API_KEY not set")

    @property
    def active(self) -> bool:
        return self._mic is not None

    @property
    def busy(self) -> bool:
        """True while an utterance is open or a transcription is still pending."""
        with self._lock:
            open_utt = self._seg is not None and self._seg.in_speech
            return open_utt or any(not f.done() for f in self._pending)

    def _client(self):
        if self._stt is None:
            if not self._s.elevenlabs_api_key:
                raise RuntimeError("ELEVENLABS_API_KEY not set")
            self._stt = ElevenLabsScribe(self._s.elevenlabs_api_key)
        return self._stt

    def start(
        self,
        speaker: str,
        language: str | None,
        on_final: FinalCallback,
        on_activity: Callable[[], None] | None = None,
    ) -> None:
        self._consent.require("microphone")  # R3
        with self._lock:
            if self._mic is not None:
                raise RuntimeError("microphone already capturing")
            self._seg = Segmenter()
            self._seg._t_ms = now_ms()  # segment times on the monotonic clock
            self._pending = []
            self._on_final, self._on_activity = on_final, on_activity
            self._speaker, self._language = speaker, language
            mic = self._mic_factory()
            mic.start(self._on_audio)
            self._mic = mic
            self._mic_name = getattr(mic, "device_name", "injected microphone")
            self._health.set(
                "scribe",
                "ok" if self._backend == "fake" else "degraded",
                f"listening: {self._mic_name}; awaiting transcription",
                backend=self._backend,
            )

    def stop(self, timeout_s: float = 15.0) -> list[SpeechEvidence]:
        """Stop the mic, transcribe the last utterance, and wait for every pending result."""
        with self._lock:
            mic, self._mic = self._mic, None
        if mic is not None:
            mic.stop()
        with self._lock:
            tail = self._seg.flush() if self._seg else []
            for seg in tail:
                self._pending.append(self._pool.submit(self._transcribe, seg))
            pending = list(self._pending)
            self._pending = []
        results: list[SpeechEvidence] = []
        for f in pending:
            try:
                ev = f.result(timeout=timeout_s)
                if ev is not None:
                    results.append(ev)
            except Exception:
                log.exception("transcription wait failed")
        return results

    def _on_audio(self, pcm: bytes) -> None:
        with self._lock:
            seg = self._seg
            if seg is None:
                return
            segments, voiced = seg.feed(pcm, None)
            for s in segments:
                self._pending.append(self._pool.submit(self._transcribe, s))
        if voiced and self._on_activity:
            self._on_activity()

    def _transcribe(self, seg: Segment) -> SpeechEvidence | None:
        lang = None if self._language in (None, "", "auto", "mixed") else self._language
        try:
            ev = self._client().transcribe(seg.pcm, SAMPLE_RATE, lang)
        except Exception as exc:
            log.warning("scribe failed: %s", type(exc).__name__)
            self._health.set(
                "scribe",
                "unavailable",
                f"last call failed: {type(exc).__name__}",
                backend=self._backend,
            )
            self._bus.publish(
                "error", {"source": "scribe", "error": type(exc).__name__, "recoverable": True}
            )
            return None
        finally:
            seg.pcm = b""  # drop the audio as soon as the request is done (R8)
        self._health.set(
            "scribe", "ok", f"{SCRIBE_MODEL} batch; input: {self._mic_name}; last call ok",
            backend=self._backend,
        )
        self._bus.publish(
            "speech.final",
            {
                "speaker": self._speaker,
                "text": ev.text,
                "language": ev.language,
                "confidence": ev.confidence,
                "duration_ms": seg.end_ms - seg.start_ms,
            },
        )
        if self._on_final:
            try:
                self._on_final(ev, seg)
            except Exception:
                log.exception("speech final callback failed")
        return ev

    def transcribe_once(self, pcm16: bytes, language: str | None = None) -> SpeechEvidence:
        """Direct batch call (evaluation harness). Audio is not kept."""
        return self._client().transcribe(pcm16, SAMPLE_RATE, language)

    def shutdown(self) -> None:
        if self._mic is not None:
            self.stop(timeout_s=1)
        self._pool.shutdown(wait=False, cancel_futures=True)


def is_low_confidence(ev: SpeechEvidence) -> bool:
    text = ev.text.strip()
    if len(text) <= SHORT_FINAL_CHARS:
        return True
    return ev.confidence is not None and ev.confidence < LOW_CONFIDENCE
