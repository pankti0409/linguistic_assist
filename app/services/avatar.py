"""AvatarService (section 8.9): Tavus conversation + echo transport, tiers 1-2 of the ladder.

Field names come from https://docs.tavus.io/openapi.yaml (fetched 2026-10-31). Tavus has
renamed personas to PALs and replicas to faces (D-014):
  POST /v2/conversations {face_id, pal_id, conversation_name, dynamic_greeting, properties}
  POST /v2/conversations/{id}/end
  app message conversation.echo {modality text|audio, text | audio(base64 PCM), sample_rate,
                                 inference_id, done}
  app message conversation.interrupt
  events conversation.replica.started_speaking / stopped_speaking

The *backend* joins the Daily room with daily-python, camera and mic off, and is the only
sender of echo messages, so a frontend cannot bypass the confirmation gate. The patient's
frontend gets `conversation_url` to watch, receive-only (R4).
"""

from __future__ import annotations

import base64
import logging
import threading
import uuid
from collections.abc import Callable
from typing import Any

import httpx

from app.config import Settings
from app.core.consent import ConsentRegistry
from app.core.errors import AppError, ServiceUnavailableError
from app.core.events import EventBus
from app.core.health import HealthRegistry
from app.core.timing import TurnTimer

log = logging.getLogger(__name__)

TAVUS_BASE = "https://tavusapi.com"
DISCLOSURE = {"synthetic": True, "disclosure": "AI avatar"}
ECHO_SAMPLE_RATE = 16_000  # openapi: sample_rate defaults to 16000 for audio echo
ECHO_FORMAT = "pcm_16000"  # ElevenLabs raw 16 kHz int16 mono
START_TIMEOUT_S = 6.0
STARTED = "conversation.replica.started_speaking"
STOPPED = "conversation.replica.stopped_speaking"


class AvatarSessionError(AppError):
    status_code = 502
    error_code = "avatar_session_failed"
    recoverable = True


# --- REST ----------------------------------------------------------------------


class TavusAPI:
    """Minimal Tavus REST client (header `x-api-key`)."""

    def __init__(self, api_key: str, base: str = TAVUS_BASE, timeout: float = 20.0) -> None:
        self._http = httpx.Client(base_url=base, headers={"x-api-key": api_key}, timeout=timeout)

    def create_conversation(self, body: dict[str, Any]) -> dict[str, Any]:
        r = self._http.post("/v2/conversations", json=body)
        r.raise_for_status()
        return r.json()

    def end_conversation(self, conversation_id: str) -> None:
        self._http.post(f"/v2/conversations/{conversation_id}/end").raise_for_status()


def conversation_body(settings: Settings, callback_url: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "face_id": settings.tavus_replica_id,
        "pal_id": settings.tavus_persona_id,
        "conversation_name": "PS-16 relay",
        # The PAL "Sahayak" has dynamic_greeting=true. Overridden here per conversation so the
        # avatar never speaks unconfirmed words; the PAL itself stays unmodified (D-042).
        "dynamic_greeting": False,
        "properties": {
            "max_call_duration": 1800,
            "participant_left_timeout": 60,
            "participant_absent_timeout": 300,
            "enable_closed_captions": True,
        },
    }
    if callback_url:
        body["callback_url"] = callback_url
    return body


# --- Daily transport ---------------------------------------------------------------

MessageCallback = Callable[[dict], None]


class DailyTransport:
    """Joins the conversation room as a silent, camera-less participant (daily-python 0.36)."""

    _initialised = False

    def __init__(self) -> None:
        from daily import CallClient, Daily, EventHandler

        if not DailyTransport._initialised:
            Daily.init()
            DailyTransport._initialised = True
        outer = self

        class Handler(EventHandler):
            def on_app_message(self, message, sender):  # noqa: N805
                if outer._on_message and isinstance(message, dict):
                    outer._on_message(message)

        self._handler = Handler()
        self._client = CallClient(event_handler=self._handler)
        self._on_message: MessageCallback | None = None

    def join(self, conversation_url: str, on_message: MessageCallback, timeout: float = 15.0):
        self._on_message = on_message
        done = threading.Event()
        err: list[Any] = []

        def completion(data, error):
            if error:
                err.append(error)
            done.set()

        self._client.set_user_name("ps16-relay")
        self._client.join(
            conversation_url,
            client_settings={"inputs": {"camera": False, "microphone": False}},
            completion=completion,
        )
        if not done.wait(timeout) or err:
            raise ConnectionError(f"daily join failed: {err[0] if err else 'timeout'}")

    def send(self, message: dict) -> None:
        self._client.send_app_message(message, None)

    def leave(self) -> None:
        done = threading.Event()
        self._client.leave(completion=lambda error: done.set())
        done.wait(5)


