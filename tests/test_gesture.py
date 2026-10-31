import json
import threading
from pathlib import Path

import numpy as np
import pytest

from app.adapters.fakes import FakeGestureRecognizer, SyntheticCamera
from app.config import load_settings
from app.core.consent import ConsentRegistry
from app.core.health import HealthRegistry
from app.services.camera import CameraHub
from app.services.gesture import (
    DEFAULT_LEXICON,
    Debouncer,
    GestureService,
    GestureToken,
    HandReading,
    InvalidLexiconError,
    Lexicon,
    MediaPipeGestureRecognizer,
)
from tests.test_camera import Recorder, wait_for

ROOT = Path(__file__).resolve().parent.parent
GESTURE_MODEL = ROOT / "assets" / "gesture_recognizer.task"


def R(label, hand="Right", score=0.9):
    return HandReading(hand=hand, label=label, score=score)


def feed(deb, frames, t0=0.0, dt=1 / 15):
    """frames: list of reading-lists; returns tokens emitted, in order."""
    out = []
    for i, readings in enumerate(frames):
        out += [t.token for t in deb.update(readings, ts_ms=i, now_s=t0 + i * dt)]
    return out


# --- debouncer ----------------------------------------------------------


def test_needs_eight_stable_frames_and_emits_once():
    d = Debouncer(stable_frames=8, min_score=0.7)
    assert feed(d, [[R("Thumb_Up")]] * 7) == []
    d = Debouncer(stable_frames=8, min_score=0.7)
    assert feed(d, [[R("Thumb_Up")]] * 12) == ["Thumb_Up|Right"]


def test_flicker_is_ignored():
    d = Debouncer(stable_frames=8, min_score=0.7)
    frames = [[R("Thumb_Up")], [R("Victory")]] * 10  # alternating labels never stabilise
    assert feed(d, frames) == []
    weak = [[R("Thumb_Up", score=0.69)]] * 20
    assert feed(Debouncer(8, 0.7), weak) == []


def test_repeat_needs_return_to_none():
    d = Debouncer(stable_frames=8, min_score=0.7)
    frames = [[R("Thumb_Up")]] * 8 + [[R("None")]] * 2 + [[R("Thumb_Up")]] * 8
    assert feed(d, frames) == ["Thumb_Up|Right", "Thumb_Up|Right"]


def test_hand_leaving_frame_rearms():
    d = Debouncer(stable_frames=8, min_score=0.7)
    frames = [[R("Thumb_Up")]] * 8 + [[]] * 2 + [[R("Thumb_Up")]] * 8
    assert feed(d, frames) == ["Thumb_Up|Right", "Thumb_Up|Right"]


def test_hold_repeats_after_1_5_s():
    d = Debouncer(stable_frames=8, min_score=0.7, hold_s=1.5)
    # 8 frames to emit, then held: 1.5 s at 15 fps is 22.5 frames more
    frames = [[R("Thumb_Up")]] * (8 + 22)
    assert feed(d, frames) == ["Thumb_Up|Right"]
    d = Debouncer(stable_frames=8, min_score=0.7, hold_s=1.5)
    assert feed(d, [[R("Thumb_Up")]] * (8 + 24)) == ["Thumb_Up|Right"] * 2


def test_weak_frame_does_not_rearm_same_token():
    d = Debouncer(stable_frames=8, min_score=0.7, hold_s=1.5)
    frames = [[R("Thumb_Up")]] * 8 + [[R("Thumb_Up", score=0.3)]] + [[R("Thumb_Up")]] * 8
    assert feed(d, frames) == ["Thumb_Up|Right"]  # blocked: not a return to None


def test_hands_are_independent_tokens():
    d = Debouncer(stable_frames=8, min_score=0.7)
    frames = [[R("Victory", "Left"), R("Thumb_Up", "Right")]] * 8
    assert sorted(feed(d, frames)) == ["Thumb_Up|Right", "Victory|Left"]


def test_token_score_is_mean_of_run():
    d = Debouncer(stable_frames=4, min_score=0.7)
    toks = []
    for i, s in enumerate([0.8, 0.9, 0.7, 1.0]):
        toks += d.update([R("Victory", score=s)], ts_ms=i, now_s=i * 0.05)
    assert toks[0].score == pytest.approx(0.85)


# --- lexicon --------------------------------------------------------------


def test_lexicon_defaults_wildcards_and_unmapped(tmp_path):
    lex = Lexicon(tmp_path / "u.json")
    assert lex.all() == DEFAULT_LEXICON
    assert lex.lookup("Thumb_Up|Left") == "yes" and lex.lookup("Thumb_Up|Right") == "yes"
    assert lex.lookup("Victory|Left") is None  # unmapped: ignored, never guessed


def test_lexicon_exact_beats_wildcard_and_persists(tmp_path):
    path = tmp_path / "u.json"
    lex = Lexicon(path)
    lex.bind("Thumb_Up|Left", "water")
    assert lex.lookup("Thumb_Up|Left") == "water" and lex.lookup("Thumb_Up|Right") == "yes"
    assert Lexicon(path).lookup("Thumb_Up|Left") == "water"
    assert json.loads(path.read_text())["Thumb_Up|Left"] == "water"


