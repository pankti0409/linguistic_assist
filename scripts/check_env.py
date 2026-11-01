"""Environment check (section 12). Prints PASS / FAIL / SKIP / INFO per item; exit 1 on any FAIL.

Checks Python, the webcam (one frame, nothing kept), the mic (0.2 s, discarded), each API key
with a cheap read-only call, each voice slot's gender label, daily-python, and model assets.
Key values are never printed.

Usage: python scripts/check_env.py [--no-camera] [--no-mic]
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app.config import load_settings  # noqa: E402

RESULTS: list[tuple[str, str, str]] = []
TIMEOUT = 20


def report(status: str, name: str, detail: str) -> None:
    RESULTS.append((status, name, detail))
    print(f"[{status:4}] {name:18} {detail}", flush=True)


def check_python() -> None:
    v = sys.version_info
    ok = (3, 10) <= (v.major, v.minor) <= (3, 13)
    report("PASS" if ok else "FAIL", "python", f"{v.major}.{v.minor}.{v.micro}")


def check_camera(s) -> None:
    from app.services.camera import OpenCVCamera, camera_indices

    if not s.camera_source.isdigit():
        report("SKIP", "camera", f"CAMERA_SOURCE is a file ({s.camera_source})")
        return
    cam = OpenCVCamera(camera_indices(s.camera_source), s.camera_size, s.camera_fps)
    try:
        if not cam.open():
            report("FAIL", "camera", "no webcam opened on indices " + str(cam.indices))
            return
        ok, frame = cam.read()  # frame stays in memory and is discarded (R8)
        if not ok or frame is None:
            report("FAIL", "camera", f"index {cam.opened_index} opened but gave no frame")
            return
        h, w = frame.shape[:2]
        report("PASS", "camera", f"index {cam.opened_index}, frame {w}x{h}")
    finally:
        cam.close()


def check_mic() -> None:
    try:
        import sounddevice as sd
    except ImportError:
        report("SKIP", "microphone", "sounddevice not installed")
        return
    try:
        dev = sd.query_devices(kind="input")
        rec = sd.rec(int(0.2 * 16000), samplerate=16000, channels=1, dtype="int16")
        sd.wait()
        n = len(rec)
        del rec  # audio is discarded immediately (R8)
        report("PASS", "microphone", f"'{dev['name']}', 16 kHz mono, {n} samples read")
    except Exception as exc:
        report("FAIL", "microphone", f"{type(exc).__name__}: {exc}")


def _get(url: str, headers: dict[str, str]) -> httpx.Response | None:
    try:
        return httpx.get(url, headers=headers, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        report("FAIL", "network", f"{url.split('/')[2]}: {type(exc).__name__}")
        return None


def check_elevenlabs(s) -> None:
    if not s.elevenlabs_api_key:
        report("FAIL", "elevenlabs key", "ELEVENLABS_API_KEY not set")
        return
    h = {"xi-api-key": s.elevenlabs_api_key}
    slots = {"male": s.voice_id_male, "female": s.voice_id_female}
    if s.voice_id and not slots[s.voice_default]:
        slots[s.voice_default] = s.voice_id
    for gender, vid in slots.items():
        name = f"voice ({gender})"
        if not vid:
            report("SKIP", name, f"VOICE_ID_{gender.upper()} not set")
            continue
        r = _get(f"https://api.elevenlabs.io/v1/voices/{vid}", h)
        if r is None:
            continue
        if r.status_code != 200:
            report("FAIL", name, f"HTTP {r.status_code}")
            continue
        d = r.json()
        label = (d.get("labels") or {}).get("gender")
        lang = (d.get("labels") or {}).get("language")
        status = "PASS" if label == gender else "FAIL"
        report(status, name, f"'{d.get('name')}', ElevenLabs label gender={label}, lang={lang}")


def check_groq(s) -> None:
    if not s.groq_api_key:
        report("FAIL", "groq key", "GROQ_API_KEY not set")
        return
    r = _get("https://api.groq.com/openai/v1/models", {"Authorization": f"Bearer {s.groq_api_key}"})
    if r is None:
        return
    if r.status_code != 200:
        report("FAIL", "groq", f"HTTP {r.status_code}")
        return
    ids = {m["id"] for m in r.json().get("data", [])}
    ok = s.llm_model in ids
    report(
        "PASS" if ok else "FAIL", "groq", f"key ok; {s.llm_model} {'listed' if ok else 'MISSING'}"
    )


def check_tavus(s) -> None:
    # Tavus renamed personas -> PALs and replicas -> faces; old names are aliases (D-014).
    if not s.tavus_api_key:
        report("FAIL", "tavus key", "TAVUS_API_KEY not set")
        return
    h = {"x-api-key": s.tavus_api_key}
    for name, path, rid in (
        ("tavus pal", "pals", s.tavus_persona_id),
        ("tavus face", "faces", s.tavus_replica_id),
    ):
        if not rid:
            report("SKIP", name, "id not set")
            continue
        r = _get(f"https://tavusapi.com/v2/{path}/{rid}", h)
        if r is None:
            continue
        if r.status_code != 200:
            report("FAIL", name, f"HTTP {r.status_code}")
            continue
        d = r.json()
        label = d.get("pal_name") or d.get("face_name") or d.get("replica_name") or "?"
        extra = f", pipeline_mode={d.get('pipeline_mode')}" if path == "pals" else ""
        report("PASS", name, f"{rid} '{label}'{extra}")


def check_daily() -> None:
    try:
        import daily  # noqa: F401  (daily-python's import name)
    except ImportError:
        report("SKIP", "daily-python", "not installed yet (M5)")
        return
    report("PASS", "daily-python", "imports")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def check_assets(s) -> None:
    for name in ("face_landmarker.task", "gesture_recognizer.task"):
        p = ROOT / "assets" / name
        if p.is_file():
            report("PASS", name, f"{p.stat().st_size} bytes sha256:{_sha(p)}...")
        else:
            report("FAIL", name, "missing; run scripts/download_models.py")
    if not s.lip_enabled:
        report("INFO", "lip checkpoint", "LIP_ENABLED=0; lip reports 'unavailable'")
    elif s.lip_checkpoint.is_file():
        report("PASS", "lip checkpoint", str(s.lip_checkpoint))
    else:
        report("INFO", "lip checkpoint", "not present yet (M3); lip reports 'unavailable'")


def main() -> int:
    s = load_settings()
    check_python()
    if "--no-camera" not in sys.argv:
        check_camera(s)
    if "--no-mic" not in sys.argv:
        check_mic()
    check_elevenlabs(s)
    check_groq(s)
    check_tavus(s)
    check_daily()
    check_assets(s)
    failed = [r for r in RESULTS if r[0] == "FAIL"]
    print(f"\n{len(RESULTS) - len(failed)} ok/skipped, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
