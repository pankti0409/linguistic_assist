"""Output voice selection: switch between a male and a female voice at runtime.

The TTS service (M5) asks `current()` for the voice ID at speak time. Each slot's gender
comes from ElevenLabs' own voice labels, checked by scripts/check_env.py, not from the voice name.
"""

from __future__ import annotations

import threading
from typing import Literal

from pydantic import BaseModel

from app.config import Settings
from app.core.errors import AppError

VoiceGender = Literal["male", "female"]
GENDERS: tuple[VoiceGender, ...] = ("male", "female")


class VoiceNotConfiguredError(AppError):
    status_code = 409
    error_code = "voice_not_configured"
    recoverable = True


class VoiceSlot(BaseModel):
    gender: VoiceGender
    configured: bool
    voice_id: str | None = None  # a public library ID, not a secret


class VoiceState(BaseModel):
    selected: VoiceGender | None
    voices: list[VoiceSlot]
    voice_kind: Literal["designed"] = "designed"  # library voices, not a clone (section 8.8)


class VoiceSelector:
    def __init__(self, settings: Settings) -> None:
        self._ids: dict[str, str] = {
            "male": settings.voice_id_male,
            "female": settings.voice_id_female,
        }
        if settings.voice_id and not self._ids[settings.voice_default]:
            self._ids[settings.voice_default] = settings.voice_id
        self._lock = threading.Lock()
        configured = [g for g in GENDERS if self._ids[g]]
        if settings.voice_default in configured:
            self._selected: VoiceGender | None = settings.voice_default  # type: ignore[assignment]
        else:
            self._selected = configured[0] if configured else None

    def select(self, gender: VoiceGender) -> VoiceState:
        if not self._ids.get(gender):
            raise VoiceNotConfiguredError(
                f"no {gender} voice configured; set VOICE_ID_{gender.upper()} in .env"
            )
        with self._lock:
            self._selected = gender
        return self.state()

    def current(self) -> tuple[VoiceGender, str] | None:
        with self._lock:
            g = self._selected
        return (g, self._ids[g]) if g else None

    def state(self) -> VoiceState:
        with self._lock:
            sel = self._selected
        return VoiceState(
            selected=sel,
            voices=[
                VoiceSlot(gender=g, configured=bool(self._ids[g]), voice_id=self._ids[g] or None)
                for g in GENDERS
            ],
        )

    @property
    def any_configured(self) -> bool:
        return any(self._ids.values())
