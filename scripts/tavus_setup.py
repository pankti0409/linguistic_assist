"""One-time Tavus setup (section 8.9): guardrails + relay PAL. Prints IDs for .env.

NOT run during the build (user decision 2026-10-31: no live Tavus calls). Field names are
from https://docs.tavus.io/openapi.yaml (POST /v2/guardrails, POST /v2/pals). Tavus calls a
persona a "PAL" now (D-014). Running this creates new resources on your account; it never
modifies an existing PAL.

Usage:
  python scripts/tavus_setup.py --dry-run          # print the request bodies only
  python scripts/tavus_setup.py --pal-name Sahayak --user-name "<name>"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app.config import load_settings  # noqa: E402
from app.services.avatar import TAVUS_BASE  # noqa: E402

CONTEXT = (
    "Messages arrive from {{USER_NAME}}'s assistive app only after explicit confirmation. "
    "Room: {{USER_NAME}} and one conversation partner. Languages: English, Hindi, code-mixed. "
    "Pronounce names as written."
)


def fill(text: str, pal: str, user: str) -> str:
    return text.replace("{{PAL_NAME}}", pal).replace("{{USER_NAME}}", user)


def bodies(pal_name: str, user_name: str, mode: str, face_id: str) -> tuple[list[dict], dict]:
    guardrails = json.loads((ROOT / "prompts" / "guardrails.json").read_text(encoding="utf-8"))
    for g in guardrails:
        if len(g["guardrail_prompt"]) > 1000:
            raise ValueError(f"{g['guardrail_name']}: prompt over 1,000 characters")
    persona = fill(
        (ROOT / "prompts" / "persona.md").read_text(encoding="utf-8"), pal_name, user_name
    )
    pal = {
        "pal_name": pal_name,
        "system_prompt": persona,
        "context": fill(CONTEXT, pal_name, user_name),
        "pipeline_mode": mode,
        "default_face_id": face_id,
        "dynamic_greeting": False,  # never speak unconfirmed words
        "guardrail_tags": ["ps16"],
        "layers": {"perception": {"perception_model": "off"}},  # no camera analysis (R4)
    }
    return guardrails, pal


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pal-name", default="Sahayak")
    ap.add_argument("--user-name", default="the user")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    s = load_settings()
    guardrails, pal = bodies(a.pal_name, a.user_name, s.tavus_pipeline_mode, s.tavus_replica_id)
    if a.dry_run:
        print(json.dumps({"guardrails": guardrails, "pal": pal}, indent=2, ensure_ascii=False))
        return 0
    if not s.tavus_api_key or not s.tavus_replica_id:
        print("TAVUS_API_KEY and TAVUS_REPLICA_ID (face id) are required")
        return 1
    http = httpx.Client(base_url=TAVUS_BASE, headers={"x-api-key": s.tavus_api_key}, timeout=30)
    for g in guardrails:
        r = http.post("/v2/guardrails", json=g)
        print(f"guardrail {g['guardrail_name']}: HTTP {r.status_code}")
        r.raise_for_status()
    r = http.post("/v2/pals", json=pal)
    r.raise_for_status()
    pal_id = r.json().get("pal_id")
    print(f"\nTAVUS_PERSONA_ID={pal_id}\nTAVUS_REPLICA_ID={s.tavus_replica_id}")
    print(
        "STT stays on Tavus' default; its output is never used, since the PAL only "
        "speaks echo text. See D-044."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
