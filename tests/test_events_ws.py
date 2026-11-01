import asyncio
import threading

import pytest

from app.core.events import EventBus
from app.schemas import EVENT_TYPES
from tests.conftest import WS_URL


def test_spec_event_types_complete():
    assert set(EVENT_TYPES) == {
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
        "mouth.activity",  # added in M1 (D-011)
    }


def test_unknown_event_type_rejected():
    with pytest.raises(ValueError):
        EventBus().publish("camera.selfie", {})


def test_publish_from_foreign_thread_reaches_subscriber():
    async def run():
        bus = EventBus()
        sub = bus.subscribe()
        t = threading.Thread(target=bus.publish, args=("camera.status", {"ok": False}))
        t.start()
        t.join()
        ev = await asyncio.wait_for(sub.get(), 1)
        assert ev.type == "camera.status" and ev.data == {"ok": False}
        assert isinstance(ev.ts_ms, int)

    asyncio.run(run())


def test_slow_subscriber_drops_oldest():
    async def run():
        bus = EventBus(maxsize=2)
        sub = bus.subscribe()
        for i in range(5):
            bus.publish("error", {"i": i})
        await asyncio.sleep(0.01)  # let call_soon_threadsafe callbacks run
        got = [(await sub.get()).data["i"] for _ in range(2)]
        assert got == [3, 4] and sub.dropped == 3

    asyncio.run(run())


def test_ws_streams_events_as_json(client):
    bus = client.app.state.bus
    with client.websocket_connect(WS_URL) as ws:
        bus.publish("camera.status", {"ok": True, "source": "fake"})
        bus.publish("turn.state", {"state": "IDLE"})
        first, second = ws.receive_json(), ws.receive_json()
    assert first["type"] == "camera.status" and first["data"] == {"ok": True, "source": "fake"}
    assert set(first) == {"type", "ts_ms", "data"}
    assert second["type"] == "turn.state"
    assert second["ts_ms"] >= first["ts_ms"]


def test_ws_unsubscribes_on_disconnect(client):
    bus = client.app.state.bus
    with client.websocket_connect(WS_URL):
        assert bus.subscriber_count == 1
    for _ in range(50):
        if bus.subscriber_count == 0:
            break
        threading.Event().wait(0.02)
    assert bus.subscriber_count == 0
