"""Per-service health. Services report their own state; nothing here claims a service works."""

from __future__ import annotations

import threading

from app.config import Settings
from app.schemas import HealthResponse, ServiceHealth, ServiceState

SERVICES = ("camera", "face", "gesture", "lip", "scribe", "tts", "avatar")

# Milestone that builds each service; shown until the service registers itself.
_BUILT_IN = {
    "camera": "M1",
    "face": "M1",
    "gesture": "M2",
    "lip": "M3",
    "scribe": "M4",
    "tts": "M5",
    "avatar": "M5",
}

LIMITS = {
    "lip": [
        "frontal face only (yaw above the configured limit is rejected)",
        "needs good, even lighting",
        "Auto-AVSR checkpoints are English-oriented",
        "Hindi lip reading is not claimed",
        "lip text is a low-reliability hint, never a fact",
    ],
    "gesture": [
        "MediaPipe built-in gesture labels only; pointing at objects is out of scope",
    ],
    "speech": [
        "speaker label comes from /turn/start; no automatic diarization",
        "atypical speech may be transcribed wrongly or not at all",
    ],
}


class HealthRegistry:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._state: dict[str, ServiceHealth] = {
            name: ServiceHealth(
                status="unavailable",
                detail=f"not built yet ({_BUILT_IN[name]})",
                configured=self._configured(name),
            )
            for name in SERVICES
        }

    def set(self, name: str, status: ServiceState, detail: str = "", backend: str = "real") -> None:
        if name not in SERVICES:
            raise ValueError(f"unknown service '{name}'")
        with self._lock:
            self._state[name] = ServiceHealth(
                status=status,
                detail=detail,
                configured=self._configured(name),
                backend=backend,  # type: ignore[arg-type]
            )

    def get(self, name: str) -> ServiceHealth:
        with self._lock:
            return self._state[name]

    def snapshot(self) -> HealthResponse:
        with self._lock:
            services = dict(self._state)
        return HealthResponse(
            simulate=self._settings.simulate,
            services=services,
            avatar_mode=self._settings.tavus_pipeline_mode,
            limits=LIMITS,
        )

    def _configured(self, name: str) -> bool | None:
        s = self._settings
        if name == "lip":
            return s.lip_enabled and s.lip_checkpoint.is_file()
        if name == "scribe":
            return bool(s.elevenlabs_api_key)
        if name == "tts":
            return bool(
                s.elevenlabs_api_key and (s.voice_id or s.voice_id_male or s.voice_id_female)
            )
        if name == "avatar":
            return bool(s.tavus_api_key and s.tavus_replica_id and s.tavus_persona_id)
        return None  # camera/face/gesture have no credentials
