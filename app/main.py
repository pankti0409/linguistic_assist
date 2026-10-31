"""FastAPI app factory. Run with `python -m app.main` (binds 127.0.0.1 only, R8)."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api import routes_misc, ws
from app.config import BIND_HOST, Settings, load_settings
from app.core.consent import ConsentRegistry
from app.core.errors import AppError
from app.core.events import EventBus
from app.core.health import HealthRegistry
from app.schemas import ErrorBody

log = logging.getLogger("ps16")


def _error(status: int, code: str, message: str, recoverable: bool) -> JSONResponse:
    body = ErrorBody(error_code=code, message=message, recoverable=recoverable)
    return JSONResponse(status_code=status, content=body.model_dump())


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="PS-16 communication assistant backend", version="0.0.0")
    app.state.settings = settings
    app.state.bus = EventBus()
    app.state.consent = ConsentRegistry()
    app.state.health = HealthRegistry(settings)

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
    app.include_router(ws.router)
    return app


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = load_settings()
    uvicorn.run(create_app(settings), host=BIND_HOST, port=settings.port)


if __name__ == "__main__":
    main()
