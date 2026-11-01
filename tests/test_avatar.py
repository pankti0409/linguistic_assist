import base64

import pytest

from app.adapters.fakes import FakeAvatar, FakeTavusAPI, FakeTTS
from app.config import load_settings
from app.core.confirmation import ConfirmationError, ConfirmationRegistry
from app.core.consent import ConsentRegistry
from app.core.errors import ConsentRequiredError
from app.core.health import HealthRegistry
from app.core.voice import VoiceSelector
from app.services.avatar import AvatarService, AvatarSessionError, conversation_body
from app.services.tts import NothingSpokenError, SpeechOutput
from tests.test_camera import Recorder
from tests.test_turns import make_client, speech

ENV = {
    "TAVUS_API_KEY": "k",
    "TAVUS_REPLICA_ID": "rbd2cdb9a3f3",
    "TAVUS_PERSONA_ID": "pb57f82ae2b1",
    "VOICE_ID_FEMALE": "f-id",
}


def stack(transport=None, api=None, granted=True, **avatar_kw):
    s = load_settings(ENV)
    consent = ConsentRegistry()
    if granted:
        consent.grant("avatar")
    bus, health = Recorder(), HealthRegistry(s)
    transport = transport or FakeAvatar()
    api = api or FakeTavusAPI()
    kw = {"start_timeout_s": 0.2, **avatar_kw}
    avatar = AvatarService(s, bus, health, consent, api, lambda: transport, **kw)
    reg = ConfirmationRegistry(120)
    tts = FakeTTS()
    out = SpeechOutput(s, bus, health, reg, VoiceSelector(s), tts, avatar)
    return avatar, out, reg, tts, transport, api, bus, health


def test_conversation_body_matches_openapi_names_and_blocks_greeting():
    body = conversation_body(load_settings(ENV))
    assert body["face_id"] == "rbd2cdb9a3f3" and body["pal_id"] == "pb57f82ae2b1"
    assert body["dynamic_greeting"] is False  # the PAL has it on; never speak unconfirmed
    assert "custom_greeting" not in body
    assert set(body["properties"]) <= {
        "max_call_duration",
        "participant_left_timeout",
        "participant_absent_timeout",
        "enable_closed_captions",
    }


def test_session_needs_avatar_consent():
    avatar, *_ = stack(granted=False)
    with pytest.raises(ConsentRequiredError):
        avatar.create_session()


def test_session_is_receive_only_and_backend_joins():
    avatar, _, _, _, transport, api, _, health = stack()
    s = avatar.create_session()
    assert s["conversation_url"] == "https://tavus.daily.co/c0001"
    assert s["join_settings"] == {"camera": False, "microphone": False}
    assert s["synthetic"] is True and s["disclosure"] == "AI avatar"
    assert transport.joined == [s["conversation_url"]]
    assert health.get("avatar").status == "ok"
    assert avatar.create_session() == s and len(api.created) == 1  # idempotent


def test_failed_join_ends_the_conversation():
    avatar, _, _, _, _, api, _, health = stack(transport=FakeAvatar(fail_join=True))
    with pytest.raises(AvatarSessionError):
        avatar.create_session()
    assert api.ended == ["c0001"] and health.get("avatar").status == "unavailable"


def test_create_failure_is_reported():
    avatar, *_ = stack(api=FakeTavusAPI(fail=True))
    with pytest.raises(AvatarSessionError):
        avatar.create_session()


def test_tier1_audio_echo_speaks_once():
    avatar, out, reg, tts, transport, *_ = stack(chunk_bytes=4)
    avatar.create_session()
    res = out.speak(reg.issue("t1", "I would like cold water, please."))
    assert res["tier"] == "avatar_audio"
    audio = transport.echoes("audio")
    assert len(audio) > 1 and transport.echoes("text") == []
    assert [m["properties"]["done"] for m in audio] == [False] * (len(audio) - 1) + [True]
    assert len({m["properties"]["inference_id"] for m in audio}) == 1
    assert all(m["properties"]["sample_rate"] == 16000 for m in audio)
    pcm = b"".join(base64.b64decode(m["properties"]["audio"]) for m in audio)
    assert pcm.startswith(b"\x00\x00")  # FakeTTS audio, reassembled in order
    assert all(m["synthetic"] is True and m["disclosure"] == "AI avatar" for m in transport.sent)
    assert tts.spoken == ["I would like cold water, please."]  # synthesised once


def test_tier2_text_echo_after_silent_audio_with_interrupt_between():
    transport = FakeAvatar(silent_modalities=("audio",))
    avatar, out, reg, tts, transport, *_ = stack(transport)
    avatar.create_session()
    res = out.speak(reg.issue("t1", "Hello"))
    assert res["tier"] == "avatar_text"
    kinds = [(m["event_type"], (m.get("properties") or {}).get("modality")) for m in transport.sent]
    i_audio = max(i for i, k in enumerate(kinds) if k[1] == "audio")
    i_text = kinds.index(("conversation.echo", "text"))
    assert ("conversation.interrupt", None) in kinds[i_audio:i_text]  # never two at once
    assert transport.echoes("text")[0]["properties"] == {
        "modality": "text",
        "text": "Hello",
        "done": True,
    }


