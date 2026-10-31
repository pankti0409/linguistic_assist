import json
import tempfile
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.fakes import FakeGroq, FakeMic, FakeScribe, FakeTTS, silence, tone
from app.config import load_settings
from app.core.turn_machine import (
    AWAITING,
    CAPTURING,
    CLARIFY,
    EDITING,
    FUSING,
    IDLE,
    REJECTED,
    SPEAKING,
    TRANSITIONS,
)
from app.main import create_app
from app.schemas import GestureWord, SpeechEvidence
from tests.conftest import BASE_URL, WS_URL, fake_overrides
from tests.test_camera import wait_for


def fusion_json(*texts, cover=(1, 2, 3), clar=False, q=None):
    return json.dumps(
        {
            "intent": "request",
            "candidates": [{"text": t, "covers": list(cover), "added_words": []} for t in texts],
            "unexplained_fragment_ids": [],
            "clarifying_question": q,
            "clarification_required": clar,
            "reasoning_summary": "answers the partner",
        }
    )


WORKED = fusion_json("I would like cold water, please.", "Cold water, please.")


def make_client(llm_responses=(), env=None, audio=b"", transcripts=()):
    s = load_settings(
        {"SIMULATE": "1", "VOICE_ID_FEMALE": "test-f", "VOICE_ID_MALE": "test-m", **(env or {})}
    )
    o = fake_overrides()
    o.llm = FakeGroq(llm_responses)
    o.tts = FakeTTS()
    o.stt = FakeScribe(transcripts)
    mic = FakeMic(audio)
    o.mic_factory = lambda: mic
    o.data_dir = Path(tempfile.mkdtemp(prefix="ps16-turn-"))
    app = create_app(s, o)
    c = TestClient(app, base_url=BASE_URL)
    c.__enter__()
    for p in ("microphone", "camera", "personalization"):
        c.post("/consent", json={"purpose": p})
    return c, o, mic


@pytest.fixture
def tc():
    c, o, mic = make_client([WORKED])
    yield c, o, mic
    c.__exit__(None, None, None)


def speech(tm, text, ts=None):
    tm._on_speech_final(
        SpeechEvidence(text=text, is_final=True, confidence=0.9),
        type("Seg", (), {"start_ms": ts})(),
    )


# --- transition table --------------------------------------------------------


def test_transition_table_matches_spec():
    assert TRANSITIONS == {
        IDLE: {CAPTURING},
        CAPTURING: {FUSING, IDLE},
        FUSING: {AWAITING},
        AWAITING: {SPEAKING, EDITING, REJECTED, CLARIFY},
        EDITING: {AWAITING},
        SPEAKING: {IDLE, AWAITING},
        REJECTED: {IDLE},
        CLARIFY: {CAPTURING},
    }


def test_illegal_transitions_return_409(tc):
    c, _, _ = tc
    for path, body in [
        ("/turn/end", None),
        ("/turn/reject", None),
        ("/turn/confirm", {"turn_id": "x", "choice_index": 0}),
        ("/turn/clarify", {"answer": "yes"}),
    ]:
        r = c.post(path, json=body)
        assert r.status_code == 409 and r.json()["error_code"] == "illegal_transition", path
    tid = c.post("/turn/start", json={"speaker": "PATIENT"}).json()["turn_id"]
    assert c.post("/turn/start", json={"speaker": "PARTNER"}).status_code == 409
    assert c.post("/turn/confirm", json={"turn_id": tid, "choice_index": 0}).status_code == 409
    assert c.post("/turn/reject").status_code == 409
    assert c.post("/turn/end", json={"turn_id": "other"}).status_code == 409


def test_start_needs_consent_and_leaves_state_unchanged():
    c, _, _ = make_client()
    c.delete("/consent/microphone")
    r = c.post("/turn/start", json={"speaker": "PATIENT", "modalities": ["speech"]})
    assert r.status_code == 403 and c.get("/turn").json()["state"] == "IDLE"
    c.delete("/consent/camera")
    r = c.post("/turn/start", json={"speaker": "PATIENT", "modalities": ["gesture"]})
    assert r.status_code == 403
    c.__exit__(None, None, None)


# --- full patient turn (API smoke test) ------------------------------------------


