"""Fetch the MediaPipe .task bundles into assets/ and print their checksums.

URLs are the "Latest" links on the official MediaPipe guide pages (checked 2026-10-31):
  developers.google.com/edge/mediapipe/solutions/vision/face_landmarker
  developers.google.com/edge/mediapipe/solutions/vision/gesture_recognizer

Usage: python scripts/download_models.py [--force]
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
_BASE = "https://storage.googleapis.com/mediapipe-models"
MODELS = {
    "face_landmarker.task": (
        f"{_BASE}/face_landmarker/face_landmarker/float16/latest/face_landmarker.task"
    ),
    "gesture_recognizer.task": (
        f"{_BASE}/gesture_recognizer/gesture_recognizer/float16/latest/gesture_recognizer.task"
    ),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(name: str, url: str, force: bool) -> Path:
    dest = ASSETS / name
    if dest.is_file() and not force:
        print(f"[keep] {name} already present")
        return dest
    tmp = dest.with_suffix(".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=60) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    tmp.replace(dest)
    print(f"[get ] {name} <- {url}")
    return dest


def main() -> int:
    ASSETS.mkdir(exist_ok=True)
    force = "--force" in sys.argv
    for name, url in MODELS.items():
        path = fetch(name, url, force)
        print(f"       {path.stat().st_size:>10} bytes  sha256={sha256(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
