# PS-16 Voice Bridge (frontend)

The patient-facing app for the PS-16 backend: Next.js 16, React 19, Tailwind 4, Motion.
Every screen shows live backend data. Nothing in this app is mocked.

## Run

```bash
# 1. backend (repo root), with the webcam self-view on (DEBUG_PREVIEW=1 in .env)
./scripts/run.ps1            # or ./scripts/run.sh
# 2. frontend
cd frontend
pnpm install
pnpm build && pnpm start     # http://localhost:3000   (or: pnpm dev)
```

`BACKEND_URL` / `NEXT_PUBLIC_BACKEND_URL` override the default `http://127.0.0.1:8765`.

## How it talks to the backend

- **HTTP** goes to `/backend/*`, which `next.config.mjs` rewrites to the backend. The browser
  stays same-origin, and the backend keeps sending no CORS headers.
- **WebSocket** `ws://127.0.0.1:8765/ws` drives everything live: turn state, fragments,
  candidates, questions, speech output, camera, gestures, lip and errors.
- **Webcam:** the backend owns the laptop webcam (R1). The browser never calls getUserMedia.
  The picture is the backend's in-memory MJPEG self-view (`/camera/preview.mjpg`, only with
  `DEBUG_PREVIEW=1`), overlaid with live face / mouth / gesture / lip results.
- **Avatar:** the Tavus room is embedded receive-only. No camera or mic permission is
  delegated to the iframe.
- **Token:** if the backend sets `ACCESS_TOKEN`, enter it under Setup. It is sent as
  `X-PS16-Token`, or `?token=` for the WS and preview.

## Screens

| Screen | What it does |
|---|---|
| My message | Pick inputs and language, record in pieces across pauses, watch fragments arrive (stutters, fillers and unsure words marked), choose 1 of 2-3 candidates with added words highlighted, answer yes/no questions (or thumbs up/down), edit with a review-before-speaking step, see and replay what was said |
| Partner | Record the partner's question as context; labelled recent conversation |
| Camera & gestures | Large self-view, live gesture feed, full lexicon editor (7 gestures x either/left/right, finish/clear actions), teach-a-gesture calibration |
| My words | Profile terms and the phrasebook (personalisation consent; delete is always allowed) |
| Avatar & voice | Male/female voice, start/end the Tavus session, the output order |
| Setup & permissions | All 5 consents, live service status and limits, theme, access token |
| Insights | Measured p50/p95 per stage, counters, recent turns |

Plus an event log drawer, light and dark themes, phone / tablet / desktop layouts, keyboard
focus throughout, and reduced-motion support.