def test_full_patient_turn_start_to_spoken(tc):
    c, o, _ = tc
    tm = c.app.state.turns
    c.app.state.conversation.add("PARTNER", "Water or tea?")
    with c.websocket_connect(WS_URL) as ws:
        tid = c.post("/turn/start", json={"speaker": "PATIENT", "modalities": ["speech"]}).json()[
            "turn_id"
        ]
        for t in ("wa", "water", "cold"):
            speech(tm, t)
        view = c.post("/turn/end").json()
        assert view["state"] == AWAITING
        assert view["cleaned_fragments"] == ["water", "cold"]
        cand = view["result"]["candidates"][0]
        assert cand["text"] == "I would like cold water, please."
        assert cand["added_words"] == ["i", "would", "like", "please"]
        assert o.tts.spoken == []  # nothing spoken before confirmation
        r = c.post("/turn/confirm", json={"turn_id": tid, "choice_index": 0}).json()
        assert r["state"] == IDLE and r["spoken"]["tier"] == "local"
        types = []
        while "tts.started" not in types:
            types.append(ws.receive_json()["type"])
    assert o.tts.spoken == ["I would like cold water, please."]
    for t in (
        "turn.state",
        "fragment.added",
        "draft.updated",
        "fusion.candidates",
        "confirm.issued",
        "output.fallback",
        "tts.started",
    ):
        assert t in types, t
    assert types.index("confirm.issued") < types.index("tts.started")
    assert c.app.state.conversation.recent()[-1].text == "I would like cold water, please."
    assert c.get("/phrasebook").json()[0]["uses"] == 1
    m = c.get("/metrics").json()
    assert m["turns"][-1]["taps"] == 1 and "fusion_ms" in m["turns"][-1]["stages"]
    assert m["turns"][-1]["tier"] == "local"


def test_partner_turn_goes_to_context_without_fusion():
    audio = silence(300) + tone(500) + silence(900) + tone(500) + silence(300)
    c, o, mic = make_client(audio=audio, transcripts=["Water", "or tea?"])
    c.post("/turn/start", json={"speaker": "PARTNER"})
    mic.wait_done()
    view = c.post("/turn/end").json()
    assert view["state"] == IDLE and view["final_text"] == "Water or tea?"
    assert view["raw_transcripts"] == ["Water", "or tea?"]
    assert c.app.state.conversation.last_partner_line() == "Water or tea?"
    assert o.llm.requests == []  # no fusion for the partner
    c.__exit__(None, None, None)


def test_mic_audio_becomes_fragments_end_to_end():
    audio = silence(300) + tone(500) + silence(900) + tone(500) + silence(900) + tone(500)
    c, o, mic = make_client([WORKED], audio=audio, transcripts=["wa", "water", "cold"])
    c.post("/turn/start", json={"speaker": "PATIENT"})
    mic.wait_done()
    view = c.post("/turn/end").json()
    assert [f["text"] for f in view["fragments"]] == ["wa", "water", "cold"]
    # "wa" is 2 characters, so it is also flagged low_confidence (section 8.5)
    assert set(view["fragments"][0]["flags"]) == {"stutter_prefix", "low_confidence"}
    assert all(f["gap_ms"] >= 0 for f in view["fragments"])
    c.__exit__(None, None, None)


# --- draft closing rules -----------------------------------------------------------


def test_short_silence_does_not_close_but_long_silence_does():
    c, _, _ = make_client([WORKED], env={"FRAGMENT_SILENCE_S": "0.8"})
    tm = c.app.state.turns
    c.post("/turn/start", json={"speaker": "PATIENT"})
    time.sleep(1.0)
    assert tm.state() == CAPTURING  # no fragment yet: silence never closes an empty draft
    speech(tm, "wa")
    time.sleep(0.4)
    speech(tm, "water")
    time.sleep(0.4)
    speech(tm, "cold")
    assert tm.state() == CAPTURING  # pauses shorter than FRAGMENT_SILENCE_S
    assert wait_for(lambda: tm.state() == AWAITING, timeout=4)
    assert tm.current().end_reason == "silence"
    c.__exit__(None, None, None)


def test_noise_does_not_restart_the_silence_clock():
    # D-057: empty finals (noise) used to reset the clock, so the draft never closed
    c, _, _ = make_client([WORKED], env={"FRAGMENT_SILENCE_S": "0.8"})
    tm = c.app.state.turns
    c.post("/turn/start", json={"speaker": "PATIENT"})
    speech(tm, "water")
    t0 = time.monotonic()
    for _ in range(4):
        time.sleep(0.2)
        speech(tm, "")  # Scribe heard only noise
    assert wait_for(lambda: tm.state() == AWAITING, timeout=4)
    assert time.monotonic() - t0 < 1.6  # closed ~0.8 s after "water", not after the noise
    assert tm.current().end_reason == "silence"
    c.__exit__(None, None, None)


