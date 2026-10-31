"""/health, /consent, /voice and the optional camera debug preview."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.errors import ServiceUnavailableError
from app.core.voice import VoiceGender, VoiceState
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


class VoiceRequest(BaseModel):
    gender: VoiceGender


@router.get("/voice", response_model=VoiceState)
def get_voice(request: Request) -> VoiceState:
    return request.app.state.voice.state()


@router.put("/voice", response_model=VoiceState)
def set_voice(body: VoiceRequest, request: Request) -> VoiceState:
    return request.app.state.voice.select(body.gender)


PREVIEW_FPS = 10


@router.get("/camera/preview.mjpg")
async def camera_preview(request: Request) -> StreamingResponse:
    """Debug-only MJPEG stream, encoded in memory (R8). Off unless DEBUG_PREVIEW=1."""
    app = request.app
    if not app.state.settings.debug_preview:
        raise ServiceUnavailableError("camera preview is disabled; set DEBUG_PREVIEW=1")
    app.state.consent.require("camera")
    hub = app.state.camera
    import cv2

    async def frames() -> AsyncIterator[bytes]:
        last = -1
        while not await request.is_disconnected() and app.state.consent.has("camera"):
            f = hub.latest()
            if f is not None and f.seq != last:
                last = f.seq
                ok, jpg = cv2.imencode(".jpg", f.image, [cv2.IMWRITE_JPEG_QUALITY, 70])
                if ok:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg.tobytes() + b"\r\n"
            await asyncio.sleep(1 / PREVIEW_FPS)

    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")
