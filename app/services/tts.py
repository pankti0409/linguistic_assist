"""Speech output (sections 8.7-8.8): the only path from a confirmed message to sound.

`SpeechOutput.speak(confirmation_id)` is the single public entry point. It consumes the
one-time ID, so it gets the exact confirmed text from the registry and never from a request
body (R2). It then tries each tier once, in order, and stops at the first that works, so two
tiers never speak the same message:
  1. ElevenLabs audio -> Tavus echo (audio)      [M5, AvatarService]
  2. Tavus text echo (persona TTS)               [M5, AvatarService]
  3. local: ElevenLabs audio + subtitles to the frontend via WS (`output.fallback`)
Every payload carries synthetic:true and disclosure:"AI avatar" (R9).
"""

from __future__ import annotations

import base64
import logging
import threading
from typing import Any

from app.config import Settings
from app.core.confirmation import ConfirmationRegistry
from app.core.events import EventBus
from app.core.health import HealthRegistry
from app.core.timing import TurnTimer, now_ms
from app.core.voice import VoiceSelector

log = logging.getLogger(__name__)

TTS_MODEL = "eleven_flash_v2_5"  # ElevenLabs models page, checked 2026-10-31
LOCAL_FORMAT = "mp3_44100_128"  # browser-playable for the local fallback
DISCLOSURE = {"synthetic": True, "disclosure": "AI avatar"}


class ElevenLabsTTS:
    """TextToSpeech over ElevenLabs Flash v2.5 (elevenlabs SDK 2.75 signature)."""

    def __init__(self, api_key: str, model_id: str = TTS_MODEL) -> None:
        from elevenlabs.client import ElevenLabs

        self._client = ElevenLabs(api_key=api_key)
        self.model_id = model_id

    def synthesize(self, text: str, voice_id: str, output_format: str = LOCAL_FORMAT) -> bytes:
        chunks = self._client.text_to_speech.convert(
            voice_id=voice_id, text=text, model_id=self.model_id, output_format=output_format
        )
        return b"".join(chunks)


class NothingSpokenError(RuntimeError):
    """Every tier failed; the message was not spoken."""


class SpeechOutput:
    def __init__(
        self,
        settings: Settings,
        bus: EventBus,
        health: HealthRegistry,
        confirmations: ConfirmationRegistry,
        voice: VoiceSelector,
        tts=None,
        avatar=None,
    ) -> None:
        self._s = settings
        self._bus = bus
        self._health = health
        self._confirm = confirmations
        self._voice = voice
        self._tts = tts
        self._backend = "fake" if tts is not None else "real"
        self.avatar = avatar  # AvatarService, wired in M5; None means local only
        self._lock = threading.Lock()  # one message at a time
        if tts is not None:
            health.set("tts", "ok", "fake synthesiser", backend="fake")
        elif settings.elevenlabs_api_key and voice.any_configured:
            health.set("tts", "degraded", f"{TTS_MODEL} configured; not yet called")
        else:
            health.set("tts", "unavailable", "ELEVENLABS_API_KEY or voice not set")

    def _client(self):
        if self._tts is None:
            if not self._s.elevenlabs_api_key:
                raise RuntimeError("ELEVENLABS_API_KEY not set")
            self._tts = ElevenLabsTTS(self._s.elevenlabs_api_key)
        return self._tts

    def speak(self, confirmation_id: str, timer: TurnTimer | None = None) -> dict[str, Any]:
        """Consume the ID and speak its text through exactly one tier. Raises on a bad ID."""
        turn_id, text = self._confirm.consume(confirmation_id)  # raises ConfirmationError
        with self._lock:
            return self._speak(turn_id, confirmation_id, text, timer)

    def _speak(self, turn_id: str, cid: str, text: str, timer: TurnTimer | None):
        current = self._voice.current()
        if current is None:
            raise NothingSpokenError("no voice configured")
        gender, voice_id = current
        meta = {
            "turn_id": turn_id,
            "confirmation_id": cid,
            "voice_kind": "designed",
            "voice_gender": gender,
            **DISCLOSURE,
        }
        if timer:
            timer.mark("speak_start")
        reasons: list[str] = []
        if self.avatar is not None:
            tier, why = self.avatar.try_speak(text, voice_id, meta, timer, self._synth)
            if tier:
                return self._done(timer, tier, meta)
            reasons.extend(why)
        # tier 3: local audio + subtitles
        try:
            audio = self._synth(text, voice_id, LOCAL_FORMAT)
        except Exception as exc:
            log.warning("local TTS failed: %s", type(exc).__name__)
            self._health.set(
                "tts",
                "unavailable",
                f"last call failed: {type(exc).__name__}",
                backend=self._backend,
            )
            self._bus.publish(
                "error", {"source": "tts", "error": type(exc).__name__, "recoverable": True, **meta}
            )
            raise NothingSpokenError(f"local TTS failed: {type(exc).__name__}") from exc
        if timer:
            timer.mark("tts_done")
        reason = "; ".join(reasons) or "avatar not configured"
        self._bus.publish("output.fallback", {"reason": reason, **meta})
        self._bus.publish(
            "tts.started",
            {
                "tier": "local",
                "format": LOCAL_FORMAT,
                "subtitles": text,
                "audio_b64": base64.b64encode(audio).decode("ascii"),
                **meta,
            },
        )
        if timer:
            timer.mark("audible")  # earliest point the frontend can play it (D-034)
        return self._done(timer, "local", meta)

    def _synth(self, text: str, voice_id: str, fmt: str) -> bytes:
        audio = self._client().synthesize(text, voice_id, fmt)
        self._health.set("tts", "ok", f"{TTS_MODEL}; last call ok", backend=self._backend)
        return audio

    def _done(self, timer: TurnTimer | None, tier: str, meta: dict) -> dict[str, Any]:
        if timer:
            timer.tier = tier
        log.info("spoke turn %s via tier %s", meta["turn_id"], tier)
        return {"tier": tier, **meta, "ts_ms": now_ms()}
