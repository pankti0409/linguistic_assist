import math
import time
from pathlib import Path

import numpy as np
import pytest

from app.adapters.fakes import FakeFaceDetector, SyntheticCamera
from app.config import load_settings
from app.core.consent import ConsentRegistry
from app.core.health import HealthRegistry
from app.services.camera import CameraHub
from app.services.face import (
    FaceObservation,
    FaceService,
    MediaPipeFaceDetector,
    MouthActivity,
    lip_indices,
    yaw_pitch_from_matrix,
)
from tests.test_camera import Recorder, wait_for

ROOT = Path(__file__).resolve().parent.parent
FACE_MODEL = ROOT / "assets" / "face_landmarker.task"


def rot(yaw_deg: float, pitch_deg: float, scale: float = 1.0) -> np.ndarray:
    y, p = math.radians(yaw_deg), math.radians(pitch_deg)
    ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    rx = np.array([[1, 0, 0], [0, math.cos(p), -math.sin(p)], [0, math.sin(p), math.cos(p)]])
    m = np.eye(4)
    m[:3, :3] = scale * (ry @ rx)
    m[:3, 3] = [1.0, -2.0, -40.0]  # translation must not matter
    return m


@pytest.mark.parametrize("yaw, pitch", [(0, 0), (30, 0), (-25, 10), (10, -20), (60, 5)])
def test_yaw_pitch_from_matrix(yaw, pitch):
    got_yaw, got_pitch = yaw_pitch_from_matrix(rot(yaw, pitch, scale=1.7))
    assert got_yaw == pytest.approx(yaw, abs=1e-6)
    assert got_pitch == pytest.approx(pitch, abs=1e-6)


def test_mouth_activity_hysteresis():
    m = MouthActivity(window=6, on_std=0.035, off_std=0.015)
    for _ in range(10):  # still mouth
        assert m.update(0.05, 0.1) is False
    assert not m.active
    flips = [m.update(0.05 + (0.3 if i % 2 else 0), 0.1) for i in range(6)]  # moving jaw
    assert m.active and flips.count(True) == 1
    # in the band between off and on, the state holds
    for i in range(6):
        m.update(0.05 + (0.05 if i % 2 else 0), 0.1)
    assert m.active and m.off_std < m.level < m.on_std
    for _ in range(6):
        m.update(0.05, 0.1)
    assert not m.active


def test_mouth_close_alone_can_trigger():
    m = MouthActivity(window=4, on_std=0.035, off_std=0.015)
    for i in range(4):
        m.update(0.0, 0.0 if i % 2 else 0.4)
    assert m.active


def _service(script, vision_fps=50):
    s = load_settings({"SIMULATE": "1", "CAMERA_FPS": "200", "VISION_FPS": str(vision_fps)})
    consent = ConsentRegistry()
    consent.grant("camera")
    bus = Recorder()
    health = HealthRegistry(s)
    hub = CameraHub(s, bus, health, consent, source_factory=SyntheticCamera)
    created: list = []
    face = FaceService(s, hub, bus, health, consent, FakeFaceDetector.factory(script, created))
    return hub, face, bus, health, created


def test_face_service_skips_frames_and_keeps_timestamps_increasing():
    hub, face, bus, _, created = _service(None, vision_fps=20)
    hub.start()
    face.start()
    try:
        assert wait_for(lambda: created and len(created[0].timestamps) >= 10)
        time.sleep(0.2)
    finally:
        face.stop()
        hub.stop()
    det = created[0]
    ts = det.timestamps
    assert all(b > a for a, b in zip(ts, ts[1:], strict=False))
    # camera runs at ~200 fps, vision at 20: most frames are skipped, none are queued
    assert hub._seq > 3 * len(ts)
    assert det.closed


