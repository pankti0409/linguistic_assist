import time
from pathlib import Path

import numpy as np
import pytest

from app.adapters.fakes import FakeFaceDetector, FakeLipReader, SyntheticCamera
from app.config import load_settings
from app.core.consent import ConsentRegistry
from app.core.errors import ConsentRequiredError
from app.core.health import HealthRegistry
from app.schemas import LipEvidence
from app.services.camera import CameraHub
from app.services.face import FaceObservation, FaceService, four_keypoints
from app.services.lip import (
    AVSR_DIR,
    Clip,
    LipService,
    UnavailableLipReader,
    build_clip,
    judge,
    load_reader,
    resample_times,
)
from tests.test_camera import Recorder, wait_for

KP = np.array([[0.4, 0.4], [0.6, 0.4], [0.5, 0.5], [0.5, 0.62]], np.float32)


def obs(ts, present=True, yaw=0.0):
    return FaceObservation(
        ts_ms=ts,
        face_present=present,
        jaw_open=0.1,
        mouth_close=0.1,
        yaw_deg=yaw if present else None,
        keypoints=KP if present else None,
    )


def frames(n, step=33, t0=1000, size=(48, 64)):
    return [(t0 + i * step, np.full(size, i % 255, np.uint8)) for i in range(n)]


# --- pure rules ------------------------------------------------------------


def test_resample_to_25_fps():
    times = resample_times(1000, 2000)
    assert len(times) == 26 and times[1] - times[0] == 40


def test_four_keypoints_order_and_eye_sorting():
    mesh = np.zeros((478, 2), np.float32)
    sets = ([2, 3], [4, 5], [10, 11])
    mesh[[2, 3]] = [0.7, 0.4]  # set 0 lies on the image right ...
    mesh[[4, 5]] = [0.3, 0.4]  # ... set 1 on the image left
    mesh[1] = [0.5, 0.5]  # nose tip
    mesh[10], mesh[11] = [0.5, 0.6], [0.5, 0.64]
    kp = four_keypoints(mesh, sets)
    assert kp[0][0] < kp[1][0]  # image-left eye first, as in Auto-AVSR's reference
    assert np.allclose(kp[2], [0.5, 0.5]) and np.allclose(kp[3], [0.5, 0.62])


def test_build_clip_attaches_nearest_keypoints_in_pixels():
    fr = frames(30)  # ~1 s at 30 fps
    ob = [obs(1000 + i * 66) for i in range(15)]  # 15 fps
    clip = build_clip(fr, ob, max_yaw_deg=25)
    assert len(clip.frames) == 24  # 957 ms span -> floor(957 / 40) + 1
    assert all(lm is not None for lm in clip.landmarks)
    assert np.allclose(clip.landmarks[0], KP * np.array([64, 48]))
    assert clip.missing_fraction == 0 and clip.yaw_over_fraction == 0


def test_judge_rules():
    f10 = [np.zeros((4, 4))] * 10
    ok = Clip(f10, [KP] * 10, 0.0, 0.0)
    assert judge(ok, 8) is None
    assert "frames" in judge(Clip([np.zeros((4, 4))] * 7, [KP] * 7, 0, 0), 8)
    assert "missing" in judge(Clip(f10, [KP] * 10, 0.21, 0), 8)
    assert judge(Clip(f10, [KP] * 10, 0.2, 0), 8) is None  # exactly 20% is allowed
    assert "yaw" in judge(Clip(f10, [KP] * 10, 0, 0.5), 8)
    assert "landmarks" in judge(Clip(f10, [None] * 10, 0, 0), 8)


def test_build_clip_measures_missing_and_yaw_on_raw_observations():
    fr = frames(30)
    ob = [obs(1000 + i * 66, present=(i % 3 != 0)) for i in range(15)]
    assert build_clip(fr, ob, 25).missing_fraction == pytest.approx(5 / 15)
    ob = [obs(1000 + i * 66, yaw=40.0 if i < 5 else 5.0) for i in range(15)]
    assert build_clip(fr, ob, 25).yaw_over_fraction == pytest.approx(5 / 15)


