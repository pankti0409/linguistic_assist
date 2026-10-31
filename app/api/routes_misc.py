"""/health and /consent."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.schemas import ConsentPurpose, ConsentRecord, ConsentRequest, HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    return request.app.state.health.snapshot()


@router.post("/consent", response_model=ConsentRecord)
def grant_consent(body: ConsentRequest, request: Request) -> ConsentRecord:
    return request.app.state.consent.grant(body.purpose)


@router.get("/consent", response_model=list[ConsentRecord])
def list_consent(request: Request) -> list[ConsentRecord]:
    return request.app.state.consent.all()


@router.delete("/consent/{purpose}", response_model=ConsentRecord)
def revoke_consent(purpose: ConsentPurpose, request: Request) -> ConsentRecord:
    return request.app.state.consent.revoke(purpose)
