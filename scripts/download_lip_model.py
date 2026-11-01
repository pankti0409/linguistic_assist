"""Download the Auto-AVSR VSR checkpoint into assets/lip/ (M3).

Source: the model zoo table in third_party/auto_avsr/README.md (Google Drive links).
The checkpoint is trained on LRS3 + VoxCeleb2: non-commercial research use only
(see docs/LICENSES.md). Google Drive sometimes answers "Quota exceeded" for these files;
this script detects that, keeps nothing, and asks you to retry later (up to 24 h).
It never works around the quota.

Usage: python scripts/download_lip_model.py [name]
  name: vsr_trlrs3vox2_base (default), vsr_trlrs3_base, vsr_trlrs2lrs3vox2avsp_base
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "assets" / "lip"
# name: (Google Drive file id, MD5 prefix from the README model zoo)
ZOO = {
    "vsr_trlrs3vox2_base": ("1shcWXUK2iauRhW9NbwCc25FjU1CoMm8i", "774a6"),
    "vsr_trlrs3_base": ("12PNM5szUsk_CuaV1yB9dL_YWvSM1zvAd", "c00a7"),
    "vsr_trlrs2lrs3vox2avsp_base": ("1r1kx7l9sWnDOCnaFHIGvOtzuhFyFA88_", "49f77"),
}
URL = "https://drive.usercontent.google.com/download?id={id}&export=download&confirm=t"


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "vsr_trlrs3vox2_base"
    if name not in ZOO:
        print(f"unknown checkpoint '{name}'; choose from {', '.join(ZOO)}")
        return 2
    file_id, md5_prefix = ZOO[name]
    DEST.mkdir(parents=True, exist_ok=True)
    part = DEST / f"{name}.pth.part"
    md5 = hashlib.md5()
    with httpx.stream("GET", URL.format(id=file_id), follow_redirects=True, timeout=120) as r:
        ctype = r.headers.get("content-type", "")
        if r.status_code != 200 or not ctype.startswith("application/octet-stream"):
            body = r.read()[:4000].decode("utf-8", "replace")
            why = "Quota exceeded" if "Quota exceeded" in body else f"HTTP {r.status_code} {ctype}"
            print(f"[FAIL] Google Drive refused the download: {why}. Try again later.")
            return 1
        total = int(r.headers.get("content-length", 0))
        done = 0
        with part.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                md5.update(chunk)
                done += len(chunk)
                if total:
                    print(f"\r{done / 1e6:8.1f} / {total / 1e6:.1f} MB", end="", flush=True)
    print()
    digest = md5.hexdigest()
    if not digest.startswith(md5_prefix):
        part.unlink(missing_ok=True)
        print(f"[FAIL] MD5 {digest} does not start with {md5_prefix}; file deleted")
        return 1
    final = DEST / "vsr.pth"  # the path LIP_CHECKPOINT defaults to
    part.replace(final)
    print(f"[ OK ] {name} -> {final} (md5 {digest})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
