"""FastAPI app factory. Run with `python -m app.main` (binds 127.0.0.1 only, R8)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.adapters.interfaces import FrameSource
from app.api import routes_gesture, routes_misc, routes_turn, ws
from app.config import BIND_HOST, ROOT, Settings, load_settings
from app.core.confirmation import ConfirmationRegistry
from app.core.consent import ConsentRegistry
from app.core.conversation import Conversation
from app.core.errors import AppError
from app.core.events import EventBus
from app.core.health import HealthRegistry
from app.core.phrasebook import Phrasebook, ProfileTerms
from app.core.timing import Metrics
from app.core.turn_machine import TurnMachine
from app.core.voice import VoiceSelector
from app.schemas import ErrorBody
from app.services.camera import CameraHub
from app.services.face import DetectorFactory, FaceService
from app.services.fusion import FusionService
from app.services.gesture import GestureService, RecognizerFactory
from app.services.lip import LipService
from app.services.scribe import ScribeService
from app.services.tts import SpeechOutput

log = logging.getLogger("ps16")


def _error(status: int, code: str, message: str, recoverable: bool) -> JSONResponse:
    body = ErrorBody(error_code=code, message=message, recoverable=recoverable)
    return JSONResponse(status_code=status, content=body.model_dump())


@dataclass
class Overrides:
    """Swap real devices for fakes (tests, SIMULATE). None means the real implementation."""

    frame_source_factory: Callable[[], FrameSource] | None = None
    face_detector_factory: DetectorFactory | None = None
    gesture_recognizer_factory: RecognizerFactory | None = None
    lexicon_path: Path | None = None
    lip_reader_factory: Callable[[], object] | None = None
    stt: object | None = None  # SpeechToText
    mic_factory: Callable[[], object] | None = None
    llm: object | None = None  # LLMClient
    tts: object | None = None  # TextToSpeech
    data_dir: Path | None = None  # phrasebook + profile terms (default: ./data)


def _wire_turns(app: FastAPI, overrides: Overrides) -> None:
    s, bus, health, consent = (
        app.state.settings,
        app.state.bus,
        app.state.health,
        app.state.consent,
    )
    data = overrides.data_dir or ROOT / "data"
    app.state.conversation = Conversation(s.context_turns)
    app.state.phrasebook = Phrasebook(data / "phrasebook.json", consent)
    app.state.profile = ProfileTerms(data / "profile_terms.json", consent)
    app.state.confirmations = ConfirmationRegistry(s.confirm_ttl_s)
    app.state.metrics = Metrics()
    app.state.scribe = ScribeService(s, bus, health, consent, overrides.stt, overrides.mic_factory)
    app.state.fusion = FusionService(s, health, overrides.llm)
    app.state.speech = SpeechOutput(
        s, bus, health, app.state.confirmations, app.state.voice, overrides.tts
    )
    app.state.turns = TurnMachine(
        s,
        bus,
        consent,
        app.state.conversation,
        app.state.phrasebook,
        app.state.profile,
        app.state.fusion,
        app.state.scribe,
        app.state.speech,
        app.state.confirmations,
        app.state.metrics,
        lip=app.state.lip,
        gesture=app.state.gesture,
        face=app.state.face,
    )


def _wire_camera(app: FastAPI, overrides: Overrides) -> None:
    s, bus, health, consent = (
        app.state.settings,
        app.state.bus,
        app.state.health,
        app.state.consent,
    )
    hub = CameraHub(s, bus, health, consent, source_factory=overrides.frame_source_factory)
    face = FaceService(s, hub, bus, health, consent, overrides.face_detector_factory)
    gesture = GestureService(
        s, hub, bus, health, consent, overrides.gesture_recognizer_factory, overrides.lexicon_path
    )
    lip = LipService(s, hub, face, bus, health, consent, overrides.lip_reader_factory)
    app.state.camera, app.state.face, app.state.gesture, app.state.lip = hub, face, gesture, lip
    # Loading Auto-AVSR (~1 GB) takes seconds, so do it off the request path.
    threading.Thread(target=lip.load, name="lip-load", daemon=True).start()

    # Camera processing runs exactly while `camera` consent is held (R3, D-013).
    def on_grant(purpose: str) -> None:
        if purpose == "camera":
            hub.start()
            face.start()
            gesture.start()

    def on_revoke(purpose: str) -> None:
        if purpose == "camera":
            gesture.stop()
            face.stop()
            hub.stop()

    consent.on_grant(on_grant)
    consent.on_revoke(on_revoke)


def create_app(settings: Settings | None = None, overrides: Overrides | None = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        app.state.turns.shutdown()
        app.state.scribe.shutdown()
        app.state.lip.shutdown()
        app.state.gesture.stop()
        app.state.face.stop()
        app.state.camera.stop()

    app = FastAPI(title="PS-16 communication assistant backend", version="0.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.bus = EventBus()
    app.state.consent = ConsentRegistry()
    app.state.health = HealthRegistry(settings)
    app.state.voice = VoiceSelector(settings)
    overrides = overrides or Overrides()
    _wire_camera(app, overrides)
    _wire_turns(app, overrides)

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return _error(exc.status_code, exc.error_code, exc.message, exc.recoverable)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        msg = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        return _error(422, "invalid_request", msg, True)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error(exc.status_code, f"http_{exc.status_code}", str(exc.detail), True)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return _error(500, "internal_error", type(exc).__name__, False)

    # DNS-rebinding guard: a hostile page that rebinds its own name to 127.0.0.1 arrives
    # with its own Host header and is refused (D-009).
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    app.include_router(routes_misc.router)
    app.include_router(routes_gesture.router)
    app.include_router(routes_turn.router)
    app.include_router(ws.router)
    return app


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = load_settings()
    uvicorn.run(create_app(settings), host=BIND_HOST, port=settings.port)


if __name__ == "__main__":
    main()