def test_silence_counts_from_utterance_end_not_transcript_arrival():
    c, _, _ = make_client([WORKED], env={"FRAGMENT_SILENCE_S": "1.0"})
    tm = c.app.state.turns
    c.post("/turn/start", json={"speaker": "PATIENT"})
    from app.core.timing import now_ms

    time.sleep(1.6)  # the person talks for a while after the turn opens
    # they stopped talking 0.9 s ago; the transcript only arrives now
    tm._on_speech_final(
        SpeechEvidence(text="water", is_final=True, confidence=0.9),
        type("Seg", (), {"start_ms": now_ms() - 1500, "end_ms": now_ms() - 900})(),
    )
    t0 = time.monotonic()
    assert wait_for(lambda: tm.state() == AWAITING, timeout=4)
    assert time.monotonic() - t0 < 0.7
    c.__exit__(None, None, None)


def test_open_utterance_holds_the_draft_open():
    c, _, _ = make_client([WORKED], env={"FRAGMENT_SILENCE_S": "0.5"})
    tm = c.app.state.turns
    c.post("/turn/start", json={"speaker": "PATIENT"})
    speech(tm, "water")
    type(tm.scribe).busy = property(lambda self: True)  # mid-word or still transcribing
    try:
        time.sleep(1.0)
        assert tm.state() == CAPTURING
    finally:
        del type(tm.scribe).busy
    assert wait_for(lambda: tm.state() == AWAITING, timeout=4)
    c.__exit__(None, None, None)


def test_max_duration_closes_draft():
    c, _, _ = make_client(
        [fusion_json("Water.", "Water please.", cover=(1,))],
        env={"FRAGMENT_MAX_S": "0.6", "FRAGMENT_SILENCE_S": "30"},
    )
    tm = c.app.state.turns
    c.post("/turn/start", json={"speaker": "PATIENT"})
    speech(tm, "water")
    assert wait_for(lambda: tm.state() == AWAITING, timeout=4)
    assert tm.current().end_reason == "max_duration"
    c.__exit__(None, None, None)


def test_commit_gesture_ends_turn_and_clear_empties_draft(tc):
    c, _, _ = tc
    tm = c.app.state.turns
    c.post("/turn/start", json={"speaker": "PATIENT", "modalities": ["speech", "gesture"]})
    speech(tm, "tea")
    tm._on_gesture_word(GestureWord(word="__CLEAR__", token="Victory|Left", score=0.9, ts_ms=1))
    assert len(tm.current().collector) == 0
    for t in ("wa", "water"):
        speech(tm, t)
    tm._on_gesture_word(GestureWord(word="cold", token="Victory|Right", score=0.92, ts_ms=2))
    frags = tm.current().collector.items()
    assert frags[-1].source == "gesture" and frags[-1].confidence == 0.92
    tm._on_gesture_word(
        GestureWord(word="__COMMIT__", token="Closed_Fist|Right", score=0.9, ts_ms=3)
    )
    assert wait_for(lambda: tm.state() == AWAITING)
    assert tm.current().end_reason == "commit"


def test_gesture_words_ignored_without_gesture_modality(tc):
    c, _, _ = tc
    tm = c.app.state.turns
    c.post("/turn/start", json={"speaker": "PATIENT", "modalities": ["speech"]})
    tm._on_gesture_word(GestureWord(word="yes", token="Thumb_Up|Left", score=0.9, ts_ms=1))
    assert len(tm.current().collector) == 0


# --- confirm / edit / reject -----------------------------------------------------------


def _to_awaiting(c, texts=("wa", "water", "cold")):
    tm = c.app.state.turns
    tid = c.post("/turn/start", json={"speaker": "PATIENT"}).json()["turn_id"]
    for t in texts:
        speech(tm, t)
    c.post("/turn/end")
    return tid


def test_edit_is_shown_back_before_speaking(tc):
    c, o, _ = tc
    tid = _to_awaiting(c)
    r = c.post("/turn/confirm", json={"turn_id": tid, "edited_text": "Cold water  please"}).json()
    assert r == {
        "turn_id": tid,
        "state": AWAITING,
        "final_text": "Cold water please",
        "confirm_required": True,
    }
    assert o.tts.spoken == []
    r = c.post("/turn/confirm", json={"turn_id": tid, "edited_text": "Cold water please"}).json()
    assert r["state"] == IDLE and o.tts.spoken == ["Cold water please"]
    entry = c.get("/phrasebook").json()[0]
    assert entry["text"] == "Cold water please" and entry["uses"] == 2  # edited counts double
    assert c.get("/metrics").json()["turns"][-1]["edits"] == 1


