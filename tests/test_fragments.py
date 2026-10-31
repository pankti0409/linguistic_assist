from app.core.fragments import FragmentCollector, clean, tokens
from app.schemas import Fragment


def F(i, text, source="speech", flags=()):
    return Fragment(id=i, ts_ms=i * 1000, gap_ms=500, source=source, text=text, flags=list(flags))


def flags_of(frags):
    return {f.text: f.flags for f in frags}


def test_worked_example_from_spec():
    flagged, cleaned = clean([F(1, "wa"), F(2, "water"), F(3, "cold")])
    assert cleaned == ["water", "cold"]
    assert flags_of(flagged)["wa"] == ["stutter_prefix"]


def test_exact_repeat_collapses_across_and_within_fragments():
    flagged, cleaned = clean([F(1, "water"), F(2, "water"), F(3, "cold")])
    assert cleaned == ["water", "cold"] and flagged[1].flags == ["repeat"]
    flagged, cleaned = clean([F(1, "water water"), F(2, "cold")])
    assert cleaned == ["water", "cold"] and flagged[0].flags == ["repeat"]


def test_repeat_compares_with_last_kept_fragment():
    flagged, cleaned = clean([F(1, "water"), F(2, "wa"), F(3, "water")])
    assert cleaned == ["water"]
    assert flagged[1].flags == ["stutter_prefix"] and flagged[2].flags == ["repeat"]


def test_stutter_chain_and_inner_stutter():
    _, cleaned = clean([F(1, "w"), F(2, "wa"), F(3, "water")])
    assert cleaned == ["water"]
    flagged, cleaned = clean([F(1, "wa water please")])
    assert cleaned == ["water please"] and flagged[0].flags == ["stutter_prefix"]


def test_fillers_flagged_and_dropped_from_cleaned_only():
    flagged, cleaned = clean([F(1, "um"), F(2, "water"), F(3, "uh hmm")])
    assert cleaned == ["water"]
    assert flagged[0].flags == ["filler"] and flagged[2].flags == ["filler"]
    assert [f.text for f in flagged] == ["um", "water", "uh hmm"]  # raw kept, in order


def test_unknown_fragments_are_kept():
    _, cleaned = clean([F(1, "zorp"), F(2, "blanket"), F(3, "ghar")])
    assert cleaned == ["zorp", "blanket", "ghar"]


def test_gesture_words_are_not_treated_as_stutters():
    _, cleaned = clean([F(1, "wa", "gesture"), F(2, "water")])
    assert cleaned == ["wa", "water"]


def test_answer_to_question_is_never_dropped():
    _, cleaned = clean([F(1, "yes"), F(2, "yes", flags=["answer_to_question"])])
    assert cleaned == ["yes", "yes"]


def test_hindi_tokens_keep_matras():
    assert tokens("मुझे पानी चाहिए") == ["मुझे", "पानी", "चाहिए"]
    _, cleaned = clean([F(1, "पा"), F(2, "पानी")])
    assert cleaned == ["पानी"]


def test_input_fragments_are_not_mutated():
    raw = [F(1, "wa"), F(2, "water")]
    clean(raw)
    assert raw[0].flags == []


def test_collector_keeps_order_and_gaps():
    c = FragmentCollector(started_ms=1000)
    a = c.add("speech", "wa", ts_ms=1500)
    b = c.add("gesture", "yes", ts_ms=4500, confidence=0.9)
    assert (a.id, a.gap_ms) == (1, 500) and (b.id, b.gap_ms) == (2, 3000)
    assert [f.text for f in c.items()] == ["wa", "yes"] and len(c) == 2
    c.clear()
    assert len(c) == 0
