"""Write evaluation/scenarios.json (reproducible). Every scenario is labelled synthetic: these
are constructed test cases, not recordings of real impaired speech.

Extra fields beyond section 9 (D-046): `split` (tune|test), `synthetic`, `intent_keywords`,
`profile_terms`, `phrasebook`; `gesture_tokens` are {word, token, score}.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evaluation.make_fragments import make_fragments  # noqa: E402


def S(text, gap=1500):
    return {"source": "speech", "text": text, "gap_ms": gap}


def sc(
    id_,
    split,
    lang,
    cat,
    frags,
    target,
    intent,
    keys,
    *,
    partner=None,
    gestures=(),
    lip=None,
    profile=(),
    phrasebook=(),
    clar=False,
    allowed=(),
):
    return {
        "id": id_,
        "split": split,
        "language": lang,
        "category": cat,
        "synthetic": True,
        "fragments": frags,
        "speaker_audio_ref": None,
        "partner_line": partner,
        "gesture_tokens": list(gestures),
        "lip_ref": lip,
        "profile_terms": list(profile),
        "phrasebook": list(phrasebook),
        "target_sentence": target,
        "allowed_additions": list(allowed),
        "intent_label": intent,
        "intent_keywords": keys,
        "expected_clarification": clar,
    }


def G(word, token, score=0.9):
    return {"word": word, "token": token, "score": score}


SCENARIOS = [
    # --- clear speech
    sc(
        "clear-01",
        "test",
        "en",
        "clear_speech",
        [S("I need the bathroom")],
        "I need the bathroom.",
        "need_bathroom",
        ["bathroom"],
    ),
    sc(
        "clear-02",
        "tune",
        "en",
        "clear_speech",
        [S("please call my daughter")],
        "Please call my daughter.",
        "call_family",
        ["call", "daughter"],
    ),
    # --- context Q&A (partner line is the main clue)
    sc(
        "ctx-01",
        "test",
        "en",
        "context_qa",
        [S("wa", 1200), S("water", 2700), S("cold", 4200)],
        "I would like cold water, please.",
        "request_drink",
        ["water", "cold"],
        partner="Water or tea?",
    ),
    sc(
        "ctx-02",
        "test",
        "en",
        "context_qa",
        [S("tea"), S("sugar")],
        "I would like tea with sugar.",
        "request_drink",
        ["tea", "sugar"],
        partner="Do you want tea?",
    ),
    sc(
        "ctx-03",
        "tune",
        "en",
        "context_qa",
        [S("pain"), S("back")],
        "I have pain in my back.",
        "report_pain",
        ["pain", "back"],
        partner="Where does it hurt?",
    ),
    sc(
        "ctx-04",
        "test",
        "en",
        "context_qa",
        [S("blanket")],
        "I would like a blanket.",
        "request_item",
        ["blanket"],
        partner="Are you cold?",
    ),
    # --- personalisation (A+): profile terms and phrasebook
    sc(
        "pers-01",
        "test",
        "en",
        "context_qa",
        [S("mee"), S("meera"), S("call")],
        "Please call Meera.",
        "call_family",
        ["call", "meera"],
        profile=["Meera"],
        phrasebook=["Please call Meera."],
    ),
    sc(
        "pers-02",
        "tune",
        "en",
        "context_qa",
        [S("window")],
        "Please open the window.",
        "request_action",
        ["window"],
        phrasebook=["Please open the window."],
    ),
    # --- gesture plus ambiguous speech (B)
    sc(
        "gest-01",
        "test",
        "en",
        "gesture_ambiguous",
        [S("wa")],
        "Yes, I would like water.",
        "request_drink",
        ["yes"],
        partner="Do you want some water?",
        gestures=[G("yes", "Thumb_Up|Right")],
    ),
    sc(
        "gest-02",
        "test",
        "en",
        "gesture_ambiguous",
        [S("hmm"), S("the")],
        "No.",
        "decline",
        ["no"],
        partner="Shall I turn on the TV?",
        gestures=[G("no", "Thumb_Down|Left")],
    ),
    sc(
        "gest-03",
        "tune",
        "en",
        "gesture_ambiguous",
        [S("doc")],
        "Wait, I need the doctor.",
        "request_help",
        ["doctor"],
        profile=["doctor"],
        gestures=[G("wait", "Open_Palm|Right")],
    ),
    # --- lip-only (C): weak hint, clarification expected
    sc(
        "lip-01",
        "test",
        "en",
        "lip_only",
        [],
        "I want water.",
        "request_drink",
        ["water"],
        lip="water",
        clar=True,
    ),
    # --- Hindi / code-mixed
    sc(
        "hi-01",
        "test",
        "hi",
        "hindi",
        [S("पा"), S("पानी")],
        "मुझे पानी चाहिए।",
        "request_drink",
        ["पानी"],
        partner="पानी या चाय?",
    ),
    sc(
        "hi-02",
        "tune",
        "hi",
        "hindi",
        [S("दर्द"), S("सिर")],
        "मेरे सिर में दर्द है।",
        "report_pain",
        ["दर्द", "सिर"],
        partner="कहाँ दर्द है?",
    ),
    sc(
        "mix-01",
        "test",
        "mixed",
        "code_mixed",
        [S("paani"), S("thanda")],
        "Mujhe thanda paani chahiye.",
        "request_drink",
        ["paani", "thanda"],
        partner="Paani ya chai?",
    ),
    sc(
        "mix-02",
        "test",
        "mixed",
        "code_mixed",
        [S("phone"), S("charge")],
        "Please mera phone charge kar do.",
        "request_action",
        ["phone", "charge"],
        allowed=["kar", "do"],
    ),
    # --- negatives
    sc(
        "neg-01",
        "test",
        "en",
        "negative_conflict",
        [S("yes")],
        "",
        "unclear",
        [],
        partner="Do you want to sleep?",
        gestures=[G("no", "Thumb_Down|Right")],
        clar=True,
    ),
    sc("neg-02", "test", "en", "negative_no_cue", [S("um"), S("uh")], "", "unclear", [], clar=True),
    sc("neg-03", "tune", "en", "negative_noise", [S("ghh"), S("zz")], "", "unclear", [], clar=True),
]

# simulated atypical speech, generated deterministically
for i, (target, keys, partner, split) in enumerate(
    [
        ("I would like some juice please", ["juice"], "What would you like to drink?", "test"),
        ("I am feeling very tired", ["tired"], "How are you feeling?", "test"),
        ("Please turn off the light", ["light", "off"], None, "tune"),
        ("I want to go outside", ["outside"], "Where do you want to go?", "test"),
    ]
):
    SCENARIOS.append(
        sc(
            f"sim-{i + 1:02d}",
            split,
            "en",
            "simulated_atypical",
            make_fragments(target, seed=i + 1),
            target + ".",
            "synthetic_" + keys[0],
            keys,
            partner=partner,
        )
    )


def main() -> None:
    ids = [s["id"] for s in SCENARIOS]
    assert len(ids) == len(set(ids))
    out = ROOT / "evaluation" / "scenarios.json"
    out.write_text(json.dumps(SCENARIOS, ensure_ascii=False, indent=1), encoding="utf-8")
    test = sum(s["split"] == "test" for s in SCENARIOS)
    print(f"wrote {len(SCENARIOS)} scenarios ({test} test, {len(SCENARIOS) - test} tune) -> {out}")


if __name__ == "__main__":
    main()
