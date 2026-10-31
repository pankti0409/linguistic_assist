"""WS /ws: streams every EventBus event as JSON {type, ts_ms, data}."""

from __future__ import annotations

import asyncio
import contextlib
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def origin_allowed(origin: str | None, extra: tuple[str, ...]) -> bool:
    """Non-browser clients send no Origin. Browsers must come from loopback or the allowlist.

    Without this, any web page the user visits could read the event stream (patient text).
    """
    if origin is None:
        return True
    if origin in extra:
        return True
    return urlsplit(origin).hostname in LOOPBACK_HOSTS


async def _until_disconnect(ws: WebSocket) -> None:
    # Clients are listeners; anything they send is ignored.
    with contextlib.suppress(WebSocketDisconnect):
        while True:
            await ws.receive_text()


@router.websocket("/ws")
async def events(ws: WebSocket) -> None:
    if not origin_allowed(ws.headers.get("origin"), ws.app.state.settings.allowed_origins):
        await ws.close(code=1008)  # before accept, so the handshake is refused with HTTP 403
        return
    bus = ws.app.state.bus
    sub = bus.subscribe()  # before accept, so no event is missed after the handshake
    await ws.accept()
    closed = asyncio.create_task(_until_disconnect(ws))
    try:
        while True:
            nxt = asyncio.create_task(sub.get())
            done, _ = await asyncio.wait({nxt, closed}, return_when=asyncio.FIRST_COMPLETED)
            if closed in done:
                nxt.cancel()
                break
            await ws.send_json(nxt.result().model_dump())
    except WebSocketDisconnect:
        pass
    finally:
        closed.cancel()
        bus.unsubscribe(sub)