def test_face_service_events_and_observations():
    def script(ts, i):
        jaw = 0.05 + (0.3 if (i // 2) % 2 else 0.0) if i >= 10 else 0.05
        return FaceObservation(
            ts_ms=ts,
            face_present=True,
            lip_points=np.zeros((40, 2), np.float32),
            jaw_open=jaw,
            mouth_close=0.1,
            yaw_deg=5.0,
            pitch_deg=-3.0,
        )

    hub, face, bus, health, _ = _service(script)
    hub.start()
    face.start()
    try:
        assert wait_for(lambda: face.mouth_activity, timeout=5)
    finally:
        face.stop()
        hub.stop()
    events = bus.of("mouth.activity")
    assert events[0]["face_present"] is True and events[0]["active"] is False
    turned_on = [e for e in events if e["changed"] and e["active"]]
    assert turned_on and turned_on[0]["yaw_deg"] == 5.0
    assert set(events[0]) == {
        "active",
        "changed",
        "face_present",
        "level",
        "yaw_deg",
        "pitch_deg",
        "obs_ts_ms",
        "lag_ms",
    }  # derived features only: no landmarks, no pixels (R8)
    assert face.history() == []  # cleared on stop


def _present(ts):
    return FaceObservation(ts_ms=ts, face_present=True, jaw_open=0.1, mouth_close=0.1)


def _absent(ts):
    return FaceObservation(ts_ms=ts, face_present=False)


def test_face_lost_resets_activity_after_debounce():
    _, face, bus, _, _ = _service(None)
    face._on_observation(_present(1))
    face._on_observation(_present(2))
    assert bus.of("mouth.activity")[-1]["face_present"] is True
    face.activity.active = True
    for ts in range(3, 7):  # 4 misses: below FACE_OFF_FRAMES, still present
        face._on_observation(_absent(ts))
    assert face.mouth_activity and bus.of("mouth.activity")[-1]["face_present"] is True
    face._on_observation(_absent(7))
    assert not face.mouth_activity
    assert bus.of("mouth.activity")[-1] == {**bus.of("mouth.activity")[-1], "face_present": False}


def test_flickering_detection_does_not_spam_events():
    _, face, bus, _, _ = _service(None)
    face._on_observation(_present(1))
    face._on_observation(_present(2))
    for ts in range(3, 40):  # alternate hit / miss, as seen live on the real webcam
        face._on_observation(_present(ts) if ts % 2 else _absent(ts))
    changes = [e for e in bus.of("mouth.activity") if e["changed"]]
    assert len(changes) == 1 and changes[0]["face_present"] is True


def test_no_event_before_presence_is_decided():
    _, face, bus, _, _ = _service(None)
    face._on_observation(_present(1))  # one hit: not yet decided
    assert bus.of("mouth.activity") == []


def test_missing_model_reports_unavailable(tmp_path):
    s = load_settings({"SIMULATE": "1", "FACE_MODEL": str(tmp_path / "nope.task")})
    consent = ConsentRegistry()
    consent.grant("camera")
    health = HealthRegistry(s)
    hub = CameraHub(s, Recorder(), health, consent, source_factory=SyntheticCamera)
    face = FaceService(s, hub, Recorder(), health, consent)  # real detector path
    assert face.start() is False
    assert health.get("face").status == "unavailable"
    assert "download_models.py" in health.get("face").detail


@pytest.mark.skipif(not FACE_MODEL.is_file(), reason="run scripts/download_models.py")
def test_real_mediapipe_live_stream_on_blank_frames():
    pytest.importorskip("mediapipe")
    assert len(lip_indices()) == 40
    got: list[FaceObservation] = []
    det = MediaPipeFaceDetector(FACE_MODEL, got.append)
    try:
        for k in range(5):
            det.detect_async(np.zeros((480, 640, 3), np.uint8), 1000 + 66 * k)
        assert wait_for(lambda: len(got) >= 1, timeout=10)
    finally:
        det.close()
    assert all(o.face_present is False for o in got)


def test_late_result_after_stop_is_dropped():
    hub, face, bus, _, _ = _service(None)
    hub.start()
    face.start()
    face.stop()
    hub.stop()
    face._on_observation(_present(10_000))
    assert face.history() == [] and face.latest() is None
