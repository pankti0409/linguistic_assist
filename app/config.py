"""Runtime configuration. Every constant from CLAUDE.md section 8.10 is overridable by env."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent

# R8: the server only ever binds to loopback. Deliberately not configurable.
BIND_HOST = "127.0.0.1"


def _bool(v: str | None, default: bool) -> bool:
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _size(v: str | None, default: tuple[int, int]) -> tuple[int, int]:
    if not v:
        return default
    w, h = v.lower().split("x")
    return int(w), int(h)


def _clean(v: str | None) -> str:
    # strip inline comments like "full        # full | echo" from .env values
    return (v or "").split("#", 1)[0].strip()


@dataclass(frozen=True)
class Settings:
    # secrets / ids
    elevenlabs_api_key: str = ""
    groq_api_key: str = ""
    llm_model: str = "openai/gpt-oss-120b"
    voice_id: str = ""  # legacy single voice; fills the default slot if that slot is empty
    voice_id_male: str = ""
    voice_id_female: str = ""
    voice_default: str = "female"
    tavus_api_key: str = ""
    tavus_replica_id: str = ""
    tavus_persona_id: str = ""
    tavus_pipeline_mode: str = "full"

    # runtime switches
    simulate: bool = False
    camera_source: str = "0"
    lip_enabled: bool = True
    lip_checkpoint: Path = field(default_factory=lambda: ROOT / "assets" / "lip" / "vsr.pth")
    debug_preview: bool = False
    debug_save_clips: bool = False  # R8: must stay false; enforced in __post_init__
    port: int = 8765  # 8000 is taken by another local app on the dev machine (D-008)
    # Browser origins allowed to open /ws (D-009). Loopback on any port is always allowed.
    allowed_origins: tuple[str, ...] = ()
    face_model: Path = field(default_factory=lambda: ROOT / "assets" / "face_landmarker.task")

    # mouth_activity detector (not in the spec table; provisional, see D-012)
    mouth_window_s: float = 0.6
    mouth_on_std: float = 0.035
    mouth_off_std: float = 0.015

    # section 8.10 constants
    camera_fps: int = 30
    camera_size: tuple[int, int] = (640, 480)
    vision_fps: int = 15
    gesture_min_score: float = 0.7
    gesture_stable_frames: int = 8
    lip_buffer_s: float = 4.0
    lip_min_frames: int = 8
    lip_max_yaw_deg: float = 25.0
    context_turns: int = 6
    fragment_silence_s: float = 6.0
    fragment_max_s: float = 45.0
    phrasebook_topk: int = 5
    max_clarify_rounds: int = 2
    confirm_ttl_s: float = 120.0
    turn_max_s: float = 20.0
    calibrate_timeout_s: float = 10.0

    def __post_init__(self) -> None:
        if self.debug_save_clips:
            raise ValueError("DEBUG_SAVE_CLIPS must be false (R8: no raw media on disk)")
        if self.tavus_pipeline_mode not in {"full", "echo"}:
            raise ValueError("TAVUS_PIPELINE_MODE must be 'full' or 'echo'")
        if self.voice_default not in {"male", "female"}:
            raise ValueError("VOICE_DEFAULT must be 'male' or 'female'")
        if self.mouth_off_std >= self.mouth_on_std:
            raise ValueError("MOUTH_OFF_STD must be below MOUTH_ON_STD (hysteresis)")


def load_settings(env: Mapping[str, str | None] | None = None) -> Settings:
    """Build Settings from `env`, or from the process env layered over `.env`."""
    if env is None:
        merged: dict[str, str | None] = dict(dotenv_values(ROOT / ".env"))
        merged.update(os.environ)
        env = merged

    def g(key: str) -> str | None:
        v = env.get(key)
        return None if v is None else _clean(v)

    d = Settings()
    return Settings(
        elevenlabs_api_key=g("ELEVENLABS_API_KEY") or "",
        groq_api_key=g("GROQ_API_KEY") or "",
        llm_model=g("LLM_MODEL") or d.llm_model,
        voice_id=g("VOICE_ID") or "",
        voice_id_male=g("VOICE_ID_MALE") or "",
        voice_id_female=g("VOICE_ID_FEMALE") or "",
        voice_default=g("VOICE_DEFAULT") or d.voice_default,
        tavus_api_key=g("TAVUS_API_KEY") or "",
        tavus_replica_id=g("TAVUS_REPLICA_ID") or "",
        tavus_persona_id=g("TAVUS_PERSONA_ID") or "",
        tavus_pipeline_mode=g("TAVUS_PIPELINE_MODE") or d.tavus_pipeline_mode,
        simulate=_bool(g("SIMULATE"), d.simulate),
        camera_source=g("CAMERA_SOURCE") or d.camera_source,
        lip_enabled=_bool(g("LIP_ENABLED"), d.lip_enabled),
        lip_checkpoint=Path(g("LIP_CHECKPOINT")) if g("LIP_CHECKPOINT") else d.lip_checkpoint,
        debug_preview=_bool(g("DEBUG_PREVIEW"), d.debug_preview),
        debug_save_clips=_bool(g("DEBUG_SAVE_CLIPS"), d.debug_save_clips),
        port=int(g("PORT") or d.port),
        allowed_origins=tuple(
            o.strip() for o in (g("ALLOWED_ORIGINS") or "").split(",") if o.strip()
        ),
        face_model=Path(g("FACE_MODEL")) if g("FACE_MODEL") else d.face_model,
        mouth_window_s=float(g("MOUTH_WINDOW_S") or d.mouth_window_s),
        mouth_on_std=float(g("MOUTH_ON_STD") or d.mouth_on_std),
        mouth_off_std=float(g("MOUTH_OFF_STD") or d.mouth_off_std),
        camera_fps=int(g("CAMERA_FPS") or d.camera_fps),
        camera_size=_size(g("CAMERA_SIZE"), d.camera_size),
        vision_fps=int(g("VISION_FPS") or d.vision_fps),
        gesture_min_score=float(g("GESTURE_MIN_SCORE") or d.gesture_min_score),
        gesture_stable_frames=int(g("GESTURE_STABLE_FRAMES") or d.gesture_stable_frames),
        lip_buffer_s=float(g("LIP_BUFFER_S") or d.lip_buffer_s),
        lip_min_frames=int(g("LIP_MIN_FRAMES") or d.lip_min_frames),
        lip_max_yaw_deg=float(g("LIP_MAX_YAW_DEG") or d.lip_max_yaw_deg),
        context_turns=int(g("CONTEXT_TURNS") or d.context_turns),
        fragment_silence_s=float(g("FRAGMENT_SILENCE_S") or d.fragment_silence_s),
        fragment_max_s=float(g("FRAGMENT_MAX_S") or d.fragment_max_s),
        phrasebook_topk=int(g("PHRASEBOOK_TOPK") or d.phrasebook_topk),
        max_clarify_rounds=int(g("MAX_CLARIFY_ROUNDS") or d.max_clarify_rounds),
        confirm_ttl_s=float(g("CONFIRM_TTL_S") or d.confirm_ttl_s),
        turn_max_s=float(g("TURN_MAX_S") or d.turn_max_s),
        calibrate_timeout_s=float(g("CALIBRATE_TIMEOUT_S") or d.calibrate_timeout_s),
    )
