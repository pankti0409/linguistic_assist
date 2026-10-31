"""Build SYNTHETIC fragment sequences from full sentences (section 9).

Simulates broken speech by dropping function words, adding stutter prefixes, repeats,
fillers and long pauses. It is seeded, so output is reproducible. Everything it makes is
labelled synthetic. Claims about real impaired speech need consented volunteer recordings.

Usage: python evaluation/make_fragments.py "I would like cold water please" --seed 3
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evaluation.metrics import words  # noqa: E402


def load_fw() -> set[str]:
    fw: set[str] = set()
    for code in ("en", "hi"):
        for line in (
            (ROOT / "prompts" / f"function_words_{code}.txt")
            .read_text(encoding="utf-8")
            .splitlines()
        ):
            line = line.strip()
            if line and not line.startswith("#"):
                fw.update(words(line))
    return fw


def make_fragments(
    sentence: str,
    seed: int = 0,
    p_drop_function: float = 0.8,
    p_stutter: float = 0.5,
    p_repeat: float = 0.25,
    p_filler: float = 0.25,
    function_words: set[str] | None = None,
) -> list[dict]:
    rng = random.Random(seed)
    fw = function_words if function_words is not None else load_fw()
    out: list[dict] = []

    def add(text: str) -> None:
        out.append({"source": "speech", "text": text, "gap_ms": rng.randint(800, 4500)})

    for w in words(sentence):
        if w in fw and rng.random() < p_drop_function:
            continue
        if rng.random() < p_filler:
            add(rng.choice(["um", "uh", "hmm"]))
        if len(w) > 3 and rng.random() < p_stutter:
            add(w[: rng.randint(1, 2)])
        add(w)
        if rng.random() < p_repeat:
            add(w)
    if not out:  # never return an empty utterance
        add(words(sentence)[0])
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 0
    frags = make_fragments(
        " ".join(args[:1]) if args else "I would like cold water please", seed=seed
    )
    print(json.dumps({"synthetic": True, "fragments": frags}, ensure_ascii=False, indent=1))
