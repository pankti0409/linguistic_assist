"""GestureService (section 8.3): MediaPipe GestureRecognizer -> debounce -> lexicon -> words.

Token key is `Label|Left` or `Label|Right`. Handedness is the subject's own hand; frames
are passed unmirrored, as OpenCV delivers them (D-018). Unmapped tokens are ignored, never
guessed.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.config import ROOT, Settings
from app.core.consent import ConsentRegistry
from app.core.errors import AppError, ServiceUnavailableError
from app.core.events import EventBus
from app.core.health import HealthRegistry
from app.schemas import GestureWord
from app.services.camera import CameraHub

log = logging.getLogger(__name__)

LABELS = (
    "Closed_Fist",
    "Open_Palm",
    "Pointing_Up",
    "Thumb_Down",
    "Thumb_Up",
    "Victory",
    "ILoveYou",
)
HANDS = ("Left", "Right")
RESERVED = ("__COMMIT__", "__CLEAR__")
REPEAT_HOLD_S = 1.5
DEFAULT_LEXICON = {"Thumb_Up|*": "yes", "Thumb_Down|*": "no", "Open_Palm|*": "wait"}
_TOKEN_RE = re.compile(rf"^({'|'.join(LABELS)})\|(Left|Right|\*)$")


@dataclass(frozen=True)
class HandReading:
    """One recognised hand in one frame."""

    hand: str  # "Left" | "Right" (subject's hand)
    label: str  # MediaPipe canned label, "None" when no gesture
    score: float


@dataclass(frozen=True)
class GestureToken:
    token: str
    score: float  # mean score over the stable run
    ts_ms: int


# --- debouncer -----------------------------------------------------------


class _HandState:
    def __init__(self) -> None:
        self.label: str | None = None
        self.run = 0
        self.scores: list[float] = []
        self.clock: float | None = None  # last emission (or blocked repeat) in this run
        self.armed = True  # a return to None re-arms the same token


class Debouncer:
    """Emit one token per stable gesture (section 8.3).

    A gesture is stable when the same label on the same hand is seen for `stable_frames`
    consecutive frames, each with score >= `min_score`. The same token repeats only after
    the hand returns to None (or leaves the frame) and the gesture is shown again, or after
    it is held for `hold_s` more seconds. A weak frame breaks the run but does not re-arm,
    so a flicker cannot fake a repeat.
    """

    def __init__(self, stable_frames: int, min_score: float, hold_s: float = REPEAT_HOLD_S):
        self.stable_frames = stable_frames
        self.min_score = min_score
        self.hold_s = hold_s
        self._hands = {h: _HandState() for h in HANDS}
        self._last_token: dict[str, str] = {}

    def update(
        self, readings: list[HandReading], ts_ms: int, now_s: float | None = None
    ) -> list[GestureToken]:
        now_s = time.monotonic() if now_s is None else now_s
        seen = {r.hand: r for r in readings if r.hand in HANDS}
        out: list[GestureToken] = []
        for hand, st in self._hands.items():
            r = seen.get(hand)
            if r is None or r.label not in LABELS:  # gone or "None": re-arm
                st.label, st.run, st.scores, st.clock, st.armed = None, 0, [], None, True
                self._last_token.pop(hand, None)
                continue
            if r.score < self.min_score:
                st.label, st.run, st.scores, st.clock = None, 0, [], None
                continue
            if r.label != st.label:
                st.label, st.run, st.scores, st.clock = r.label, 0, [], None
            st.run += 1
            st.scores.append(r.score)
            token = f"{r.label}|{hand}"
            if st.clock is None and st.run >= self.stable_frames:
                if st.armed or self._last_token.get(hand) != token:
                    out.append(self._emit(st, token, ts_ms, now_s, hand))
                else:
                    st.clock = now_s  # blocked repeat: start the hold clock instead
            elif st.clock is not None and now_s - st.clock >= self.hold_s:
                out.append(self._emit(st, token, ts_ms, now_s, hand))
        return out

    def _emit(
        self, st: _HandState, token: str, ts_ms: int, now_s: float, hand: str
    ) -> GestureToken:
        score = float(np.mean(st.scores[-self.stable_frames :]))
        st.clock, st.armed = now_s, False
        self._last_token[hand] = token
        return GestureToken(token=token, score=round(score, 3), ts_ms=ts_ms)


# --- lexicon -------------------------------------------------------------


class InvalidLexiconError(AppError):
    status_code = 422
    error_code = "invalid_lexicon"
    recoverable = True


class Lexicon:
    """token -> word map stored in calibration/{user}.json. `Label|*` matches either hand."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._map: dict[str, str] = dict(DEFAULT_LEXICON)
        if path.is_file():
            self._map = self.validate(json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def validate(mapping: dict) -> dict[str, str]:
        if not isinstance(mapping, dict):
            raise InvalidLexiconError("lexicon must be an object of token -> word")
        clean: dict[str, str] = {}
        for token, word in mapping.items():
            if not isinstance(token, str) or not _TOKEN_RE.match(token):
                raise InvalidLexiconError(
                    f"bad token '{token}'; expected Label|Left, Label|Right or Label|* "
                    f"with Label in {', '.join(LABELS)}"
                )
            if not isinstance(word, str) or not word.strip():
                raise InvalidLexiconError(f"word for '{token}' must be a non-empty string")
            if word.startswith("__") and word not in RESERVED:
                raise InvalidLexiconError(f"unknown reserved word '{word}'")
            clean[token] = word.strip()
        return clean

    def lookup(self, token: str) -> str | None:
        label = token.split("|", 1)[0]
        with self._lock:
            return self._map.get(token) or self._map.get(f"{label}|*")

    def all(self) -> dict[str, str]:
        with self._lock:
            return dict(self._map)

    def replace(self, mapping: dict) -> dict[str, str]:
        clean = self.validate(mapping)
        with self._lock:
            self._map = clean
        self._save()
        return self.all()

    def bind(self, token: str, word: str) -> dict[str, str]:
        with self._lock:
            new = {**self._map, token: word}
        return self.replace(new)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.all(), indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)


