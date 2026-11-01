"""FaceService (section 8.2): MediaPipe FaceLandmarker in LIVE_STREAM mode.

A worker polls the CameraHub at VISION_FPS and sends only frames newer than the last one
sent (frame-skip, never a queue), so `detect_async` timestamps are strictly increasing.
Per result it derives lip landmarks, jawOpen / mouthClose, and yaw / pitch, then updates
`mouth_activity`. That is a movement cue only, never speech content.

API names were checked against the installed mediapipe 1.2.0 source (D-010).
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.config import Settings
from app.core.consent import ConsentRegistry
from app.core.events import EventBus
from app.core.health import HealthRegistry
from app.core.timing import now_ms
from app.services.camera import CameraHub

log = logging.getLogger(__name__)

HEARTBEAT_S = 1.0
FACE_ON_FRAMES = 2  # consecutive detections before face_present turns on
FACE_OFF_FRAMES = 5  # consecutive misses (~0.33 s at 15 fps) before it turns off


@dataclass(frozen=True)
class FaceObservation:
    ts_ms: int
    face_present: bool
    lip_points: np.ndarray | None = None  # (N, 2) normalised x, y in image coordinates
    jaw_open: float | None = None
    mouth_close: float | None = None
    yaw_deg: float | None = None
    pitch_deg: float | None = None
    # [right eye, left eye, nose tip, mouth centre], normalised; the 4 points Auto-AVSR's
    # own MediaPipe detector produces (see four_keypoints)
    keypoints: np.ndarray | None = None


ObservationCallback = Callable[[FaceObservation], None]


def yaw_pitch_from_matrix(m: np.ndarray) -> tuple[float, float]:
    """Yaw (about y) and pitch (about x) in degrees from a 4x4 facial transformation matrix.

    Uses R = Ry(yaw) @ Rx(pitch) ordering. Signs depend on the camera's mirroring, so
    callers gate on magnitude (|yaw| <= LIP_MAX_YAW_DEG), never on sign.
    """
    r = np.asarray(m, dtype=float)[:3, :3]
    # strip any uniform scale the matrix carries
    scale = np.linalg.norm(r[:, 0])
    if scale > 0:
        r = r / scale
    yaw = math.degrees(math.atan2(r[0, 2], r[2, 2]))
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, -r[1, 2]))))
    return yaw, pitch


class MouthActivity:
    """Windowed std of jawOpen / mouthClose, with hysteresis.

    Turns on above `on_std` and off below `off_std`.
    """

    def __init__(self, window: int, on_std: float, off_std: float) -> None:
        self._jaw: deque[float] = deque(maxlen=max(2, window))
        self._close: deque[float] = deque(maxlen=max(2, window))
        self.on_std, self.off_std = on_std, off_std
        self.active = False
        self.level = 0.0

    def reset(self) -> None:
        self._jaw.clear()
        self._close.clear()
        self.active = False
        self.level = 0.0

    def update(self, jaw_open: float, mouth_close: float) -> bool:
        """Feed one observation. Returns True when `active` flips."""
        self._jaw.append(jaw_open)
        self._close.append(mouth_close)
        if len(self._jaw) < self._jaw.maxlen:  # type: ignore[operator]
            return False
        self.level = float(max(np.std(self._jaw), np.std(self._close)))
        before = self.active
        if not self.active and self.level > self.on_std:
            self.active = True
        elif self.active and self.level < self.off_std:
            self.active = False
        return self.active != before


# --- landmark bridge for Auto-AVSR (D-022) ------------------------------------


def _indices(connections) -> list[int]:
    s: set[int] = set()
    for c in connections:
        s.update((c.start, c.end))
    return sorted(s)


_KP_SETS: tuple[list[int], list[int], list[int]] | None = None
NOSE_TIP = 1  # canonical face mesh nose tip


def keypoint_sets() -> tuple[list[int], list[int], list[int]]:
    """(eye A, eye B, lips) index sets from the installed MediaPipe face mesh."""
    global _KP_SETS
    if _KP_SETS is None:
        from mediapipe.tasks.python import vision

        c = vision.FaceLandmarksConnections
        _KP_SETS = (
            _indices(c.FACE_LANDMARKS_RIGHT_EYE),
            _indices(c.FACE_LANDMARKS_LEFT_EYE),
            _indices(c.FACE_LANDMARKS_LIPS),
        )
    return _KP_SETS


def four_keypoints(mesh_xy: np.ndarray, sets: tuple[list[int], list[int], list[int]]) -> np.ndarray:
    """Mesh (478, 2) normalised -> (4, 2) normalised [right eye, left eye, nose tip, mouth].

    The order matches Auto-AVSR's stable reference (68-point mean face: 36-41 right eye,
    42-47 left eye, nose, 48-67 mouth), where the subject's right eye is on the image
    left. The eyes are ordered by x, so this holds whatever MediaPipe calls them.
    """
    a = mesh_xy[sets[0]].mean(axis=0)
    b = mesh_xy[sets[1]].mean(axis=0)
    left_img, right_img = (a, b) if a[0] <= b[0] else (b, a)
    mouth = mesh_xy[sets[2]].mean(axis=0)
    return np.stack([left_img, right_img, mesh_xy[NOSE_TIP], mouth]).astype(np.float32)


# --- MediaPipe adapter -------------------------------------------------------


def lip_indices() -> list[int]:
    from mediapipe.tasks.python import vision

    idx: set[int] = set()
    for c in vision.FaceLandmarksConnections.FACE_LANDMARKS_LIPS:
        idx.update((c.start, c.end))
    return sorted(idx)


class MediaPipeFaceDetector:
    """FaceDetector over mediapipe.tasks FaceLandmarker (LIVE_STREAM, one face)."""

    def __init__(self, model_path: Path, on_observation: ObservationCallback) -> None:
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        self._mp = mp
        self._lips = lip_indices()
        self._kp_sets = keypoint_sets()
        self._cb = on_observation
        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.LIVE_STREAM,
            num_faces=1,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
            result_callback=self._on_result,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)

    def detect_async(self, bgr: np.ndarray, ts_ms: int) -> None:
        rgb = np.ascontiguousarray(bgr[:, :, ::-1])
        self._landmarker.detect_async(self._mp.Image(self._mp.ImageFormat.SRGB, rgb), ts_ms)

    def close(self) -> None:
        self._landmarker.close()

    def _on_result(self, result, _image, ts_ms: int) -> None:
        self._cb(self.convert(result, ts_ms, self._lips, self._kp_sets))

    @staticmethod
    def convert(result, ts_ms: int, lips: list[int], kp_sets=None) -> FaceObservation:
        if not result.face_landmarks:
            return FaceObservation(ts_ms=ts_ms, face_present=False)
        lm = result.face_landmarks[0]
        mesh = np.array([(p.x, p.y) for p in lm], dtype=np.float32)
        points = mesh[lips]
        shapes = {c.category_name: c.score for c in (result.face_blendshapes or [[]])[0]}
        yaw = pitch = None
        if result.facial_transformation_matrixes:
            yaw, pitch = yaw_pitch_from_matrix(result.facial_transformation_matrixes[0])
        return FaceObservation(
            ts_ms=ts_ms,
            face_present=True,
            lip_points=points,
            jaw_open=shapes.get("jawOpen"),
            mouth_close=shapes.get("mouthClose"),
            yaw_deg=yaw,
            pitch_deg=pitch,
            keypoints=four_keypoints(mesh, kp_sets) if kp_sets else None,
        )


DetectorFactory = Callable[[Path, ObservationCallback], object]


class FaceService:
    def __init__(
        self,
        settings: Settings,
        hub: CameraHub,
        bus: EventBus,
        health: HealthRegistry,
        consent: ConsentRegistry,
        detector_factory: DetectorFactory | None = None,
    ) -> None:
        self._s = settings
        self._hub = hub
        self._bus = bus
        self._health = health
        self._consent = consent
        self._factory = detector_factory or MediaPipeFaceDetector
        self._backend = "real" if detector_factory is None else "fake"
        window = max(2, round(settings.mouth_window_s * settings.vision_fps))
        self.activity = MouthActivity(window, settings.mouth_on_std, settings.mouth_off_std)
        self._lock = threading.Lock()
        self._latest: FaceObservation | None = None
        self._history: deque[FaceObservation] = deque(
            maxlen=max(1, round(settings.lip_buffer_s * settings.vision_fps))
        )
        self._subs: list[ObservationCallback] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._detector = None
        self._last_sent_ts = -1
        self._face_present: bool | None = None  # debounced; None until first decision
        self._hits = self._misses = 0
        self._last_beat = 0.0
        self._results: deque[float] = deque(maxlen=30)

    # --- lifecycle -------------------------------------------------------

    def start(self) -> bool:
        self._consent.require("camera")  # R3
        if self.running:
            return True
        if self._backend == "real" and not self._s.face_model.is_file():
            self._health.set(
                "face",
                "unavailable",
                f"{self._s.face_model.name} missing; run scripts/download_models.py",
            )
            return False
        try:
            self._detector = self._factory(self._s.face_model, self._on_observation)
        except Exception as exc:
            log.exception("face detector failed to load")
            self._health.set("face", "unavailable", f"detector load failed: {type(exc).__name__}")
            return False
        self._stop.clear()
        self.activity.reset()
        self._face_present = None
        self._hits = self._misses = 0
        self._thread = threading.Thread(target=self._run, name="FaceService", daemon=True)
        self._thread.start()
        self._health.set("face", "ok", "running, waiting for frames", backend=self._backend)
        return True

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout)
        if self._detector is not None:
            try:
                self._detector.close()
            except Exception:
                log.exception("face detector close failed")
            self._detector = None
        with self._lock:
            self._latest = None
            self._history.clear()
        self._health.set("face", "unavailable", "stopped", backend=self._backend)

    @property
    def running(self) -> bool:
        t = self._thread
        return bool(t and t.is_alive())

    # --- consumers -------------------------------------------------------

    def latest(self) -> FaceObservation | None:
        with self._lock:
            return self._latest

    def history(self) -> list[FaceObservation]:
        with self._lock:
            return list(self._history)

    def subscribe(self, cb: ObservationCallback) -> None:
        with self._lock:
            self._subs.append(cb)

    @property
    def mouth_activity(self) -> bool:
        return self.activity.active

    # --- worker ----------------------------------------------------------

    def _run(self) -> None:
        period = 1.0 / max(1, self._s.vision_fps)
        while not self._stop.is_set():
            t0 = time.monotonic()
            frame = self._hub.latest()
            if frame is not None and frame.ts_ms > self._last_sent_ts:
                self._last_sent_ts = frame.ts_ms
                try:
                    self._detector.detect_async(frame.image, frame.ts_ms)  # type: ignore[union-attr]
                except Exception as exc:
                    log.warning("detect_async failed: %s", type(exc).__name__)
            self._stop.wait(max(0.0, period - (time.monotonic() - t0)))

    def _on_observation(self, obs: FaceObservation) -> None:
        if self._stop.is_set() and not self.running and self._detector is None:
            return  # late async result after stop(): don't refill the cleared history
        with self._lock:
            self._latest = obs
            self._history.append(obs)
            subs = list(self._subs)
        self._results.append(time.monotonic())
        changed = self._update_presence(obs.face_present)
        if obs.face_present and obs.jaw_open is not None and obs.mouth_close is not None:
            changed |= self.activity.update(obs.jaw_open, obs.mouth_close)
        if self._face_present is False and self.activity.active:
            self.activity.reset()
            changed = True
        now = time.monotonic()
        if self._face_present is not None and (changed or now - self._last_beat >= HEARTBEAT_S):
            self._last_beat = now
            self._publish(obs, changed)
        for cb in subs:
            try:
                cb(obs)
            except Exception:
                log.exception("face subscriber failed")

    def _update_presence(self, present: bool) -> bool:
        """Debounced face presence (D-016): on after FACE_ON_FRAMES hits, off after
        FACE_OFF_FRAMES misses. Raw per-frame presence stays in `history()` for the lip
        evidence rules. Returns True when the debounced state flips."""
        if present:
            self._hits, self._misses = self._hits + 1, 0
        else:
            self._hits, self._misses = 0, self._misses + 1
        before = self._face_present
        if before is not True and self._hits >= FACE_ON_FRAMES:
            self._face_present = True
        elif before is not False and self._misses >= FACE_OFF_FRAMES:
            self._face_present = False
        return self._face_present != before

    def _publish(self, obs: FaceObservation, changed: bool) -> None:
        fps = 0.0
        if len(self._results) > 1:
            fps = (len(self._results) - 1) / max(1e-6, self._results[-1] - self._results[0])
        self._bus.publish(
            "mouth.activity",
            {
                "active": self.activity.active,
                "changed": changed,
                "face_present": bool(self._face_present),
                "level": round(self.activity.level, 4),
                "yaw_deg": None if obs.yaw_deg is None else round(obs.yaw_deg, 1),
                "pitch_deg": None if obs.pitch_deg is None else round(obs.pitch_deg, 1),
                "obs_ts_ms": obs.ts_ms,
                "lag_ms": now_ms() - obs.ts_ms,
            },
        )
        detail = f"{fps:.1f} results/s, face {'present' if self._face_present else 'absent'}"
        self._health.set("face", "ok", detail, backend=self._backend)