def test_reject_stores_nothing_and_speaks_nothing(tc):
    c, o, _ = tc
    _to_awaiting(c)
    assert c.post("/turn/reject").json()["state"] == IDLE
    assert o.tts.spoken == [] and c.get("/phrasebook").json() == []
    assert c.app.state.conversation.recent() == []


def test_bad_choice_index_is_422(tc):
    c, o, _ = tc
    tid = _to_awaiting(c)
    r = c.post("/turn/confirm", json={"turn_id": tid, "choice_index": 7})
    assert r.status_code == 422 and o.tts.spoken == []


def test_output_failure_returns_to_awaiting_and_new_id_needed(tc):
    c, o, _ = tc
    tid = _to_awaiting(c)
    o.tts.fail = True
    r = c.post("/turn/confirm", json={"turn_id": tid, "choice_index": 0})
    assert r.status_code == 502 and c.get("/turn").json()["state"] == AWAITING
    o.tts.fail = False
    r = c.post("/turn/confirm", json={"turn_id": tid, "choice_index": 0})
    assert r.status_code == 200 and o.tts.spoken == ["I would like cold water, please."]


def test_no_route_can_speak_without_confirmation(tc):
    c, o, _ = tc
    routes = {getattr(r, "path", "") for r in c.app.routes}
    assert not any("speak" in p for p in routes)  # speaking is reachable only via confirm
    _to_awaiting(c)
    for bad in ({"turn_id": "wrong", "choice_index": 0}, {"choice_index": 0}):
        c.post("/turn/confirm", json=bad)
    assert o.tts.spoken == []


# --- clarification loop -------------------------------------------------------------------


def test_clarification_answer_becomes_fragment_and_reruns():
    q1 = fusion_json(clar=True, q="Do you want water?")
    final = fusion_json("I would like water, please.", "Water, please.", cover=(1, 2))
    c, o, _ = make_client([q1, final])
    tm = c.app.state.turns
    tid = c.post("/turn/start", json={"speaker": "PATIENT"}).json()["turn_id"]
    speech(tm, "water")
    view = c.post("/turn/end").json()
    assert view["result"]["clarifying_question"] == "Do you want water?"
    view = c.post("/turn/clarify", json={"answer": "yes"}).json()
    last = view["fragments"][-1]
    assert last["text"] == "yes" and last["flags"] == ["answer_to_question"]
    assert view["clarify_rounds"] == 1 and view["result"]["candidates"]
    sent = json.loads(o.llm.requests[1]["user"])
    assert sent["clarifications"] == [{"question": "Do you want water?", "answer": "yes"}]
    assert c.post("/turn/confirm", json={"turn_id": tid, "choice_index": 0}).status_code == 200
    c.__exit__(None, None, None)


def test_thumbs_up_answers_the_question():
    q1 = fusion_json(clar=True, q="Do you want water?")
    final = fusion_json("I would like water, please.", "Water, please.", cover=(1, 2))
    c, _, _ = make_client([q1, final])
    tm = c.app.state.turns
    c.post("/turn/start", json={"speaker": "PATIENT"})
    speech(tm, "water")
    c.post("/turn/end")
    tm._on_gesture_word(GestureWord(word="yes", token="Thumb_Up|Right", score=0.9, ts_ms=1))
    assert wait_for(lambda: tm.current().clarify_rounds == 1 and tm.state() == AWAITING)
    assert tm.current().result.candidates
    c.__exit__(None, None, None)


