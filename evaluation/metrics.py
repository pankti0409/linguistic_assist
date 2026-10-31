"""Evaluation metrics (section 9). Pure Python, no extra dependency, measured values only.

Acceptance is decided by deterministic rules against labelled targets, never by an LLM
judge (D-045):
  * a candidate is *accepted* when its content words (tokens minus the function-word
    allowlist) equal the target sentence's content words, so function-word differences
    ("I would like ..." vs "I want ...") do not count against it, but meaning words do;
  * intent is correct when the first candidate contains every `intent_keywords` token, or
    when clarification was expected and requested.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence

_WORD = re.compile(r"[0-9A-Za-zÀ-ɏऀ-ॣ०-ॿ]+(?:'[A-Za-z]+)?")


def words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text or "")]


# --- WER -------------------------------------------------------------------------


def edit_counts(ref: Sequence[str], hyp: Sequence[str]) -> tuple[int, int, int]:
    """(substitutions, deletions, insertions) of a minimum-edit alignment."""
    n, m = len(ref), len(hyp)
    # dp[i][j] = (cost, S, D, I)
    dp = [[(0, 0, 0, 0)] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = (i, 0, i, 0)
    for j in range(1, m + 1):
        dp[0][j] = (j, 0, 0, j)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
                continue
            c, s, d, ins = dp[i - 1][j - 1]
            sub = (c + 1, s + 1, d, ins)
            c, s, d, ins = dp[i - 1][j]
            dele = (c + 1, s, d + 1, ins)
            c, s, d, ins = dp[i][j - 1]
            inse = (c + 1, s, d, ins + 1)
            dp[i][j] = min(sub, dele, inse)
    _, s, d, ins = dp[n][m]
    return s, d, ins


def wer(ref: str, hyp: str) -> float:
    """WER % = (S + D + I) / reference words x 100 on raw text (lower-cased, unpunctuated)."""
    r, h = words(ref), words(hyp)
    if not r:
        raise ValueError("reference has no words")
    s, d, i = edit_counts(r, h)
    return (s + d + i) / len(r) * 100


def corpus_wer(pairs: Iterable[tuple[str, str]]) -> float | None:
    tot_err = tot_ref = 0
    for ref, hyp in pairs:
        r = words(ref)
        s, d, i = edit_counts(r, words(hyp))
        tot_err += s + d + i
        tot_ref += len(r)
    return None if tot_ref == 0 else tot_err / tot_ref * 100


# --- acceptance / intent -------------------------------------------------------------


def content_words(text: str, function_words: set[str]) -> set[str]:
    return {w for w in words(text) if w not in function_words}


def accepted(candidate: str, target: str, function_words: set[str]) -> bool:
    return content_words(candidate, function_words) == content_words(target, function_words)


def intent_correct(
    first_candidate: str | None,
    clarified: bool,
    expected_clarification: bool,
    intent_keywords: Sequence[str],
) -> bool:
    if expected_clarification:
        return clarified
    if clarified or not first_candidate:
        return False
    got = set(words(first_candidate))
    return all(k.lower() in got for k in intent_keywords)


def unsupported_words(candidate: str, evidence_text: str, function_words: set[str]) -> list[str]:
    """Independent re-check of R10 on the final output (must be empty after the validator)."""
    ev = set(words(evidence_text))
    return [w for w in words(candidate) if w not in ev and w not in function_words]


# --- latency / summary -------------------------------------------------------------


def percentile(values: Sequence[float], p: float) -> float | None:
    """Nearest-rank percentile; None for no data (never a made-up zero)."""
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, math.ceil(p / 100 * len(s)) - 1))
    return float(s[k])


def rate(numer: int, denom: int) -> float | None:
    return None if denom == 0 else numer / denom


def mean(values: Sequence[float]) -> float | None:
    return None if not values else sum(values) / len(values)