def test_load_reader_unavailable_cases(tmp_path):
    r = load_reader(load_settings({"LIP_ENABLED": "0"}))
    assert not r.available and "LIP_ENABLED=0" in r.reason
    r = load_reader(load_settings({"LIP_CHECKPOINT": str(tmp_path / "none.pth")}))
    assert not r.available and "download_lip_model.py" in r.reason
    assert r.read([np.zeros((2, 2))] * 3).status == "unavailable"


# --- service ---------------------------------------------------------------


def _service(reader, script=None, mode="push"):
    s = load_settings({"SIMULATE": "1", "CAMERA_FPS": "30", "VISION_FPS": "15"})
    consent = ConsentRegistry()
    consent.grant("camera")
    bus = Recorder()
    health = HealthRegistry(s)
    hub = CameraHub(s, bus, health, consent, source_factory=SyntheticCamera)
    face = FaceService(s, hub, bus, health, consent, FakeFaceDetector.factory(script))
    lip = LipService(s, hub, face, bus, health, consent, lambda: reader, mode=mode)
    return hub, face, lip, bus, health


def _face_script(ts, i):
    return obs(ts)


def test_push_capture_reads_clip_and_publishes():
    reader = FakeLipReader(LipEvidence(status="ok", text="water", score=0.31), available=True)
    hub, face, lip, bus, health = _service(reader, _face_script)
    lip.load()
    assert health.get("lip").status == "ok"
    hub.start()
    face.start()
    try:
        lip.start_capture()
        time.sleep(1.0)
        ev = lip.stop_capture().result(timeout=5)
    finally:
        face.stop()
        hub.stop()
    assert ev.status == "ok" and ev.text == "water" and ev.score == 0.31
    assert reader.calls and reader.calls[0] >= 8
    pub = bus.of("lip.result")[-1]
    assert pub["status"] == "ok" and pub["hint_only"] is True and pub["reason"] is None
    assert len(lip._frames) == 0  # clip dropped from memory


def test_short_clip_is_insufficient_and_reader_not_called():
    reader = FakeLipReader(LipEvidence(status="ok", text="x", score=0.9), available=True)
    _, _, lip, bus, _ = _service(reader, _face_script)
    lip.load()
    lip.start_capture()
    ev = lip.stop_capture().result(timeout=5)  # no frames at all
    assert ev.status == "insufficient_visual_evidence" and reader.calls == []
    assert "frames" in bus.of("lip.result")[-1]["reason"]


def test_no_face_is_insufficient():
    reader = FakeLipReader(LipEvidence(status="ok", text="x", score=0.9), available=True)
    hub, face, lip, _, _ = _service(reader, None)  # fake detector: never a face
    lip.load()
    hub.start()
    face.start()
    try:
        lip.start_capture()
        time.sleep(0.8)
        ev = lip.stop_capture().result(timeout=5)
    finally:
        face.stop()
        hub.stop()
    assert ev.status == "insufficient_visual_evidence" and reader.calls == []


def test_unavailable_reader_never_fakes_text():
    hub, face, lip, bus, health = _service(UnavailableLipReader("checkpoint missing"))
    lip.load()
    assert health.get("lip").status == "unavailable"
    assert "mouth_activity only" in health.get("lip").detail
    hub.start()
    face.start()
    try:
        lip.start_capture()
        time.sleep(0.5)
        ev = lip.stop_capture().result(timeout=5)
    finally:
        face.stop()
        hub.stop()
    assert ev.status == "unavailable" and ev.text is None and ev.score is None
    assert bus.of("lip.result")[-1]["reason"] == "checkpoint missing"


