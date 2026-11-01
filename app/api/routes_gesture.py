"""/gesture/lexicon and /gesture/calibrate."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/gesture")


@router.get("/lexicon")
def get_lexicon(request: Request) -> dict[str, str]:
    return request.app.state.gesture.lexicon.all()


@router.put("/lexicon")
def put_lexicon(body: dict[str, str], request: Request) -> dict[str, str]:
    return request.app.state.gesture.lexicon.replace(body)


class CalibrateRequest(BaseModel):
    word: str = Field(min_length=1, max_length=40)


@router.post("/calibrate")
def calibrate(body: CalibrateRequest, request: Request) -> dict:
    # Sync endpoint: FastAPI runs it in a worker thread, so waiting up to 10 s is fine.
    request.app.state.consent.require("camera")
    return request.app.state.gesture.calibrate(body.word)
