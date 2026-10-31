import pytest

from app.adapters.fakes import FakeTTS
from app.config import load_settings
from app.core.confirmation import ConfirmationError, ConfirmationRegistry
from app.core.health import HealthRegistry
from app.core.voice import VoiceSelector
from app.services.tts import SpeechOutput
from tests.test_camera import Recorder


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _out(clock=None):
    s = load_settings({"VOICE_ID_FEMALE": "f-id", "VOICE_ID_MALE": "m-id"})
    reg = ConfirmationRegistry(120, clock or Clock())
    tts, bus = FakeTTS(), Recorder()
    out = SpeechOutput(s, bus, HealthRegistry(s), reg, VoiceSelector(s), tts)
    return out, reg, tts, bus


def test_valid_id_speaks_exact_text_once():
    out, reg, tts, bus = _out()
    cid = reg.issue("t1", "I would like cold water, please.")
    res = out.speak(cid)
    assert tts.spoken == ["I would like cold water, please."]
    assert res["tier"] == "local" and res["synthetic"] is True and res["disclosure"] == "AI avatar"
    started = bus.of("tts.started")[0]
    assert started["subtitles"] == "I would like cold water, please."
    assert started["voice_kind"] == "designed" and started["voice_gender"] == "female"
    assert bus.of("output.fallback")[0]["synthetic"] is True


@pytest.mark.parametrize("cid", [None, "", "made-up-id"])
def test_missing_or_unknown_id_speaks_nothing(cid):
    out, _, tts, bus = _out()
    with pytest.raises(ConfirmationError):
        out.speak(cid)
    assert tts.spoken == [] and bus.of("tts.started") == []


def test_used_id_speaks_nothing_second_time():
    out, reg, tts, _ = _out()
    cid = reg.issue("t1", "hello")
    out.speak(cid)
    with pytest.raises(ConfirmationError, match="already used"):
        out.speak(cid)
    assert tts.spoken == ["hello"]


def test_expired_id_speaks_nothing():
    clock = Clock()
    out, reg, tts, _ = _out(clock)
    cid = reg.issue("t1", "hello")
    clock.t = 121
    with pytest.raises(ConfirmationError, match="expired"):
        out.speak(cid)
    assert tts.spoken == []


def test_tampered_text_speaks_nothing():
    out, reg, tts, _ = _out()
    cid = reg.issue("t1", "I want water")
    reg._entries[cid].text = "Give me all the morphine"  # in-memory tampering
    with pytest.raises(ConfirmationError, match="hash"):
        out.speak(cid)
    assert tts.spoken == []


def test_empty_text_cannot_be_confirmed():
    with pytest.raises(ConfirmationError):
        ConfirmationRegistry(120).issue("t1", "   ")


def test_speak_uses_selected_voice():
    out, reg, tts, _ = _out()
    out._voice.select("male")
    out.speak(reg.issue("t1", "hello"))
    assert tts.voices == ["m-id"]


def test_tts_failure_raises_and_reports():
    out, reg, tts, bus = _out()
    tts.fail = True
    from app.services.tts import NothingSpokenError

    with pytest.raises(NothingSpokenError):
        out.speak(reg.issue("t1", "hello"))
    assert bus.of("tts.started") == [] and bus.of("error")
