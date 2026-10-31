import pytest
from pydantic import ValidationError

from app.schemas import Candidate, Fragment, FusionResult, coverage_errors


def _frag(i: int, text: str, flags=()) -> Fragment:
    return Fragment(id=i, ts_ms=i * 1000, gap_ms=500, source="speech", text=text, flags=list(flags))


def _cand(covers) -> Candidate:
    return Candidate(text="I would like cold water, please.", covers=covers, added_words=[])


def test_needs_two_to_three_candidates_without_clarification():
    with pytest.raises(ValidationError, match="2-3 candidates"):
        FusionResult(
            intent="request",
            candidates=[_cand([1])],
            clarification_required=False,
            reasoning_summary="x",
        )
    ok = FusionResult(
        intent="request",
        candidates=[_cand([1]), _cand([1])],
        clarification_required=False,
        reasoning_summary="x",
    )
    assert len(ok.candidates) == 2


def test_more_than_three_candidates_rejected_even_with_clarification():
    with pytest.raises(ValidationError):
        FusionResult(
            intent="x",
            candidates=[_cand([1])] * 4,
            clarification_required=True,
            reasoning_summary="x",
        )


def test_clarification_result_may_have_no_candidates():
    r = FusionResult(
        intent="unknown",
        clarification_required=True,
        clarifying_question="Cold water?",
        reasoning_summary="fragments too thin",
    )
    assert r.candidates == []


def test_reasoning_summary_capped_at_200_chars():
    with pytest.raises(ValidationError):
        FusionResult(intent="x", clarification_required=True, reasoning_summary="a" * 201)


def test_coverage_requires_all_non_filler_fragments():
    frags = [
        _frag(1, "wa", ["stutter_prefix"]),
        _frag(2, "water"),
        _frag(3, "um", ["filler"]),
        _frag(4, "cold"),
    ]
    full = FusionResult(
        intent="request",
        candidates=[_cand([1, 2, 4]), _cand([1, 2, 4])],
        clarification_required=False,
        reasoning_summary="x",
    )
    assert coverage_errors(full, frags) == []

    partial = full.model_copy(update={"candidates": [_cand([2]), _cand([1, 2, 4])]})
    errs = coverage_errors(partial, frags)
    assert len(errs) == 1 and "[1, 4]" in errs[0]

    explained = partial.model_copy(update={"unexplained_fragment_ids": [1, 4]})
    assert coverage_errors(explained, frags) == []


def test_coverage_flags_unknown_ids():
    frags = [_frag(1, "water")]
    r = FusionResult(
        intent="x",
        candidates=[_cand([1, 9]), _cand([1])],
        unexplained_fragment_ids=[7],
        clarification_required=False,
        reasoning_summary="x",
    )
    errs = coverage_errors(r, frags)
    assert any("[7]" in e for e in errs) and any("[9]" in e for e in errs)
