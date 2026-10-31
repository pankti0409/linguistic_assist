"""CameraHub (section 8.1): the one thread that owns the webcam (R1).

Frames live in memory only (R8): the latest frame plus a ~1 s deque. Subscribers read by
polling `latest()`/`recent()` or by callback, and downscale on their own side. A missing or
busy camera never crashes the app: the hub publishes `camera.status{ok:false}` and retries
with backoff.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from app.adapters.interfaces import FrameSource
from app.config import Settings
from app.core.consent import ConsentRegistry
from app.core.events import EventBus
from app.core.health import HealthRegistry
from app.core.timing import now_ms

log = logging.getLogger(__name__)

FALLBACK_INDICES = (0, 1, 2)  # R1: integrated webcam is index 0; 1-2 only as fallback
READ_FAILS_BEFORE_REOPEN = 15


@dataclass(frozen=True)
class Frame:
    seq: int
    ts_ms: int  # monotonic, strictly increasing within one hub
    image: np.ndarray  # BGR uint8, as OpenCV delivers it


class OpenCVCamera:
    """FrameSource over the laptop webcam. Uses CAP_DSHOW on Windows."""

    def __init__(self, indices: Sequence[int], size: tuple[int, int], fps: int) -> None:
        self.indices = tuple(indices)
        self.size = size
        self.fps = fps
        self.opened_index: int | None = None
        self._cap = None

    def open(self) -> bool:
        import cv2

        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        for idx in self.indices:
            cap = cv2.VideoCapture(idx, backend)
            if not cap.isOpened():
                cap.release()
                continue
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.size[0])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.size[1])
            cap.set(cv2.CAP_PROP_FPS, self.fps)
            ok, _ = cap.read()
            if ok:
                self._cap, self.opened_index = cap, idx
                return True
            cap.release()
        return False

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self._cap is None:
            return False, None
        ok, frame = self._cap.read()
        return (True, frame) if ok else (False, None)

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            self.opened_index = None


def camera_indices(source: str) -> tuple[int, ...]:
    first = int(source)
    return (first, *[i for i in FALLBACK_INDICES if i != first])


def make_source(settings: Settings) -> FrameSource:
    src = settings.camera_source
    if src.isdigit():
        return OpenCVCamera(camera_indices(src), settings.camera_size, settings.camera_fps)
    if not settings.simulate:
        raise ValueError("CAMERA_SOURCE may be a video file only when SIMULATE=1 (R1)")
    from app.adapters.fakes import VideoFileCamera  # lazy: fakes imports services

    return VideoFileCamera(src)


def describe(source: FrameSource) -> str:
    if isinstance(source, OpenCVCamera):
        return f"webcam index {source.opened_index}"
    return getattr(source, "description", type(source).__name__)


FrameCallback = Callable[[Frame], None]


class CameraHub:
    def __init__(
        self,
        settings: Settings,
        bus: EventBus,
        health: HealthRegistry,
        consent: ConsentRegistry,
        source_factory: Callable[[], FrameSource] | None = None,
        backoff_s: Sequence[float] = (0.5, 1.0, 2.0, 5.0),
    ) -> None:
        self._settings = settings
        self._bus = bus
        self._health = health
        self._consent = consent
        self._factory = source_factory or (lambda: make_source(settings))
        self._backoff = tuple(backoff_s)
        self._backend = "real" if source_factory is None and not settings.simulate else "fake"
        self._lock = threading.Lock()
        self._latest: Frame | None = None
        self._recent: deque[Frame] = deque(maxlen=max(1, settings.camera_fps))
        self._callbacks: list[FrameCallback] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._seq = 0
        self._last_ts = -1
        self.fps_measured = 0.0

    # --- lifecycle -------------------------------------------------------

    def start(self) -> None:
        self._consent.require("camera")  # R3
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="CameraHub", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        t = self._thread
        if t and t is not threading.current_thread():
            t.join(timeout)
        with self._lock:
            self._latest = None
            self._recent.clear()  # drop frames from memory as soon as the camera stops

    @property
    def running(self) -> bool:
        t = self._thread
        return bool(t and t.is_alive())

    # --- consumers -------------------------------------------------------

    def latest(self) -> Frame | None:
        with self._lock:
            return self._latest

    def recent(self) -> list[Frame]:
        with self._lock:
            return list(self._recent)

    def subscribe(self, cb: FrameCallback) -> None:
        with self._lock:
            self._callbacks.append(cb)

    def unsubscribe(self, cb: FrameCallback) -> None:
        with self._lock:
            if cb in self._callbacks:
                self._callbacks.remove(cb)

    # --- thread ----------------------------------------------------------

    def _status(self, ok: bool, detail: str, **extra: object) -> None:
        self._bus.publish("camera.status", {"ok": ok, "detail": detail, **extra})
        self._health.set("camera", "ok" if ok else "unavailable", detail, backend=self._backend)

    def _run(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                source = self._factory()
                opened = source.open()
            except Exception as exc:  # misconfiguration or driver error: report, retry
                log.warning("camera open raised %s", type(exc).__name__)
                source, opened = None, False
            if not opened:
                wait = self._backoff[min(attempt, len(self._backoff) - 1)]
                attempt += 1
                self._status(False, "camera busy or missing", retry_in_s=wait, attempt=attempt)
                if self._stop.wait(wait):
                    break
                continue
            attempt = 0
            self._status(True, describe(source))
            try:
                self._pump(source)
            finally:
                source.close()
        self._status(False, "stopped")

    def _pump(self, source: FrameSource) -> None:
        period = 1.0 / max(1, self._settings.camera_fps)
        fails = 0
        next_t = time.monotonic()
        window: deque[float] = deque(maxlen=30)
        while not self._stop.is_set():
            try:
                ok, image = source.read()
            except Exception:
                ok, image = False, None
            if not ok or image is None:
                fails += 1
                if fails >= READ_FAILS_BEFORE_REOPEN:
                    self._status(False, "camera stopped delivering frames; reopening")
                    return
                self._stop.wait(period)
                continue
            fails = 0
            self._emit(image)
            now = time.monotonic()
            window.append(now)
            if len(window) > 1:
                self.fps_measured = (len(window) - 1) / max(1e-6, window[-1] - window[0])
            # pace to CAMERA_FPS (a real webcam already blocks in read(); a file does not)
            next_t = max(next_t + period, now - period)
            delay = next_t - time.monotonic()
            if delay > 0 and self._stop.wait(delay):
                return

    def _emit(self, image: np.ndarray) -> None:
        ts = max(now_ms(), self._last_ts + 1)  # strictly increasing for MediaPipe
        self._last_ts = ts
        self._seq += 1
        frame = Frame(seq=self._seq, ts_ms=ts, image=image)
        with self._lock:
            self._latest = frame
            self._recent.append(frame)
            callbacks = list(self._callbacks)
        for cb in callbacks:
            try:
                cb(frame)
            except Exception:
                log.exception("camera subscriber failed")