# --- MediaPipe adapter ---------------------------------------------------

ReadingsCallback = Callable[[list[HandReading], int], None]


class MediaPipeGestureRecognizer:
    def __init__(self, model_path: Path, on_readings: ReadingsCallback) -> None:
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        self._mp = mp
        self._cb = on_readings
        options = vision.GestureRecognizerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.LIVE_STREAM,
            num_hands=2,
            result_callback=self._on_result,
        )
        self._rec = vision.GestureRecognizer.create_from_options(options)

    def recognize_async(self, bgr: np.ndarray, ts_ms: int) -> None:
        rgb = np.ascontiguousarray(bgr[:, :, ::-1])  # unmirrored on purpose (D-018)
        self._rec.recognize_async(self._mp.Image(self._mp.ImageFormat.SRGB, rgb), ts_ms)

    def close(self) -> None:
        self._rec.close()

    def _on_result(self, result, _image, ts_ms: int) -> None:
        self._cb(self.convert(result), ts_ms)

    @staticmethod
    def convert(result) -> list[HandReading]:
        readings = []
        for gestures, handed in zip(result.gestures or [], result.handedness or [], strict=False):
            if not gestures or not handed:
                continue
            g, h = gestures[0], handed[0]
            readings.append(
                HandReading(hand=h.category_name, label=g.category_name or "None", score=g.score)
            )
        return readings


RecognizerFactory = Callable[[Path, ReadingsCallback], object]
WordCallback = Callable[[GestureWord], None]


