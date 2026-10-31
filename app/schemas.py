"""Pydantic v2 schemas (CLAUDE.md section 6) plus API request/response models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

Speaker = Literal["PATIENT", "PARTNER"]
Modality = Literal["speech", "lip", "gesture", "context"]
FragmentFlag = Literal["low_confidence", "repeat", "stutter_prefix", "filler", "answer_to_question"]
ConsentPurpose = Literal["camera", "microphone", "voice_clone", "avatar", "personalization"]
CONSENT_PURPOSES: tuple[str, ...] = ConsentPurpose.__args__  # type: ignore[attr-defined]

EventType = Literal[
    "camera.status",
    "gesture.token",
    "gesture.word",
    "lip.result",
    "speech.partial",
    "speech.final",
    "fragment.added",
    "draft.updated",
    "fusion.question",
    "turn.state",
    "fusion.candidates",
    "confirm.issued",
    "tts.started",
    "avatar.speaking",
    "avatar.guardrail",
    "output.fallback",
    "error",
    # not in the spec list, but M1 acceptance needs it (D-011)
    "mouth.activity",
]
EVENT_TYPES: tuple[str, ...] = EventType.__args__  # type: ignore[attr-defined]


# --- evidence -------------------------------------------------------------


class DialogueTurn(BaseModel):
    speaker: Speaker
    text: str
    ts_ms: int


class GestureWord(BaseModel):
    word: str
    token: str
    score: float
    ts_ms: int


class SpeechEvidence(BaseModel):
    text: str
    is_final: bool
    language: str | None = None


class LipEvidence(BaseModel):
    status: Literal["ok", "insufficient_visual_evidence", "unavailable"]
    text: str | None = None
    score: float | None = None
    frames: int = 0


class Fragment(BaseModel):
    id: int
    ts_ms: int
    gap_ms: int  # silence before this fragment
    source: Literal["speech", "gesture", "lip"]
    text: str
    is_final: bool = True
    confidence: float | None = None  # only if the provider returns one
    flags: list[FragmentFlag] = []


class PhraseEntry(BaseModel):
    text: str
    uses: int
    last_used_ms: int


class EvidencePacket(BaseModel):
    turn_id: str
    speaker: Speaker
    ts_ms: int
    language_pref: str = "en"
    fragments: list[Fragment]  # raw order kept
    cleaned_fragments: list[str]  # deterministic cleanup only
    mouth_activity: bool = False
    context: list[DialogueTurn] = []  # last CONTEXT_TURNS turns
    profile_terms: list[str] = []
    phrasebook_hits: list[PhraseEntry] = []


# --- fusion output ----------------------------------------------------------


class Candidate(BaseModel):
    text: str
    covers: list[int]  # fragment ids this sentence accounts for
    added_words: list[str]  # words in no fragment; shown to the patient


class FusionResult(BaseModel):
    intent: str
    candidates: list[Candidate] = Field(default_factory=list, max_length=3)
    unexplained_fragment_ids: list[int] = []
    clarifying_question: str | None = None  # yes/no, answerable by Thumb_Up / Thumb_Down
    clarification_required: bool
    reasoning_summary: str = Field(max_length=200)

    @model_validator(mode="after")
    def _candidate_count(self) -> FusionResult:
        if not self.clarification_required and not 2 <= len(self.candidates) <= 3:
            raise ValueError(
                "2-3 candidates are required unless clarification_required is true "
                f"(got {len(self.candidates)})"
            )
        return self


def coverage_errors(result: FusionResult, fragments: list[Fragment]) -> list[str]:
    """Second FusionResult validator, which needs the fragments it was built from.

    Each candidate must cover every non-filler fragment id, or the missing ids must be
    listed in `unexplained_fragment_ids`. Unknown ids are errors too.
    """
    known = {f.id for f in fragments}
    content = {f.id for f in fragments if "filler" not in f.flags}
    unexplained = set(result.unexplained_fragment_ids)
    errors: list[str] = []
    if bad := unexplained - known:
        errors.append(f"unexplained_fragment_ids has unknown ids {sorted(bad)}")
    for i, c in enumerate(result.candidates):
        if bad := set(c.covers) - known:
            errors.append(f"candidate {i} covers unknown ids {sorted(bad)}")
        if missing := content - set(c.covers) - unexplained:
            errors.append(f"candidate {i} leaves fragments {sorted(missing)} unaccounted for")
    return errors


# --- API models -------------------------------------------------------------


class ErrorBody(BaseModel):
    error_code: str
    message: str
    recoverable: bool


class Event(BaseModel):
    type: EventType
    ts_ms: int
    data: dict[str, Any] = {}


class ConsentRequest(BaseModel):
    purpose: ConsentPurpose


class ConsentRecord(BaseModel):
    purpose: ConsentPurpose
    granted: bool
    ts_ms: int | None = None


ServiceState = Literal["ok", "degraded", "unavailable"]


class ServiceHealth(BaseModel):
    status: ServiceState
    detail: str = ""
    configured: bool | None = None  # credentials/assets present; never the values themselves
    backend: Literal["real", "fake", "none"] = "none"


class HealthResponse(BaseModel):
    simulate: bool
    services: dict[str, ServiceHealth]
    avatar_mode: str
    limits: dict[str, list[str]]
