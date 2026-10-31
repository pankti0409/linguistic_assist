"""Turn, profile, phrasebook and metrics routes (section 7)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.schemas import Modality, Speaker

router = APIRouter()


class TurnStart(BaseModel):
    speaker: Speaker
    modalities: list[Modality] = ["speech"]
    language_pref: str = Field("en", pattern=r"^(en|hi|mixed|auto)$")


class TurnRef(BaseModel):
    turn_id: str | None = None


class TurnConfirm(BaseModel):
    turn_id: str
    choice_index: int | None = None
    edited_text: str | None = Field(None, max_length=300)


class TurnClarify(BaseModel):
    turn_id: str | None = None
    answer: str = Field(min_length=1, max_length=120)


def _tm(request: Request):
    return request.app.state.turns


@router.get("/turn")
def get_turn(request: Request) -> dict[str, Any]:
    t = _tm(request).current()
    return t.view() if t else {"state": "IDLE", "turn_id": None}


@router.post("/turn/start")
def turn_start(body: TurnStart, request: Request) -> dict[str, Any]:
    return _tm(request).start(body.speaker, list(body.modalities), body.language_pref).view()


@router.post("/turn/end")
def turn_end(request: Request, body: TurnRef | None = None) -> dict[str, Any]:
    # Sync: waits for the last transcription and, for PATIENT turns, the candidates.
    return _tm(request).end(body.turn_id if body else None).view()


@router.post("/turn/confirm")
def turn_confirm(body: TurnConfirm, request: Request) -> dict[str, Any]:
    return _tm(request).confirm(body.turn_id, body.choice_index, body.edited_text)


@router.post("/turn/reject")
def turn_reject(request: Request, body: TurnRef | None = None) -> dict[str, Any]:
    return _tm(request).reject(body.turn_id if body else None).view()


@router.post("/turn/clarify")
def turn_clarify(body: TurnClarify, request: Request) -> dict[str, Any]:
    # A button answer is a deliberate patient input, recorded like a gesture word (D-037).
    return _tm(request).clarify(body.answer, body.turn_id, source="gesture").view()


@router.get("/profile/terms")
def get_terms(request: Request) -> list[str]:
    return request.app.state.profile.get()


@router.put("/profile/terms")
def put_terms(body: list[str], request: Request) -> list[str]:
    return request.app.state.profile.put(body)


@router.get("/phrasebook")
def get_phrasebook(request: Request) -> list[dict]:
    return [e.model_dump() for e in request.app.state.phrasebook.entries()]


@router.delete("/phrasebook")
def delete_phrasebook(request: Request) -> dict[str, int]:
    return {"deleted": request.app.state.phrasebook.wipe()}  # always allowed


@router.get("/metrics")
def metrics(request: Request) -> dict[str, Any]:
    return request.app.state.metrics.snapshot()


@router.get("/context")
def get_context(request: Request) -> list[dict]:
    """Recent labelled dialogue (last CONTEXT_TURNS), oldest first."""
    return [t.model_dump() for t in request.app.state.conversation.recent()]


@router.get("/config")
def get_config(request: Request) -> dict[str, Any]:
    """Non-secret runtime settings a frontend needs. Never keys or IDs."""
    s = request.app.state.settings
    return {
        "fragment_silence_s": s.fragment_silence_s,
        "fragment_max_s": s.fragment_max_s,
        "turn_max_s": s.turn_max_s,
        "max_clarify_rounds": s.max_clarify_rounds,
        "confirm_ttl_s": s.confirm_ttl_s,
        "context_turns": s.context_turns,
        "calibrate_timeout_s": s.calibrate_timeout_s,
        "lip_enabled": s.lip_enabled,
        "debug_preview": s.debug_preview,
        "simulate": s.simulate,
        "avatar_mode": s.tavus_pipeline_mode,
        "avatar_audio_echo": s.avatar_audio_echo,
        "token_required": bool(s.access_token),
        "languages": ["en", "hi", "mixed", "auto"],
    }