@pytest.mark.parametrize(
    "mapping",
    [
        {"Thumbs|Left": "x"},
        {"Thumb_Up|Both": "x"},
        {"Thumb_Up|Left": ""},
        {"Thumb_Up|Left": "__DELETE__"},
        {"None|Left": "x"},
    ],
)
def test_lexicon_rejects_bad_entries(tmp_path, mapping):
    with pytest.raises(InvalidLexiconError):
        Lexicon(tmp_path / "u.json").replace(mapping)


def test_reserved_words_allowed(tmp_path):
    lex = Lexicon(tmp_path / "u.json")
    lex.replace({"Closed_Fist|Right": "__COMMIT__", "Victory|*": "__CLEAR__"})
    assert lex.lookup("Closed_Fist|Right") == "__COMMIT__"


# --- service ----------------------------------------------------------------


def _service(script, tmp_path):
    s = load_settings({"SIMULATE": "1", "CAMERA_FPS": "200", "VISION_FPS": "60"})
    consent = ConsentRegistry()
    consent.grant("camera")
    bus = Recorder()
    health = HealthRegistry(s)
    hub = CameraHub(s, bus, health, consent, source_factory=SyntheticCamera)
    created: list = []
    svc = GestureService(
        s,
        hub,
        bus,
        health,
        consent,
        FakeGestureRecognizer.factory(script, created),
        tmp_path / "lex.json",
    )
    return hub, svc, bus, created


def test_service_publishes_token_and_word(tmp_path):
    hub, svc, bus, created = _service(lambda ts, i: [R("Thumb_Up", "Left")], tmp_path)
    words = []
    svc.subscribe_words(words.append)
    hub.start()
    svc.start()
    try:
        assert wait_for(lambda: words)
    finally:
        svc.stop()
        hub.stop()
    assert bus.of("gesture.token")[0]["token"] == "Thumb_Up|Left"
    assert bus.of("gesture.word")[0]["word"] == "yes"
    assert words[0].word == "yes" and words[0].score == pytest.approx(0.9)
    ts = created[0].timestamps
    assert all(b > a for a, b in zip(ts, ts[1:], strict=False))


def test_unmapped_token_gives_no_word(tmp_path):
    _, svc, bus, _ = _service(None, tmp_path)
    svc.handle_token(GestureToken("Victory|Right", 0.9, 1))
    assert bus.of("gesture.token") and bus.of("gesture.word") == []


def test_calibration_binds_next_stable_token(tmp_path):
    hub, svc, bus, _ = _service(None, tmp_path)
    hub.start()
    svc.start()
    try:
        result = {}
        t = threading.Thread(target=lambda: result.update(svc.calibrate("water", timeout_s=3)))
        t.start()
        assert wait_for(lambda: svc._calibration is not None)
        svc.handle_token(GestureToken("Victory|Left", 0.95, 5))
        t.join(3)
    finally:
        svc.stop()
        hub.stop()
    assert result["token"] == "Victory|Left" and result["word"] == "water"
    assert svc.lexicon.lookup("Victory|Left") == "water"
    assert bus.of("gesture.word") == []  # the calibration token itself is not a word


def test_calibration_times_out(tmp_path):
    from app.services.gesture import CalibrationTimeoutError

    hub, svc, _, _ = _service(None, tmp_path)
    hub.start()
    svc.start()
    try:
        with pytest.raises(CalibrationTimeoutError):
            svc.calibrate("water", timeout_s=0.2)
    finally:
        svc.stop()
        hub.stop()


def test_gesture_api():
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.conftest import BASE_URL, fake_overrides

    s = load_settings({"SIMULATE": "1", "CALIBRATE_TIMEOUT_S": "0.3"})
    with TestClient(create_app(s, fake_overrides()), base_url=BASE_URL) as client:
        _gesture_api_checks(client)


def _gesture_api_checks(client):
    r = client.get("/gesture/lexicon")
    assert r.status_code == 200 and r.json() == DEFAULT_LEXICON
    r = client.put(
        "/gesture/lexicon", json={"Victory|Right": "water", "Closed_Fist|*": "__COMMIT__"}
    )
    assert r.status_code == 200 and r.json()["Victory|Right"] == "water"
    r = client.put("/gesture/lexicon", json={"Wave|Right": "hi"})
    assert r.status_code == 422 and r.json()["error_code"] == "invalid_lexicon"
    r = client.post("/gesture/calibrate", json={"word": "tea"})
    assert r.status_code == 403  # needs camera consent
    client.post("/consent", json={"purpose": "camera"})
    assert wait_for(lambda: client.app.state.gesture.running)
    r = client.post("/gesture/calibrate", json={"word": "tea"})  # fake sees no hands
    assert r.status_code == 408 and r.json()["error_code"] == "calibration_timeout"


@pytest.mark.skipif(not GESTURE_MODEL.is_file(), reason="run scripts/download_models.py")
def test_real_mediapipe_gesture_live_stream_on_blank_frames():
    got: list = []
    rec = MediaPipeGestureRecognizer(GESTURE_MODEL, lambda r, ts: got.append(r))
    try:
        for k in range(5):
            rec.recognize_async(np.zeros((480, 640, 3), np.uint8), 1000 + 66 * k)
        assert wait_for(lambda: len(got) >= 1, timeout=10)
    finally:
        rec.close()
    assert all(r == [] for r in got)
