"""Print live events from a running backend, e.g. to watch mouth_activity while you talk.

Usage:
  python scripts/watch_events.py                    # all events
  python scripts/watch_events.py mouth.activity     # only these types
  python scripts/watch_events.py --changes          # mouth.activity only when it flips

The backend must be running and camera consent granted (POST /consent {"purpose":"camera"}).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import websockets


async def main(types: set[str], changes_only: bool) -> None:
    port = os.environ.get("PORT", "8765")
    async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
        print(f"connected to ws://127.0.0.1:{port}/ws (Ctrl+C to stop)")
        async for raw in ws:
            ev = json.loads(raw)
            if types and ev["type"] not in types:
                continue
            if changes_only and ev["type"] == "mouth.activity" and not ev["data"].get("changed"):
                continue
            print(ev["ts_ms"], ev["type"], json.dumps(ev["data"]), flush=True)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    try:
        asyncio.run(main(set(args), "--changes" in sys.argv))
    except KeyboardInterrupt:
        pass