def test_capture_requires_camera_consent():
    s = load_settings({"SIMULATE": "1"})
    consent = ConsentRegistry()
    bus, health = Recorder(), HealthRegistry(s)
    hub = CameraHub(s, bus, health, consent, source_factory=SyntheticCamera)
    face = FaceService(s, hub, bus, health, consent, FakeFaceDetector.factory())
    lip = LipService(s, hub, face, bus, health, consent, FakeLipReader)
    with pytest.raises(ConsentRequiredError):
        lip.start_capture()


def test_auto_mode_follows_mouth_activity():
    reader = FakeLipReader(LipEvidence(status="ok", text="hi", score=0.2), available=True)
    _, face, lip, bus, _ = _service(reader, mode="auto")
    lip.load()
    face.activity.active = True
    lip._on_observation(obs(1))
    assert lip.capturing
    face.activity.active = False
    lip._on_observation(obs(2))
    assert not lip.capturing
    assert wait_for(lambda: bus.of("lip.result"))


def test_health_reports_lip_in_app(client):
    assert wait_for(lambda: client.get("/health").json()["services"]["lip"]["detail"] != "loading")


# --- real Auto-AVSR code (no checkpoint needed) --------------------------------


@pytest.mark.skipif(not (AVSR_DIR / "lightning.py").is_file(), reason="auto_avsr not cloned")
def test_auto_avsr_preprocessing_runs_on_our_landmarks():
    pytest.importorskip("torch")
    pytest.importorskip("skimage")
    from app.services.lip import AutoAvsrReader

    reader = AutoAvsrReader(Path("unused.pth"), load_model=False)
    assert reader.available is False  # no model, so never used for text
    h, w = 480, 640
    rng = np.random.default_rng(0)
    clip_frames = [rng.integers(0, 255, (h, w), dtype=np.uint8) for _ in range(20)]
    lm = KP * np.array([w, h], np.float32)
    landmarks = [lm if i % 2 == 0 else None for i in range(20)]  # gaps get interpolated
    video = reader.preprocess(clip_frames, landmarks)
    assert tuple(video.shape) == (20, 1, 88, 88)
    assert abs(float(video.mean())) < 5  # normalised by (x - 0.421) / 0.165


# --- HuggingFace Space lip reader (D-050) -----------------------------------


class _FakeGradioClient:
    """Minimal stand-in for gradio_client.Client."""

    def __init__(self, space_id, **kwargs):
        self.space_id = space_id
        self.calls: list[dict] = []

    def predict(self, *, video_path, beam_size, api_name):
        self.calls.append({"video_path": video_path, "beam_size": beam_size})
        return "hello world"


def _make_hf_reader(monkeypatch, space_id="marshal-yash/vsr_trlrs3vox2_base"):
    """Return a HFSpaceLipReader with gradio_client mocked out."""
    from app.services.lip import HFSpaceLipReader

    reader = HFSpaceLipReader(space_id=space_id, beam_size=10)
    fake_client = _FakeGradioClient(space_id)
    reader._client = fake_client  # inject pre-built fake, skip real network call
    return reader, fake_client


def test_hf_space_reader_is_available(monkeypatch):
    from app.services.lip import HFSpaceLipReader

    monkeypatch.setattr("app.services.lip.find_spec", lambda name: object())
    reader = HFSpaceLipReader()
    assert reader.available is True
    assert reader.reason == ""


def test_hf_space_reader_unavailable_without_client_dependency(monkeypatch):
    from app.services.lip import HFSpaceLipReader

    monkeypatch.setattr("app.services.lip.find_spec", lambda name: None)
    reader = HFSpaceLipReader()
    assert reader.available is False
    assert "gradio-client is not installed" in reader.reason
    assert "pip install gradio-client" in reader.reason


def test_hf_space_missing_client_reports_unavailable_health(monkeypatch):
    from app.services.lip import HFSpaceLipReader

    monkeypatch.setattr("app.services.lip.find_spec", lambda name: None)
    _, _, lip, _, health = _service(HFSpaceLipReader())
    lip.load()
    assert health.get("lip").status == "unavailable"
    assert "gradio-client is not installed" in health.get("lip").detail


