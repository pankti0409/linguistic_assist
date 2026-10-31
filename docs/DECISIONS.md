# Decisions log

Entries are dated and tied to a milestone. Anything that departs from `CLAUDE.md`, or that the
spec leaves open, is recorded here.

## M0 (2026-10-31)

### D-001 Credentials and IDs mapping
The keys were handed over without labels. Each one was mapped by format, then confirmed with a
cheap read-only call:
- `TAVUS_API_KEY`: the 32-hex key. `GET https://tavusapi.com/v2/personas/pb57f82ae2b1` succeeded.
- `TAVUS_PERSONA_ID=pb57f82ae2b1` (the "pal id"): persona name "Sahayak", `pipeline_mode: full`.
- `TAVUS_REPLICA_ID=rbd2cdb9a3f3`: not given directly. Taken from that persona's
  `default_replica_id`.
- `ELEVENLABS_API_KEY`: the `sk_…` key. `GET /v1/voices/{id}` succeeded for both voice IDs.
- `VOICE_ID=zT03pEAEi0VHKciJODfn`: "Raju - Relatable Hindi Voice", category `professional`.
- `VOICE_ID_ALT=9lx2GDtpvyyNBM7O9Mmx`: "Saavi – Calm Sales Agent Voice", category `professional`.
  The spec has no second voice slot, so this one is kept as a spare and is not used yet.
- `GROQ_API_KEY`: the `gsk_…` key. `GET /openai/v1/models` lists `openai/gpt-oss-120b`.

Both voices are ElevenLabs library voices, not clones of the patient. So `voice_clone` consent
does not apply to them, and their output is labelled `voice_kind:"designed"` (section 8.8). The
choice between Raju and Saavi is still open for the user.

### D-002 Consent is in-memory only
`ConsentRegistry` does not persist. Every restart requires consent again. This is the
conservative reading of R3. Revoking a purpose calls registered listeners so running services
can stop themselves (wired up from M1 onward).

### D-003 Health never claims an unbuilt service works
Until a service registers itself, `/health` reports it as `unavailable` with
`detail="not built yet (Mx)"`. `configured` only says whether credentials or assets are present,
never their values. Fakes report `backend:"fake"`.

### D-004 Fixed loopback bind
`BIND_HOST` is the constant `127.0.0.1` and cannot be overridden by env (R8). `PORT` can be.
`DEBUG_SAVE_CLIPS=true` makes settings construction fail.

### D-005 Coverage check lives outside the FusionResult model
"Each candidate covers every non-filler fragment id" needs the fragments, and `FusionResult`
does not hold them. It is `schemas.coverage_errors(result, fragments)`, called by the fusion
service (M4). The 2-3 candidate rule is a model validator.

### D-006 Dependencies added per milestone
`requirements.txt` holds only what M0 uses (plus numpy and opencv for the video-file fake
camera). `mediapipe`, `elevenlabs`, `groq`, `sounddevice` and `daily-python` are added at the
milestone that first calls them, with versions checked against their docs at that point.

### D-007 Error body for framework errors
Validation errors (422), HTTP errors and unhandled exceptions all render as
`{error_code, message, recoverable}`. Unhandled exceptions return only the exception type name,
never the message, so no stack details or data leak.

### D-008 Default port 8765
Port 8000 is already used by another local app on the development machine. The default is now
`8765`, and `PORT` overrides it. The bind address stays fixed at `127.0.0.1`.

### D-009 Local attack surface: Origin and Host checks
Binding to loopback does not stop a web page in the user's own browser from reaching the API.
- `/ws` refuses browser Origins that are not loopback (any port) or listed in `ALLOWED_ORIGINS`
  (comma-separated). The handshake is refused with HTTP 403. Clients that send no Origin (scripts, native apps)
  are allowed.
- `TrustedHostMiddleware` only accepts `Host: 127.0.0.1` or `localhost`, which defeats DNS
  rebinding. Tests use `base_url=http://127.0.0.1`.
- CORS middleware is deliberately absent, so cross-origin browser `fetch` calls with JSON
  bodies fail their preflight.

### Open items carried from M0
- The HTTP API has no client authentication. Any local process can call `/consent` today, and
  `/turn/confirm` once it exists in M4. That fits a single-user laptop PoC with R2 enforced
  server-side. Revisit in M7 (a per-launch token for the frontend).
- `VOICE_ID` is set to "Raju" (Hindi) and "Saavi" is kept as `VOICE_ID_ALT`. The user decides
  which voice is final.