def test_rounds_cap_at_two_then_plain_fragments():
    q = fusion_json(clar=True, q="Do you mean the window?")
    c, o, _ = make_client([q, q, q])
    tm = c.app.state.turns
    c.post("/turn/start", json={"speaker": "PATIENT"})
    for t in ("win", "window", "open"):
        speech(tm, t)
    c.post("/turn/end")
    c.post("/turn/clarify", json={"answer": "no"})
    view = c.post("/turn/clarify", json={"answer": "no"}).json()
    assert view["clarify_rounds"] == 2
    assert view["fallback"] == {"text": "window open", "prompt": "choose, edit or repeat"}
    assert view["result"]["clarifying_question"] is None
    r = c.post("/turn/clarify", json={"answer": "yes"})
    assert r.status_code == 409  # no third round
    assert len(o.llm.requests) == 3
    tid = view["turn_id"]
    c.post("/turn/confirm", json={"turn_id": tid, "edited_text": "Open the window"})
    r = c.post("/turn/confirm", json={"turn_id": tid, "edited_text": "Open the window"})
    assert r.status_code == 200 and o.tts.spoken == ["Open the window"]
    c.__exit__(None, None, None)


def test_concurrent_end_calls_close_once(tc):
    c, o, _ = tc
    tm = c.app.state.turns
    c.post("/turn/start", json={"speaker": "PATIENT"})
    for t in ("wa", "water", "cold"):
        speech(tm, t)
    codes = []

    def end():
        codes.append(c.post("/turn/end").status_code)

    threads = [threading.Thread(target=end) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(codes) == [200, 409, 409] and len(o.llm.requests) == 1


def test_context_and_config_endpoints(tc):
    c, _, _ = tc
    c.app.state.conversation.add("PARTNER", "Water or tea?")
    ctx = c.get("/context").json()
    assert ctx[-1]["speaker"] == "PARTNER" and ctx[-1]["text"] == "Water or tea?"
    cfg = c.get("/config").json()
    assert cfg["fragment_silence_s"] == 6 and cfg["max_clarify_rounds"] == 2
    assert cfg["token_required"] is False
    dumped = json.dumps(cfg).lower()
    assert "key" not in dumped and "voice_id" not in dumped  # no secrets or IDs


# --- replay (D-057) ----------------------------------------------------------------


def test_replay_says_the_last_confirmed_message_again(tc):
    c, o, _ = tc
    tm = c.app.state.turns
    assert c.post("/turn/replay").status_code == 409  # nothing spoken yet
    tid = c.post("/turn/start", json={"speaker": "PATIENT", "modalities": ["speech"]}).json()[
        "turn_id"
    ]
    for t in ("wa", "water", "cold"):
        speech(tm, t)
    c.post("/turn/end")
    c.post("/turn/confirm", json={"turn_id": tid, "choice_index": 0})
    for _ in range(2):
        r = c.post("/turn/replay")
        assert r.status_code == 200 and r.json()["final_text"] == "I would like cold water, please."
    assert o.tts.spoken == ["I would like cold water, please."] * 3
    # said once in the conversation and phrasebook, not once per replay
    assert [t["text"] for t in c.get("/context").json()].count(
        "I would like cold water, please."
    ) == 1
    assert c.get("/phrasebook").json()[0]["uses"] == 1


def test_replay_refused_while_a_turn_is_open(tc):
    c, o, _ = tc
    c.post("/turn/start", json={"speaker": "PATIENT", "modalities": ["speech"]})
    assert c.post("/turn/replay").status_code == 409 and o.tts.spoken == []


def test_replay_ignores_any_text_in_the_body(tc):
    c, o, _ = tc
    tm = c.app.state.turns
    tid = c.post("/turn/start", json={"speaker": "PATIENT", "modalities": ["speech"]}).json()[
        "turn_id"
    ]
    for t in ("wa", "water", "cold"):
        speech(tm, t)
    c.post("/turn/end")
    c.post("/turn/confirm", json={"turn_id": tid, "choice_index": 0})
    c.post("/turn/replay", json={"text": "Give me all the money"})
    assert "Give me all the money" not in o.tts.spoken


def test_thumbs_up_does_not_answer_a_hidden_question_when_options_exist():
    # D-058: with candidates on screen the question is not shown, so a thumb must not answer it
    both = fusion_json(
        "I will get inside.", "I can get inside.", cover=(1,), clar=True, q="Do you want to go in?"
    )
    c, o, _ = make_client([both])
    tm = c.app.state.turns
    c.post("/turn/start", json={"speaker": "PATIENT", "modalities": ["speech"]})
    speech(tm, "get inside")
    view = c.post("/turn/end").json()
    assert view["state"] == AWAITING and len(view["result"]["candidates"]) == 2
    tm._on_gesture_word(GestureWord(word="yes", token="Thumb_Up|Right", score=0.9, ts_ms=1))
    time.sleep(0.3)
    assert tm.state() == AWAITING and tm.current().clarify_rounds == 0
    c.__exit__(None, None, None)