def test_hf_space_reader_returns_lip_evidence(monkeypatch, tmp_path):
    """HFSpaceLipReader encodes frames and returns LipEvidence(status='ok')."""
    import cv2

    reader, fake_client = _make_hf_reader(monkeypatch)

    # patch cv2.VideoWriter so we don't need a real codec
    class _FakeVW:
        def write(self, frame): pass
        def release(self): pass

    monkeypatch.setattr(cv2, "VideoWriter", lambda *a, **kw: _FakeVW())
    monkeypatch.setattr(cv2, "VideoWriter_fourcc", lambda *a: 0)

    rng = np.random.default_rng(42)
    clip_frames = [rng.integers(0, 255, (48, 64), dtype=np.uint8) for _ in range(20)]

    ev = reader.read(clip_frames)
    assert ev.status == "ok"
    assert ev.text == "hello world"
    assert ev.score == 0.5
    assert ev.frames == 20
    assert len(fake_client.calls) == 1
    assert fake_client.calls[0]["beam_size"] == 10.0


def test_hf_space_reader_empty_frames(monkeypatch):
    """Empty frame list -> insufficient_visual_evidence, no network call."""
    reader, fake_client = _make_hf_reader(monkeypatch)
    ev = reader.read([])
    assert ev.status == "insufficient_visual_evidence"
    assert fake_client.calls == []


def test_load_reader_prefers_hf_space_over_local(tmp_path, monkeypatch):
    """When LIP_HF_SPACE is set, load_reader returns HFSpaceLipReader."""
    from app.config import load_settings
    from app.services.lip import HFSpaceLipReader, load_reader

    monkeypatch.setattr("app.services.lip.find_spec", lambda name: object())
    s = load_settings({
        "LIP_HF_SPACE": "marshal-yash/vsr_trlrs3vox2_base",
        "LIP_HF_BEAM_SIZE": "15",
        "LIP_ENABLED": "1",
    })
    reader = load_reader(s)
    assert isinstance(reader, HFSpaceLipReader)
    assert reader._space_id == "marshal-yash/vsr_trlrs3vox2_base"
    assert reader._beam_size == 15
    assert reader.available is True


def test_load_reader_hf_space_disabled_when_lip_disabled():
    """LIP_ENABLED=0 must take precedence even when LIP_HF_SPACE is set."""
    from app.config import load_settings
    from app.services.lip import UnavailableLipReader, load_reader

    s = load_settings({
        "LIP_HF_SPACE": "marshal-yash/vsr_trlrs3vox2_base",
        "LIP_ENABLED": "0",
    })
    reader = load_reader(s)
    assert isinstance(reader, UnavailableLipReader)
    assert not reader.available


def test_hf_space_health_message(monkeypatch):
    """LipService.load() surfaces the Space ID in the health detail."""
    from app.adapters.fakes import FakeFaceDetector, SyntheticCamera
    from app.config import load_settings
    from app.core.consent import ConsentRegistry
    from app.core.health import HealthRegistry
    from app.services.camera import CameraHub
    from app.services.face import FaceService
    from app.services.lip import HFSpaceLipReader, LipService
    from tests.test_camera import Recorder

    monkeypatch.setattr("app.services.lip.find_spec", lambda name: object())
    reader = HFSpaceLipReader(space_id="marshal-yash/vsr_trlrs3vox2_base", beam_size=20)
    s = load_settings({"SIMULATE": "1"})
    consent = ConsentRegistry()
    consent.grant("camera")
    bus = Recorder()
    health = HealthRegistry(s)
    hub = CameraHub(s, bus, health, consent, source_factory=SyntheticCamera)
    face = FaceService(s, hub, bus, health, consent, FakeFaceDetector.factory())
    lip = LipService(s, hub, face, bus, health, consent, lambda: reader)
    lip.load()
    detail = health.get("lip").detail
    assert "marshal-yash/vsr_trlrs3vox2_base" in detail
    assert "beam=20" in detail