class GestureService:
    def __init__(
        self,
        settings: Settings,
        hub: CameraHub,
        bus: EventBus,
        health: HealthRegistry,
        consent: ConsentRegistry,
        recognizer_factory: RecognizerFactory | None = None,
        lexicon_path: Path | None = None,
    ) -> None:
        self._s = settings
        self._hub = hub
        self._bus = bus
        self._health = health
        self._consent = consent
        self._factory = recognizer_factory or MediaPipeGestureRecognizer
        self._backend = "real" if recognizer_factory is None else "fake"
        self.model_path = ROOT / "assets" / "gesture_recognizer.task"
        self.lexicon = Lexicon(lexicon_path or ROOT / "calibration" / "default.json")
        self.debouncer = Debouncer(settings.gesture_stable_frames, settings.gesture_min_score)
        self._lock = threading.Lock()
        self._word_subs: list[WordCallback] = []
        self._calibration: tuple[threading.Event, list[GestureToken]] | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._rec = None
        self._last_sent_ts = -1

    def start(self) -> bool:
        self._consent.require("camera")
        if self.running:
            return True
        if self._backend == "real" and not self.model_path.is_file():
            self._health.set(
                "gesture", "unavailable", "gesture_recognizer.task missing; run download_models"
            )
            return False
        try:
            self._rec = self._factory(self.model_path, self._on_readings)
        except Exception as exc:
            log.exception("gesture recognizer failed to load")
            self._health.set("gesture", "unavailable", f"load failed: {type(exc).__name__}")
            return False
        self.debouncer = Debouncer(self._s.gesture_stable_frames, self._s.gesture_min_score)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="GestureService", daemon=True)
        self._thread.start()
        self._health.set("gesture", "ok", "running", backend=self._backend)
        return True

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout)
        if self._rec is not None:
            try:
                self._rec.close()
            except Exception:
                log.exception("gesture recognizer close failed")
            self._rec = None
        self._health.set("gesture", "unavailable", "stopped", backend=self._backend)

    @property
    def running(self) -> bool:
        t = self._thread
        return bool(t and t.is_alive())

    def subscribe_words(self, cb: WordCallback) -> None:
        with self._lock:
            self._word_subs.append(cb)

    def calibrate(self, word: str, timeout_s: float | None = None) -> dict:
        """Block until the next stable token (up to CALIBRATE_TIMEOUT_S), then bind it."""
        timeout_s = self._s.calibrate_timeout_s if timeout_s is None else timeout_s
        if not self.running:
            raise ServiceUnavailableError("gesture service is not running; grant camera consent")
        self.lexicon.validate({"Thumb_Up|*": word})  # validates the word only
        done: threading.Event = threading.Event()
        got: list[GestureToken] = []
        with self._lock:
            self._calibration = (done, got)
        try:
            if not done.wait(timeout_s):
                raise CalibrationTimeoutError(f"no stable gesture within {timeout_s:.0f} s")
        finally:
            with self._lock:
                self._calibration = None
        return {
            "token": got[0].token,
            "word": word,
            "lexicon": self.lexicon.bind(got[0].token, word),
        }

    def _run(self) -> None:
        period = 1.0 / max(1, self._s.vision_fps)
        while not self._stop.is_set():
            t0 = time.monotonic()
            frame = self._hub.latest()
            if frame is not None and frame.ts_ms > self._last_sent_ts:
                self._last_sent_ts = frame.ts_ms
                try:
                    self._rec.recognize_async(frame.image, frame.ts_ms)  # type: ignore[union-attr]
                except Exception as exc:
                    log.warning("recognize_async failed: %s", type(exc).__name__)
            self._stop.wait(max(0.0, period - (time.monotonic() - t0)))

    def _on_readings(self, readings: list[HandReading], ts_ms: int) -> None:
        if self._stop.is_set():
            return
        for tok in self.debouncer.update(readings, ts_ms):
            self.handle_token(tok)

    def handle_token(self, tok: GestureToken) -> None:
        self._bus.publish(
            "gesture.token", {"token": tok.token, "score": tok.score, "ts_ms": tok.ts_ms}
        )
        with self._lock:
            cal = self._calibration
            if cal is not None:
                self._calibration = None
        if cal is not None:  # calibration captures the token instead of producing a word
            cal[1].append(tok)
            cal[0].set()
            return
        word = self.lexicon.lookup(tok.token)
        if word is None:
            return  # unmapped tokens are ignored, never guessed
        gw = GestureWord(word=word, token=tok.token, score=tok.score, ts_ms=tok.ts_ms)
        self._bus.publish("gesture.word", gw.model_dump())
        with self._lock:
            subs = list(self._word_subs)
        for cb in subs:
            try:
                cb(gw)
            except Exception:
                log.exception("gesture word subscriber failed")


class CalibrationTimeoutError(AppError):
    status_code = 408
    error_code = "calibration_timeout"
    recoverable = True