def test_tier3_local_when_avatar_is_silent():
    transport = FakeAvatar(silent_modalities=("audio", "text"))
    avatar, out, reg, tts, transport, _, bus, _ = stack(transport)
    avatar.create_session()
    res = out.speak(reg.issue("t1", "Hello"))
    assert res["tier"] == "local"
    assert bus.of("output.fallback")[0]["reason"].count("did not start speaking") == 2
    assert transport.sent[-1]["event_type"] == "conversation.interrupt"
    assert len(bus.of("tts.started")) == 1  # exactly one tier delivered audio


def test_killing_tavus_falls_back_to_local():
    class Dead(FakeAvatar):
        def send(self, message):
            raise ConnectionError("network gone")

    avatar, out, reg, tts, _, _, bus, _ = stack(Dead())
    avatar.create_session()
    assert out.speak(reg.issue("t1", "Hello"))["tier"] == "local"
    assert "audio echo failed" in bus.of("output.fallback")[0]["reason"]


def test_no_session_means_local_only():
    _, out, reg, _, transport, _, bus, _ = stack()
    assert out.speak(reg.issue("t1", "Hello"))["tier"] == "local"
    assert transport.sent == [] and bus.of("output.fallback")[0]["reason"] == "no avatar session"


def test_audio_echo_can_be_disabled():
    avatar, out, reg, _, transport, *_ = stack(audio_echo=False)
    avatar.create_session()
    assert out.speak(reg.issue("t1", "Hello"))["tier"] == "avatar_text"
    assert transport.echoes("audio") == []


def test_gate_still_applies_with_avatar():
    avatar, out, reg, tts, transport, *_ = stack()
    avatar.create_session()
    with pytest.raises(ConfirmationError):
        out.speak("forged")
    cid = reg.issue("t1", "Hello")
    out.speak(cid)
    with pytest.raises(ConfirmationError):
        out.speak(cid)
    assert len(transport.echoes()) == len(transport.echoes("audio")) and tts.spoken == ["Hello"]


def test_all_tiers_failing_raises():
    transport = FakeAvatar(silent_modalities=("audio", "text"))
    avatar, out, reg, tts, *_ = stack(transport)
    avatar.create_session()
    tts.fail = True
    with pytest.raises(NothingSpokenError):
        out.speak(reg.issue("t1", "Hello"))


def test_speaking_events_and_guardrails_forwarded():
    avatar, _, _, _, _, _, bus, _ = stack()
    avatar.create_session()
    avatar._on_message({"event_type": "conversation.replica.started_speaking"})
    avatar._on_message(
        {
            "event_type": "conversation.replica.stopped_speaking",
            "properties": {"duration": 2.5, "interrupted": False},
        }
    )
    ev = bus.of("avatar.speaking")
    assert ev[0]["speaking"] is True and ev[1] == {
        "speaking": False,
        "duration": 2.5,
        "interrupted": False,
        "synthetic": True,
        "disclosure": "AI avatar",
    }


def test_avatar_api_reject_interrupts_and_revoke_ends_session():
    c, o, _ = make_client(
        [
            '{"intent":"r","candidates":[{"text":"Water.","covers":[1],'
            '"added_words":[]},{"text":"Water, please.","covers":[1],'
            '"added_words":[]}],"unexplained_fragment_ids":[],'
            '"clarifying_question":null,"clarification_required":false,'
            '"reasoning_summary":"x"}'
        ]
    )
    assert c.post("/avatar/session").status_code == 403
    c.post("/consent", json={"purpose": "avatar"})
    s = c.post("/avatar/session").json()
    assert s["conversation_url"] and s["join_settings"]["camera"] is False
    transport = c.app.state.avatar._transport
    tm = c.app.state.turns
    c.post("/turn/start", json={"speaker": "PATIENT"})
    assert transport.sent[-1]["event_type"] == "conversation.interrupt"  # new turn
    speech(tm, "water")
    c.post("/turn/end")
    n = len(transport.sent)
    c.post("/turn/reject")
    assert transport.sent[n]["event_type"] == "conversation.interrupt"
    r = c.post(
        "/avatar/guardrail",
        json={
            "event_type": "guardrail.triggered",
            "guardrail_name": "verbatim_relay",
            "text": "secret",
        },
    )
    assert r.json() == {"received": True}
    c.delete("/consent/avatar")
    assert c.get("/avatar/session").json()["conversation_id"] is None
    assert c.app.state.avatar._api.ended == ["c0001"]
    c.__exit__(None, None, None)
