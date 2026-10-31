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
- ~~Voice choice~~: resolved in M1 (D-017). Both voices are kept, and the user switches at runtime.

## M1 (2026-10-31)

### D-010 MediaPipe 1.2.0, verified from installed source
MediaPipe 1.2.0 is newer than the spec author's reference. Names were checked in
`mediapipe/tasks/python/vision/face_landmarker.py`: `FaceLandmarkerOptions(base_options,
running_mode, num_faces, output_face_blendshapes, output_facial_transformation_matrixes,
result_callback)`, `detect_async(image, timestamp_ms)` (raises on a timestamp that is not
increasing), `Blendshapes.JAW_OPEN=25` / `MOUTH_CLOSE=27` (looked up by `category_name`
"jawOpen" / "mouthClose"), and `FaceLandmarksConnections.FACE_LANDMARKS_LIPS`, which gives
40 lip landmark indices. Model URLs are the "Latest" links on the official guide pages
(`.../float16/latest/*.task`). The SHA-256 of each bundle is printed by
`scripts/download_models.py`:
- face_landmarker.task      64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff
- gesture_recognizer.task   97952348cf6a6a4915c2ea1496b4b37ebabc50cbbf80571435643c455f2b0482
Because `latest` can move, these hashes record what was tested.

### D-011 New WS event `mouth.activity`
M1 acceptance asks for streamed mouth_activity events, but the section 7 event list has no
type for them. Added `mouth.activity`, published when its state flips plus a 1 s heartbeat.
Payload, derived features only (R8): `active, changed, face_present, level, yaw_deg,
pitch_deg, obs_ts_ms, lag_ms`. No landmarks or pixels.

### D-012 mouth_activity thresholds are provisional
Activity = max(std(jawOpen), std(mouthClose)) over `MOUTH_WINDOW_S`=0.6 s. It turns on above
`MOUTH_ON_STD`=0.035 and off below `MOUTH_OFF_STD`=0.015. All three are env-overridable.
Live run on the dev webcam: still periods measured 0.0001-0.025, activations measured
0.036-0.125. The builder could not confirm that those activations matched real speech, and
large head turns (|yaw| > 40 degrees) were present during the run. Tune them with
`scripts/watch_events.py --changes` while someone talks, then mouths silently, then stays
still.

### D-013 Camera lifecycle follows `camera` consent
`POST /consent {camera}` starts CameraHub and FaceService. `DELETE /consent/camera` stops
both and clears frames and observations from memory. The spec defines no camera start route,
and this keeps "processing runs only while consent is held" true by construction.

### D-014 Tavus renamed personas to PALs and replicas to faces
The current `https://docs.tavus.io/openapi.yaml` lists `/v2/pals` and `/v2/faces`. It says
`/v2/replicas` and `replica_id` remain legacy aliases. `/v2/personas/{id}` still answered 200
in M0. `check_env.py` uses the documented `GET /v2/pals/{id}` and `GET /v2/faces/{id}`. The
env names `TAVUS_PERSONA_ID` / `TAVUS_REPLICA_ID` are kept, to match the spec.
The existing PAL "Sahayak" (pb57f82ae2b1) already has a relay system prompt and guardrails
(`g17d4d797de66`). It also has `dynamic_greeting: true`, which conflicts with "speak only
confirmed text". This must be handled in M5, before any session is opened. M5 also has to
re-check every field in section 8.9 against the PAL schema.

### D-015 OpenCV: contrib build only
mediapipe 1.2.0 depends on `opencv-contrib-python`. With `opencv-python` also installed there
are two competing `cv2` packages, so `opencv-python` was removed and only the contrib build
is listed.

### D-016 Debounced face presence
On the real webcam, raw detections alternated hit/miss frame to frame, which spammed events
and kept the activity window from filling. `face_present` in events and health is now
debounced: on after 2 consecutive hits, off after 5 consecutive misses (~0.33 s). Raw
per-frame presence is kept in `FaceService.history()`, because the M3 rule "face missing
> 20% of frames" must use raw frames.

### D-017 Male / female voice switching
`.env` now has `VOICE_ID_MALE` (Raju) and `VOICE_ID_FEMALE` (Saavi), plus `VOICE_DEFAULT`.
`GET /voice` shows the slots, and `PUT /voice {"gender": "male" | "female"}` switches at
runtime. The TTS service (M5) reads the selection at speak time. Each slot's gender comes
from ElevenLabs' `labels.gender`, which `check_env.py` verifies (both PASS), not from the
voice name. Both voices are Hindi library voices. Not covered by the switch:
- The Tavus face (`rbd2cdb9a3f3`, "Helen - Home") does not change with the voice.
- In the text-echo tier (8.8 tier 2), Tavus uses the PAL's own TTS voice. Switching there
  would need a second PAL or a per-session layer override, to be checked in M5.
