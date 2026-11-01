import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.core.voice import VoiceNotConfiguredError, VoiceSelector
from app.main import create_app
from tests.conftest import BASE_URL, fake_overrides

BOTH = {"VOICE_ID_MALE": "male-id", "VOICE_ID_FEMALE": "female-id"}


def test_default_and_switching():
    v = VoiceSelector(load_settings(BOTH))
    assert v.current() == ("female", "female-id")  # VOICE_DEFAULT defaults to female
    v.select("male")
    assert v.current() == ("male", "male-id")
    v.select("female")
    assert v.current() == ("female", "female-id")


def test_voice_default_env():
    v = VoiceSelector(load_settings({**BOTH, "VOICE_DEFAULT": "male"}))
    assert v.current() == ("male", "male-id")


def test_unconfigured_gender_refused_and_selection_kept():
    v = VoiceSelector(load_settings({"VOICE_ID_FEMALE": "female-id"}))
    with pytest.raises(VoiceNotConfiguredError):
        v.select("male")
    assert v.current() == ("female", "female-id")


def test_falls_back_to_the_configured_slot():
    v = VoiceSelector(load_settings({"VOICE_ID_MALE": "male-id"}))  # default female missing
    assert v.current() == ("male", "male-id")
    assert VoiceSelector(load_settings({})).current() is None


def test_legacy_voice_id_fills_default_slot_only():
    v = VoiceSelector(load_settings({"VOICE_ID": "legacy", "VOICE_DEFAULT": "male"}))
    assert v.current() == ("male", "legacy")
    kept = VoiceSelector(load_settings({"VOICE_ID": "legacy", **BOTH}))
    assert kept.current() == ("female", "female-id")


def test_bad_voice_default_rejected():
    with pytest.raises(ValueError):
        load_settings({"VOICE_DEFAULT": "robot"})


def test_voice_api():
    app = create_app(load_settings({"SIMULATE": "1", **BOTH}), fake_overrides())
    with TestClient(app, base_url=BASE_URL) as c:
        r = c.get("/voice")
        assert r.status_code == 200
        assert r.json()["selected"] == "female"
        assert r.json()["voice_kind"] == "designed"
        assert {s["gender"]: s["configured"] for s in r.json()["voices"]} == {
            "male": True,
            "female": True,
        }
        r = c.put("/voice", json={"gender": "male"})
        assert r.status_code == 200 and r.json()["selected"] == "male"
        assert c.get("/voice").json()["selected"] == "male"
        r = c.put("/voice", json={"gender": "robot"})
        assert r.status_code == 422 and r.json()["error_code"] == "invalid_request"


def test_voice_api_unconfigured_slot(client):
    r = client.put("/voice", json={"gender": "male"})
    assert r.status_code == 409
    assert r.json()["error_code"] == "voice_not_configured"
