"""/avatar/session and the Tavus guardrail webhook."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.services.avatar import DISCLOSURE

router = APIRouter(prefix="/avatar")


@router.post("/session")
def create_session(request: Request) -> dict[str, Any]:
    """Create the Tavus conversation; the backend joins it as the only echo sender."""
    return request.app.state.avatar.create_session(request.app.state.settings.tavus_callback_url)


@router.get("/session")
def get_session(request: Request) -> dict[str, Any]:
    return request.app.state.avatar.public_session()


@router.delete("/session")
def end_session(request: Request) -> dict[str, Any]:
    request.app.state.avatar.end_session()
    return {"ended": True}


@router.post("/guardrail")
async def guardrail_webhook(request: Request) -> dict[str, bool]:
    """Tavus guardrail callback. Forwarded to WS as derived fields only, never raw speech."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    keep = {
        k: body.get(k)
        for k in ("conversation_id", "event_type", "guardrail_name", "guardrail_id", "timestamp")
        if k in body
    }
    request.app.state.bus.publish("avatar.guardrail", {**keep, **DISCLOSURE})
    return {"received": True}