# --- service -------------------------------------------------------------------------


class AvatarService:
    def __init__(
        self,
        settings: Settings,
        bus: EventBus,
        health: HealthRegistry,
        consent: ConsentRegistry,
        api=None,
        transport_factory: Callable[[], object] | None = None,
        start_timeout_s: float = START_TIMEOUT_S,
        audio_echo: bool = True,
        chunk_bytes: int = 16_000,
    ) -> None:
        self._s = settings
        self._bus = bus
        self._health = health
        self._consent = consent
        self._api = api
        self._backend = "fake" if api is not None else "real"
        self._transport_factory = transport_factory or DailyTransport
        self.start_timeout_s = start_timeout_s
        self.audio_echo = audio_echo
        self.chunk_bytes = chunk_bytes  # raw PCM bytes per echo frame; unverified limit (D-043)
        self._lock = threading.Lock()
        self.session: dict[str, Any] | None = None
        self._transport = None
        self._started = threading.Event()
        self._speaking = False
        configured = bool(
            settings.tavus_api_key and settings.tavus_replica_id and settings.tavus_persona_id
        )
        if api is not None:
            health.set("avatar", "degraded", "fake Tavus; no session", backend="fake")
        elif configured:
            health.set("avatar", "degraded", "configured; no session (POST /avatar/session)")
        else:
            health.set("avatar", "unavailable", "Tavus key / face / PAL not set; local audio only")

    # --- session ----------------------------------------------------------

    def _rest(self):
        if self._api is None:
            if not self._s.tavus_api_key:
                raise ServiceUnavailableError("TAVUS_API_KEY not set")
            self._api = TavusAPI(self._s.tavus_api_key)
        return self._api

    def create_session(self, callback_url: str | None = None) -> dict[str, Any]:
        self._consent.require("avatar")  # R3
        with self._lock:
            if self.session is not None:
                return self.public_session()
        try:
            conv = self._rest().create_conversation(conversation_body(self._s, callback_url))
        except Exception as exc:
            self._health.set(
                "avatar",
                "unavailable",
                f"create failed: {type(exc).__name__}",
                backend=self._backend,
            )
            raise AvatarSessionError(
                f"Tavus conversation not created: {type(exc).__name__}"
            ) from exc
        transport = self._transport_factory()
        try:
            transport.join(conv["conversation_url"], self._on_message)
        except Exception as exc:
            try:
                self._rest().end_conversation(conv["conversation_id"])
            except Exception:
                log.exception("could not end conversation after failed join")
            self._health.set(
                "avatar", "unavailable", f"echo transport failed: {exc}", backend=self._backend
            )
            raise AvatarSessionError(f"backend could not join the room: {exc}") from exc
        with self._lock:
            self.session, self._transport = conv, transport
        self._health.set(
            "avatar", "ok", f"session {conv['conversation_id']}", backend=self._backend
        )
        return self.public_session()

    def public_session(self) -> dict[str, Any]:
        s = self.session or {}
        return {
            "conversation_id": s.get("conversation_id"),
            "conversation_url": s.get("conversation_url"),
            # the patient's frontend joins receive-only (R4)
            "join_settings": {"camera": False, "microphone": False},
            **DISCLOSURE,
        }

    def end_session(self) -> None:
        with self._lock:
            conv, transport = self.session, self._transport
            self.session, self._transport = None, None
        if transport is not None:
            try:
                transport.leave()
            except Exception:
                log.exception("leave failed")
        if conv is not None:
            try:
                self._rest().end_conversation(conv["conversation_id"])
            except Exception:
                log.exception("end conversation failed")
        self._health.set("avatar", "degraded", "no session", backend=self._backend)

    # --- inbound events --------------------------------------------------------

    def _on_message(self, msg: dict) -> None:
        et = msg.get("event_type")
        if et == STARTED:
            self._speaking = True
            self._started.set()
            self._bus.publish("avatar.speaking", {"speaking": True, **DISCLOSURE})
        elif et == STOPPED:
            self._speaking = False
            props = msg.get("properties") or {}
            self._bus.publish(
                "avatar.speaking",
                {
                    "speaking": False,
                    "duration": props.get("duration"),
                    "interrupted": props.get("interrupted"),
                    **DISCLOSURE,
                },
            )
        elif et and "guardrail" in et:
            self._bus.publish("avatar.guardrail", {"event_type": et, **DISCLOSURE})

    # --- outbound -----------------------------------------------------------------

    def _send(self, properties: dict | None, event_type: str) -> None:
        msg: dict[str, Any] = {
            "message_type": "conversation",
            "event_type": event_type,
            "conversation_id": self.session["conversation_id"],  # type: ignore[index]
            **DISCLOSURE,  # R9; extra keys alongside the schema's (D-043)
        }
        if properties is not None:
            msg["properties"] = properties
        self._transport.send(msg)  # type: ignore[union-attr]

    def interrupt(self) -> None:
        if self.session is not None and self._transport is not None:
            try:
                self._send(None, "conversation.interrupt")
            except Exception:
                log.exception("interrupt failed")

    def _await_start(self) -> bool:
        return self._started.wait(self.start_timeout_s)

    def try_speak(
        self, text: str, voice_id: str, meta: dict, timer: TurnTimer | None, synth
    ) -> tuple[str | None, list[str]]:
        """Tier 1 (audio echo) then tier 2 (text echo). Returns (tier, failure reasons).

        A tier counts as spoken only when Tavus reports started_speaking. Before moving to the
        next tier the avatar is interrupted, so two tiers never speak the same message.
        """
        if self.session is None or self._transport is None:
            return None, ["no avatar session"]
        reasons: list[str] = []
        if self.audio_echo:
            try:
                pcm = synth(text, voice_id, ECHO_FORMAT)
                if timer:
                    timer.mark("tts_done")
                self._started.clear()
                iid = uuid.uuid4().hex
                chunks = [
                    pcm[i : i + self.chunk_bytes] for i in range(0, len(pcm), self.chunk_bytes)
                ]
                for i, chunk in enumerate(chunks):
                    self._send(
                        {
                            "modality": "audio",
                            "audio": base64.b64encode(chunk).decode("ascii"),
                            "sample_rate": ECHO_SAMPLE_RATE,
                            "inference_id": iid,
                            "done": i == len(chunks) - 1,
                        },
                        "conversation.echo",
                    )
                if self._await_start():
                    return self._spoken("avatar_audio", text, meta, timer), reasons
                reasons.append("audio echo: avatar did not start speaking")
                self.interrupt()
            except Exception as exc:
                reasons.append(f"audio echo failed: {type(exc).__name__}")
                self.interrupt()
        try:
            self._started.clear()
            self._send({"modality": "text", "text": text, "done": True}, "conversation.echo")
            if self._await_start():
                return self._spoken("avatar_text", text, meta, timer), reasons
            reasons.append("text echo: avatar did not start speaking")
            self.interrupt()
        except Exception as exc:
            reasons.append(f"text echo failed: {type(exc).__name__}")
            self.interrupt()
        self._health.set("avatar", "degraded", "; ".join(reasons), backend=self._backend)
        return None, reasons

    def _spoken(self, tier: str, text: str, meta: dict, timer: TurnTimer | None) -> str:
        if timer:
            timer.mark("tts_done")
            timer.mark("avatar_started")
            timer.mark("audible")
        self._bus.publish("tts.started", {"tier": tier, "subtitles": text, **meta})
        return tier
