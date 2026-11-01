import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.adapters.fakes import SimulatedLLM, simulation_overrides
from app.config import load_settings
from app.main import create_app
from tests.conftest import BASE_URL, WS_URL, fake_overrides


def _client(env):
    return TestClient(
        create_app(load_settings({"SIMULATE": "1", **env}), fake_overrides()), base_url=BASE_URL
    )


def test_token_required_when_configured():
    with _client({"ACCESS_TOKEN": "s3cret"}) as c:
        assert c.get("/health").status_code == 200  # stays open
        r = c.get("/consent")
        assert r.status_code == 401 and r.json()["error_code"] == "unauthorized"
        assert c.get("/consent", headers={"X-PS16-Token": "wrong"}).status_code == 401
        assert c.get("/consent", headers={"X-PS16-Token": "s3cret"}).status_code == 200
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect(WS_URL):
                pass
        with c.websocket_connect(WS_URL + "?token=s3cret") as ws:
            c.app.state.bus.publish("error", {"x": 1})
            assert ws.receive_json()["data"] == {"x": 1}


def test_no_token_by_default():
    with _client({}) as c:
        assert c.get("/consent").status_code == 200


def test_simulated_llm_never_invents_words():
    from app.core.health import HealthRegistry
    from app.services.fusion import FusionService
    from tests.test_fusion import WORKED, packet

    s = load_settings({})
    r = FusionService(s, HealthRegistry(s), SimulatedLLM()).reconstruct(packet(WORKED))
    assert [c.text for c in r.candidates] == ["Water cold.", "Water cold, please."]
    assert r.candidates[1].added_words == ["please"]


def test_simulation_overrides_run_a_whole_turn_offline():
    o = simulation_overrides()
    from app.adapters.fakes import FakeFaceDetector, FakeGestureRecognizer, SyntheticCamera

    o.frame_source_factory = SyntheticCamera  # tests never open a camera or a video
    o.face_detector_factory = FakeFaceDetector.factory()
    o.gesture_recognizer_factory = FakeGestureRecognizer.factory()
    import tempfile
    from pathlib import Path

    o.data_dir = Path(tempfile.mkdtemp())
    o.lexicon_path = o.data_dir / "lex.json"
    s = load_settings({"SIMULATE": "1", "VOICE_ID_FEMALE": "sim"})
    with TestClient(create_app(s, o), base_url=BASE_URL) as c:
        c.post("/consent", json={"purpose": "microphone"})
        tid = c.post("/turn/start", json={"speaker": "PATIENT"}).json()["turn_id"]
        from tests.test_turns import speech

        speech(c.app.state.turns, "water")
        view = c.post("/turn/end").json()
        assert view["result"]["candidates"][0]["text"] == "Water."
        r = c.post("/turn/confirm", json={"turn_id": tid, "choice_index": 0}).json()
        assert r["spoken"]["tier"] == "local" and o.tts.spoken == ["Water."]
        services = c.get("/health").json()["services"]
        assert services["scribe"]["backend"] == "fake" and services["tts"]["backend"] == "fake"
