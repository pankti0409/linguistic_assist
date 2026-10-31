"""EventBus: thread-safe fan-out from any module to every WebSocket subscriber.

Camera and vision threads publish from outside the event loop, so delivery goes
through `loop.call_soon_threadsafe`. Each subscriber has a bounded queue; when a
slow client falls behind, the oldest event is dropped and counted.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from app.core.timing import now_ms
from app.schemas import EVENT_TYPES, Event

log = logging.getLogger(__name__)


class Subscription:
    def __init__(self, loop: asyncio.AbstractEventLoop, maxsize: int) -> None:
        self.loop = loop
        self.queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self.dropped = 0

    def _put(self, event: Event) -> None:  # runs on self.loop
        if self.queue.full():
            self.queue.get_nowait()
            self.dropped += 1
        self.queue.put_nowait(event)

    async def get(self) -> Event:
        return await self.queue.get()


class EventBus:
    def __init__(self, maxsize: int = 256) -> None:
        self._maxsize = maxsize
        self._subs: list[Subscription] = []
        self._lock = threading.Lock()
        self.published = 0

    def subscribe(self) -> Subscription:
        """Call from inside the event loop that will consume the events."""
        sub = Subscription(asyncio.get_running_loop(), self._maxsize)
        with self._lock:
            self._subs.append(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        with self._lock:
            if sub in self._subs:
                self._subs.remove(sub)

    def publish(self, type_: str, data: dict[str, Any] | None = None) -> Event:
        """Publish from any thread. Unknown event types are a programming error."""
        if type_ not in EVENT_TYPES:
            raise ValueError(f"unknown event type '{type_}'")
        event = Event(type=type_, ts_ms=now_ms(), data=data or {})  # type: ignore[arg-type]
        with self._lock:
            subs = list(self._subs)
            self.published += 1
        for sub in subs:
            try:
                sub.loop.call_soon_threadsafe(sub._put, event)
            except RuntimeError:  # loop closed: client is gone
                self.unsubscribe(sub)
        return event

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)
