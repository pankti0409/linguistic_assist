import threading
import time

import pytest

from app.adapters.fakes import SyntheticCamera, VideoFileCamera
from app.config import load_settings
from app.core.consent import ConsentRegistry
from app.core.errors import ConsentRequiredError
from app.core.health import HealthRegistry
from app.services.camera import CameraHub, OpenCVCamera, camera_indices, make_source


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


class Recorder:
    """EventBus stand-in that records published events synchronously."""

    def __init__(self):
        self.events = []
        self._lock = threading.Lock()

    def publish(self, type_, data=None):
        with self._lock:
            self.events.append((type_, data or {}))

    def of(self, type_):
        with self._lock:
            return [d for t, d in self.events if t == type_]


def make_hub(source=None, fps=100, granted=True, backoff=(0.01,)):
    s = load_settings({"SIMULATE": "1", "CAMERA_FPS": str(fps)})
    consent = ConsentRegistry()
    if granted:
        consent.grant("camera")
    bus = Recorder()
    health = HealthRegistry(s)
    src = source or SyntheticCamera()
    hub = CameraHub(s, bus, health, consent, source_factory=lambda: src, backoff_s=backoff)
    return hub, bus, health, src


def test_camera_refuses_without_consent():
    hub, *_ = make_hub(granted=False)
    with pytest.raises(ConsentRequiredError):
        hub.start()
    assert not hub.running


def test_frames_flow_with_strictly_increasing_timestamps():
    hub, bus, health, _ = make_hub()
    hub.start()
    try:
        assert wait_for(lambda: len(hub.recent()) >= 20)
        frames = hub.recent()
        ts = [f.ts_ms for f in frames]
        assert all(b > a for a, b in zip(ts, ts[1:], strict=False))
        assert [f.seq for f in frames] == list(range(frames[0].seq, frames[0].seq + len(frames)))
        assert hub.latest().seq == frames[-1].seq
        assert len(hub.recent()) <= 100  # deque bounded to ~1 s at CAMERA_FPS
        assert bus.of("camera.status")[0]["ok"] is True
        assert health.get("camera").status == "ok"
    finally:
        hub.stop()
    assert not hub.running
    assert hub.latest() is None and hub.recent() == []  # frames dropped from memory
    assert bus.of("camera.status")[-1] == {"ok": False, "detail": "stopped"}


def test_subscriber_callbacks_and_failures_are_isolated():
    hub, *_ = make_hub()
    got = []

    def bad(_frame):
        raise RuntimeError("subscriber bug")

    hub.subscribe(bad)
    hub.subscribe(got.append)
    hub.start()
    try:
        assert wait_for(lambda: len(got) >= 5)
        assert hub.running  # a crashing subscriber does not kill the camera thread
    finally:
        hub.stop()


def test_busy_camera_retries_with_backoff_then_recovers():
    hub, bus, health, src = make_hub(SyntheticCamera(fail_opens=3))
    hub.start()
    try:
        assert wait_for(lambda: hub.latest() is not None)
    finally:
        hub.stop()
    statuses = bus.of("camera.status")
    fails = [s for s in statuses[:3]]
    assert all(s["ok"] is False and s["detail"] == "camera busy or missing" for s in fails)
    assert [s["attempt"] for s in fails] == [1, 2, 3]
    assert statuses[3]["ok"] is True
    assert src.opens == 4


def test_open_exception_does_not_crash():
    s = load_settings({"SIMULATE": "1"})
    consent = ConsentRegistry()
    consent.grant("camera")
    bus = Recorder()

    def boom():
        raise OSError("driver exploded")

    hub = CameraHub(s, bus, HealthRegistry(s), consent, source_factory=boom, backoff_s=(0.01,))
    hub.start()
    try:
        assert wait_for(lambda: len(bus.of("camera.status")) >= 3)
        assert hub.running
    finally:
        hub.stop()


def test_camera_that_stops_delivering_is_reopened():
    hub, bus, _, src = make_hub(SyntheticCamera(fail_after=5))
    hub.start()
    try:
        assert wait_for(lambda: src.opens >= 2)
    finally:
        hub.stop()
    assert any("reopening" in s["detail"] for s in bus.of("camera.status"))
    assert src.closed >= 1


def test_index_order_prefers_configured_then_fallbacks():
    assert camera_indices("0") == (0, 1, 2)
    assert camera_indices("1") == (1, 0, 2)


def test_make_source_rules():
    assert isinstance(make_source(load_settings({})), OpenCVCamera)
    sim = make_source(load_settings({"SIMULATE": "1", "CAMERA_SOURCE": "clip.mp4"}))
    assert isinstance(sim, VideoFileCamera)
    with pytest.raises(ValueError, match="R1"):
        make_source(load_settings({"CAMERA_SOURCE": "clip.mp4"}))


def test_consent_grant_starts_and_revoke_stops_camera(client):
    hub, face = client.app.state.camera, client.app.state.face
    assert not hub.running
    with client.websocket_connect("ws://127.0.0.1/ws") as ws:
        client.post("/consent", json={"purpose": "camera"})
        assert wait_for(lambda: hub.running and face.running and hub.latest() is not None)
        seen = set()
        while not {"camera.status", "mouth.activity"} <= seen:
            seen.add(ws.receive_json()["type"])
        client.delete("/consent/camera")
        assert wait_for(lambda: not hub.running and not face.running)
    services = client.get("/health").json()["services"]
    assert services["camera"]["status"] == "unavailable"
    assert services["camera"]["detail"] == "stopped"


def test_preview_disabled_by_default(client):
    r = client.get("/camera/preview.mjpg")
    assert r.status_code == 503 and r.json()["error_code"] == "service_unavailable"


def test_preview_needs_camera_consent():
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.conftest import BASE_URL, fake_overrides

    s = load_settings({"SIMULATE": "1", "DEBUG_PREVIEW": "1"})
    with TestClient(create_app(s, fake_overrides()), base_url=BASE_URL) as c:
        r = c.get("/camera/preview.mjpg")
    assert r.status_code == 403 and r.json()["error_code"] == "consent_required"
