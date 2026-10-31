import json

from app.adapters.fakes import FakeGroq
from app.config import load_settings
from app.core.fragments import clean
from app.core.health import HealthRegistry
from app.schemas import DialogueTurn, EvidencePacket, Fragment, PhraseEntry
from app.services.fusion import FUSION_SCHEMA, FusionService, packet_json

S = load_settings({})


def F(i, text, source="speech", flags=()):
    return Fragment(id=i, ts_ms=i * 1000, gap_ms=900, source=source, text=text, flags=list(flags))


def packet(frags, partner="Water or tea?", **kw):
    flagged, cleaned = clean(frags)
    ctx = [DialogueTurn(speaker="PARTNER", text=partner, ts_ms=0)] if partner else []
    return EvidencePacket(
        turn_id="t",
        speaker="PATIENT",
        ts_ms=1,
        fragments=flagged,
        cleaned_fragments=cleaned,
        context=ctx,
        **kw,
    )


def out(*cands, clar=False, q=None, unexplained=()):
    return json.dumps(
        {
            "intent": "request_drink",
            "candidates": [{"text": t, "covers": cov, "added_words": []} for t, cov in cands],
            "unexplained_fragment_ids": list(unexplained),
            "clarifying_question": q,
            "clarification_required": clar,
            "reasoning_summary": "answers the partner's question",
        }
    )


WORKED = [F(1, "wa"), F(2, "water"), F(3, "cold")]


def svc(*responses):
    llm = FakeGroq(responses)
    return FusionService(S, HealthRegistry(S), llm), llm


def test_worked_example_candidates_and_added_words():
    f, llm = svc(
        out(("I would like cold water, please.", [1, 2, 3]), ("Cold water, please.", [1, 2, 3]))
    )
    r = f.reconstruct(packet(WORKED))
    assert not r.clarification_required and len(r.candidates) == 2
    assert r.candidates[0].text == "I would like cold water, please."
    assert r.candidates[0].added_words == ["i", "would", "like", "please"]  # computed in code
    req = llm.requests[0]
    assert req["temperature"] == 0.2 and req["max_tokens"] <= 300
    sent = json.loads(req["user"])
    assert sent["cleaned_fragments"] == ["water", "cold"]
    assert sent["context"][0] == {"speaker": "PARTNER", "text": "Water or tea?"}


def test_only_the_packet_is_sent_never_media():
    p = packet(WORKED)
    body = packet_json(p)
    assert set(json.loads(body)) == set(EvidencePacket.model_fields)
    assert "frame" not in body and "audio" not in body and "pcm" not in body


def test_retry_once_then_clarify_on_invalid_output():
    f, llm = svc("not json", '{"intent": "x"}')
    r = f.reconstruct(packet(WORKED))
    assert r.clarification_required and r.candidates == [] and len(llm.requests) == 2
    assert len(f.last_debug["errors"]) == 2


def test_retry_succeeds_on_second_attempt():
    f, llm = svc(
        "{broken", out(("I would like cold water.", [1, 2, 3]), ("Cold water.", [1, 2, 3]))
    )
    r = f.reconstruct(packet(WORKED))
    assert not r.clarification_required and len(llm.requests) == 2


def test_coverage_error_triggers_retry():
    bad = out(("Cold water.", [3]), ("Water.", [2]))  # leaves fragments unaccounted for
    f, llm = svc(bad, bad)
    r = f.reconstruct(packet(WORKED))
    assert r.clarification_required and "unaccounted" in f.last_debug["errors"][0]


def test_llm_exception_retries_then_clarifies():
    class Boom:
        calls = 0

        def complete_json(self, *a, **k):
            Boom.calls += 1
            raise ConnectionError("down")

    f = FusionService(S, HealthRegistry(S), Boom())
    r = f.reconstruct(packet(WORKED))
    assert r.clarification_required and Boom.calls == 2


def test_post_validator_drops_invented_name_number_medicine():
    f, _ = svc(
        out(
            ("I would like cold water, please.", [1, 2, 3]),
            ("Meera, bring cold water.", [1, 2, 3]),  # invented name + verb
            ("I want 2 cold water.", [1, 2, 3]),  # number (and "want" is not allowlisted)
        )
    )
    r = f.reconstruct(packet(WORKED))
    texts = [c.text for c in r.candidates]
    assert texts == ["I would like cold water, please."]
    assert r.clarification_required  # one survivor -> yes/no confirmation question
    assert r.clarifying_question == 'Did you mean: "I would like cold water, please."?'
    unsupported = {w for d in f.last_debug["dropped"] for w in d["unsupported"]}
    assert {"meera", "bring", "2", "want"} <= unsupported


def test_medicine_not_in_evidence_is_dropped_but_allowed_when_in_profile():
    resp = out(("I need my paracetamol.", [1]), ("My paracetamol, please.", [1]))
    f, _ = svc(resp)
    r = f.reconstruct(packet([F(1, "need")], partner=None))
    assert r.candidates == [] and r.clarification_required
    f, _ = svc(resp)
    r = f.reconstruct(packet([F(1, "need")], partner=None, profile_terms=["paracetamol"]))
    assert len(r.candidates) == 2


def test_negation_cannot_be_added():
    f, _ = svc(out(("I do not want water.", [1]), ("No water.", [1])))
    r = f.reconstruct(packet([F(1, "water")], partner=None))
    assert r.candidates == []  # "not" / "no" are not function-word additions


def test_words_from_partner_and_phrasebook_are_traceable():
    f, _ = svc(out(("Tea, please.", [1]), ("I would like tea.", [1])))
    r = f.reconstruct(packet([F(1, "that")]))  # "tea" comes from the partner's line
    assert [c.added_words for c in r.candidates][0] == ["tea", "please"]
    f, _ = svc(out(("Please open the window.", [1]), ("Open the window, please.", [1])))
    hits = [PhraseEntry(text="Please open the window", uses=3, last_used_ms=0)]
    r = f.reconstruct(packet([F(1, "window")], partner=None, phrasebook_hits=hits))
    assert len(r.candidates) == 2


def test_hindi_function_words_pass():
    f, _ = svc(out(("मुझे पानी चाहिए।", [1]), ("पानी चाहिए।", [1])))
    r = f.reconstruct(packet([F(1, "पानी")], partner=None, language_pref="hi"))
    assert len(r.candidates) == 2 and r.candidates[0].added_words == ["मुझे", "चाहिए"]


def test_lip_only_evidence_forces_clarification():
    f, _ = svc(out(("I want water.", [1]), ("Water.", [1])))
    p = packet([F(1, "water", source="lip")], partner=None)
    r = f.reconstruct(p)
    assert r.clarification_required and r.clarifying_question
    # lip plus speech is not lip-only
    f, _ = svc(out(("Water, please.", [1, 2]), ("Water.", [1, 2])))
    r = f.reconstruct(packet([F(1, "water", source="lip"), F(2, "water")], partner=None))
    assert not r.clarification_required


def test_no_content_fragments_skip_the_llm():
    f, llm = svc()
    r = f.reconstruct(packet([F(1, "um")], partner=None))
    assert r.clarification_required and llm.requests == []


def test_schema_is_strict_compatible():
    def walk(node):
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
            for v in node["properties"].values():
                walk(v)
        if node.get("type") == "array":
            walk(node["items"])

    walk(FUSION_SCHEMA)
