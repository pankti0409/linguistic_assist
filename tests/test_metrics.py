import pytest

from evaluation import metrics as M
from evaluation.make_fragments import make_fragments
from evaluation.run_eval import build_packet, judge, summarise

FW = {"i", "would", "like", "please", "a", "the", "to", "मुझे", "चाहिए"}


# --- WER against hand-computed cases ---------------------------------------------


def test_wer_hand_computed():
    assert M.wer("water or tea", "water or tea") == 0
    assert M.wer("water or tea", "water and tea") == pytest.approx(100 / 3)  # 1 S / 3
    assert M.wer("water or tea", "water tea") == pytest.approx(100 / 3)  # 1 D / 3
    assert M.wer("water or tea", "water or hot tea") == pytest.approx(100 / 3)  # 1 I / 3
    assert M.wer("a b c d", "x b d e f") == pytest.approx(4 / 4 * 100)  # S + D + 2 I = 4
    assert M.edit_counts(list("abcd"), list("xbdef")) == (1, 1, 2)
    assert M.wer("Water, or TEA?", "water or tea") == 0  # case and punctuation ignored
    with pytest.raises(ValueError):
        M.wer("", "x")


def test_corpus_wer_weights_by_reference_length():
    assert M.corpus_wer([("a b c d", "a b c d"), ("e f", "x f")]) == pytest.approx(100 / 6)
    assert M.corpus_wer([]) is None


def test_hindi_wer_tokens():
    assert M.wer("मुझे पानी चाहिए।", "मुझे पानी चाहिए") == 0


# --- acceptance / intent ------------------------------------------------------------


def test_acceptance_ignores_function_words_only():
    target = "I would like cold water, please."
    assert M.accepted("Cold water, please.", target, FW)
    assert M.accepted("I would like cold water.", target, FW)
    assert not M.accepted("I would like water.", target, FW)  # meaning word missing
    assert not M.accepted("I would like cold tea.", target, FW)


def test_intent_rules():
    assert M.intent_correct("I want cold water", False, False, ["water", "cold"])
    assert not M.intent_correct("I want water", False, False, ["water", "cold"])
    assert M.intent_correct(None, True, True, [])
    assert not M.intent_correct("Water.", False, True, [])  # should have asked
    assert not M.intent_correct("Water.", True, False, ["water"])  # asked needlessly


def test_unsupported_words_check():
    assert M.unsupported_words("I would like cold water", "wa water cold", FW) == []
    assert M.unsupported_words("Meera brings cold water", "water cold", FW) == ["meera", "brings"]


def test_percentile_nearest_rank_and_none():
    assert M.percentile([], 50) is None
    assert M.percentile([5], 95) == 5
    vals = list(range(1, 101))
    assert M.percentile(vals, 50) == 50 and M.percentile(vals, 95) == 95
    assert M.rate(0, 0) is None and M.mean([]) is None


# --- synthetic fragments -------------------------------------------------------------


def test_make_fragments_is_seeded_and_keeps_content_words():
    a = make_fragments("I would like some juice please", seed=1, function_words=FW)
    b = make_fragments("I would like some juice please", seed=1, function_words=FW)
    assert a == b
    texts = [f["text"] for f in a]
    assert "juice" in texts and all(f["source"] == "speech" for f in a)
    assert all(800 <= f["gap_ms"] <= 4500 for f in a)


# --- harness pieces ---------------------------------------------------------------------


SC = {
    "id": "x",
    "language": "en",
    "category": "context_qa",
    "fragments": [
        {"source": "speech", "text": "wa", "gap_ms": 1000},
        {"source": "speech", "text": "water", "gap_ms": 1000},
    ],
    "partner_line": "Water or tea?",
    "gesture_tokens": [{"word": "yes", "token": "Thumb_Up|Left", "score": 0.9}],
    "lip_ref": "water",
    "profile_terms": ["Meera"],
    "phrasebook": ["Please call Meera."],
    "target_sentence": "I would like water.",
    "allowed_additions": [],
    "intent_keywords": ["water"],
    "expected_clarification": False,
}


def test_ablation_packets_add_evidence_step_by_step():
    a, ap, b, c = (build_packet(SC, k) for k in ("A", "A+", "B", "C"))
    assert [f.source for f in a.fragments] == ["speech", "speech"]
    assert a.profile_terms == [] and a.phrasebook_hits == [] and a.context
    assert ap.profile_terms == ["Meera"] and ap.phrasebook_hits[0].text == "Please call Meera."
    assert [f.source for f in b.fragments][-1] == "gesture"
    assert [f.source for f in c.fragments][-1] == "lip"


def test_judge_and_effort_policy():
    p = build_packet(SC, "A")
    good = judge(SC, p, ["Water, please.", "I would like water."], [[1, 2], [1, 2]], False, FW)
    assert good["first_accepted"] and good["any_accepted"] and good["coverage"] == 1.0
    assert good["taps"] + good["edits"] == 1 and good["n_unsupported"] == 0
    bad = judge(SC, p, ["Tea, please."], [[1, 2]], False, FW)
    assert not bad["any_accepted"] and bad["taps"] + bad["edits"] == 3
    s = summarise(
        [
            {
                **good,
                "status": "ok",
                "language": "en",
                "expected_clarification": False,
                "fusion_ms": 100.0,
            },
            {"status": "not_run", "language": "en", "expected_clarification": False},
        ]
    )
    assert s["evaluated"] == 1 and s["not_run"] == 1 and s["first_accept"] == 1.0
