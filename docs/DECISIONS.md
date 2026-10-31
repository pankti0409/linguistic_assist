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

## M2 (2026-10-31)

### D-018 Handedness from unmirrored frames
The MediaPipe hand guide says handedness is the subject's own hand, and that "passing a
horizontally mirrored image will invert these outputs". OpenCV frames are not mirrored, so
they go to the recognizer unchanged. `Thumb_Up|Left` means the patient's left hand. A
frontend that shows a mirrored preview should not change the lexicon.

### D-019 Debounce rules, made exact
Per hand: 8 consecutive frames with the same label and score >= 0.7 emit one token. Another
token with the same key needs either a return to `None` (or the hand leaving the frame) and
a new stable run, or 1.5 s more of continuous hold. A frame below the score threshold breaks
the run but does not re-arm, so a flicker cannot fake a repeat. A different gesture in
between does count as a change.

### D-020 Lexicon storage and validation
Lexicon file: `calibration/default.json`. Lookup tries the exact `Label|Hand` key first,
then `Label|*`. `PUT /gesture/lexicon` replaces the whole map. Only the 7 canned labels,
`Left|Right|*`, non-empty words and the two reserved words are accepted; anything else
returns 422. Calibration waits `CALIBRATE_TIMEOUT_S` (10 s) and returns 408 on timeout.
The token captured during calibration is not also emitted as a word.

### D-021 M2 live evidence, and what is still unverified
Live run on the dev webcam: the recognizer ran at 14.8 results/s. Someone's real left-hand
`Pointing_Up` (scores 0.72-0.76) produced stable `gesture.token` events, with 1.5 s
hold-repeats. A second run with a temporary demo lexicon saw `Open_Palm` in 18 frames, but
never 8 consecutive at >= 0.7, so correctly no token. The token -> `gesture.word` step is
covered by tests, but not yet seen live with a mapped gesture. Verify with
`scripts/watch_events.py gesture.token gesture.word` while showing a thumbs-up steadily for
about 1 s.

## M3 (2026-10-31)

### D-022 Auto-AVSR integration: what is theirs and what is ours
Auto-AVSR is cloned at commit `182b62837773ab01052d4ac21ef1d2203ea7d267` into
`third_party/auto_avsr` (gitignored). The reader calls their code unchanged:
- `preparation/detectors/mediapipe/video_process.VideoProcess` for landmark interpolation,
  temporal smoothing, similarity alignment to `20words_mean_face.npy`, and the 96x96 crop;
- `datamodule/transforms.VideoTransform("test")` for /255, CenterCrop(88), Grayscale and
  Normalize(0.421, 0.165);
- `lightning.ModelModule` with `get_beam_search_decoder`.

Two bridges are written here:
1. Their MediaPipe detector uses the legacy `mp.solutions.face_detection` API, which
   MediaPipe 1.2.0 no longer has. Instead we feed the same 4 points (right eye, left eye,
   nose tip, mouth centre) from FaceLandmarker: the mean of each eye's contour, mesh
   index 1, and the mean of the lip contour. The two eyes are ordered by image x, to
   match the 68-point reference (36-41 = subject's right eye, on the image left).
2. Frames are greyscaled on arrival to save memory (about 37 MB for 4 s at 30 fps),
   instead of inside `VideoTransform`. `VideoProcess(convert_gray=False)` then works on
   the single-channel frames. The clip is resampled to 25 fps, the frame rate of
   LRS3 / VoxCeleb2.

### D-023 Yaw rule for lip evidence
The spec says "yaw over 25 degrees". Applied as: more than 20% of the clip's face
observations with |yaw| > `LIP_MAX_YAW_DEG` makes the evidence insufficient. This mirrors
the face-missing rule, so a single glance away does not discard a clip. Both fractions are
measured on raw per-frame observations, never on interpolated frames.

### D-024 Lip score
`ModelModule.forward` discards the beam score, so `_decode` repeats its 6 steps and keeps
the best hypothesis score. It reports `exp(score / tokens)`, capped at 1. This is a
relative hint, not a calibrated probability. Lip output is always `hint_only: true`.

### D-025 Checkpoint download blocked by Google Drive quota
The tutorial's `doc.ic.ac.uk` URLs return 404. All four VSR checkpoints in the README
model zoo (Google Drive) currently answer "Quota exceeded" for full downloads. Single
small byte ranges were served: the first bytes confirmed a PyTorch zip named
`vsr_trlrs3vox2_base.pth` of 1,001,892,616 bytes. A full download was not forced around the
quota. `scripts/download_lip_model.py` retries the official link, detects the quota page,
verifies the README MD5 prefix, and saves to `assets/lip/vsr.pth`. Until then lip reports
`unavailable` with the reason, and only `mouth_activity` is used (section 8.4). Preferred
checkpoint: `vsr_trlrs3vox2_base` (24.6% WER on LRS3). All VSR checkpoints are the same
size (250 M params), so "smallest" does not discriminate between them. This one avoids
LRS2's BBC licence.

### D-026 M3 live evidence
Real webcam plus FaceLandmarker: a 3 s push capture buffered 90 frames (30 fps). It
published `lip.result {status: unavailable, reason: checkpoint missing, hint_only: true}`,
and FaceService history was empty after stop. Auto-AVSR's real preprocessing ran in tests
on our landmarks (20 x 1 x 88 x 88 output) without model weights. No lip text has been
produced yet, and none is claimed.

## M4 (2026-11-01)

### D-027 Groq: strict json_schema
The Groq structured-outputs docs list `openai/gpt-oss-120b` for strict mode. So
`response_format={"type": "json_schema", "json_schema": {"name", "strict": true, "schema"}}`
is used with a hand-written schema: every property required, every object
`additionalProperties: false`, and nullable `clarifying_question` via `["string", "null"]`.
The 3-candidate maximum and the coverage rule are checked by Pydantic and
`coverage_errors`, not by the schema.

### D-028 Groq daily token cap (blocking live checks)
The key is on the `on_demand` tier: 200,000 tokens/day for gpt-oss-120b, 8,000/min, 1,000
requests. On 2026-10-31/11-01 the org had already used about 199,900 tokens/day (another
user of the key), so full reconstruction calls (~1,050 tokens each) were refused while a
5-token call passed. Rate limits and network errors now fail fast (`LLMUnavailableError`):
they do not use up the one retry that is meant for invalid output, and the patient sees
"sentence suggestions unavailable right now; edit or repeat". **The live Groq run of the
worked example is still pending.** The logic is covered by tests with a scripted LLM.

### D-029 Function-word allowlists
`prompts/function_words_{en,hi}.txt`. Negations (not/no/never, नहीं/मत/ना) are excluded
on purpose: adding one flips the meaning. "like" (EN) and "चाहिए / chahiye" (HI) are
allowed as request frames, following the spec's own "I would like ..." example; "want" and
"need" are not. The Hindi list is a draft for review by a Hindi speaker. The tokenizer
covers the Devanagari letters and matras, but not the danda "।" (found by a failing test).

### D-030 Scribe batch only
`scribe_v2` batch, per the spec's ordering. The realtime socket (`scribe_v2_realtime`) is
deferred, so there are no `speech.partial` events yet. Request options: `file_format=
"pcm_s16le_16"` (raw 16 kHz mono int16, no WAV wrapper), `timestamps_granularity="word"`,
`tag_audio_events=false`. `no_verbatim` stays off so the transcript is raw. The language
code comes back as ISO 639-3 (`eng`).

### D-031 Pause segmentation for fragments
A batch API returns one text per request. To get one fragment per utterance, mic audio is
cut at pauses by an energy segmenter: 30 ms frames, adaptive noise floor + 12 dB (floor
-50 dBFS), 3 loud frames to start, 700 ms quiet to end, at least 250 ms of *voiced* audio,
15 s maximum. Utterances are transcribed one at a time, in order. Live: synthetic speech
"wa / water / cold" with 1.5-2 s pauses gave exactly 3 utterances. On the real laptop mic,
room sound (p90 -37 dBFS) kept one 5.3 s "utterance" open with nobody speaking; Scribe
returned empty text and no fragment was made. This needs tuning on real recordings.

### D-032 Speech confidence and empty finals
`SpeechEvidence.confidence` (an added optional field) = exp(mean word logprob) from Scribe's
per-word `logprob`, i.e. only provider data. `low_confidence` is flagged when the text is
<= 2 characters or confidence < 0.4. Empty finals emit `speech.final` but create no
fragment, since there is no content to reconstruct from.

### D-033 Token cap with a reasoning model
`max_completion_tokens=300` (spec <= 300), `reasoning_effort="low"`, `include_reasoning=
false`. Whether 300 is enough for gpt-oss reasoning plus 3 candidates is unverified until
the live run (D-028). The one live call that went through returned valid JSON with only 1
candidate, which the validator rejected.

### D-034 What "e2e latency" measures
`e2e_ms` = end of capture -> `audible`. For the local tier, `audible` is when the audio is
published to the frontend (the backend cannot observe playback). For avatar tiers (M5) it
is Tavus' `started_speaking` event. Reports must state which.

### D-035 `EvidencePacket.clarifications`
An added field `[{question, answer}]`. Without it the LLM would see a bare "yes" fragment
with no question to attach it to.

### D-036 Failed output returns to AWAITING_CONFIRM
If every tier fails, SPEAKING -> AWAITING_CONFIRM, which the spec diagram does not draw.
The used confirmation_id stays dead, and a new confirm issues a new one.

### D-037 Clarify answers given by button
The answer from `POST /turn/clarify` is recorded as a `gesture`-source fragment (a deliberate
patient input). Fragment sources are limited to speech/gesture/lip.

### D-038 Post-validator details
`added_words` are recomputed in code (tokens not in any fragment) instead of trusting the
LLM. If one candidate survives, the result becomes clarification_required with the
yes/no question `Did you mean: "<text>"?`. If none survive, it is a clarification result.
The rounds cap applies after 2 answers. The fallback text excludes the yes/no answers.

### D-039 Edit flow
`/turn/confirm {edited_text}` the first time puts the text in EDITING and shows it back
(`confirm_required: true`). Sending the identical text again speaks it. No other fields
were needed.

### D-040 Personalisation consent
Phrasebook and profile-term reads, writes and retrieval need `personalization` consent.
`DELETE /phrasebook` is always allowed. Revoking consent stops use but does not delete;
deletion is a separate, explicit act.

### D-041 ElevenLabs plan blocks the configured voices
`text_to_speech` with Raju / Saavi returns **402 paid_plan_required**: "Free users cannot use
library voices via the API." On this plan only the 21 premade voices work (e.g. Sarah
`EXAVITQu4vr4xnSDxMaL` female, Brian `nPczCjzI2devNBz1zQrb` male; ElevenLabs labels). The
live Scribe check used Sarah ad hoc; `.env` is unchanged pending the user's decision.

## M5 (2026-11-01)

### D-042 Greeting blocked per conversation, PAL untouched
The current OpenAPI allows `dynamic_greeting` per conversation ("Optional override of the
PAL's `dynamic_greeting`"). Every conversation is created with `dynamic_greeting: false`
and no `custom_greeting`, so the avatar's first words are always a confirmed echo. The
existing "Sahayak" PAL is not modified: the user chose no live Tavus calls, and this
override makes a change unnecessary.

### D-043 Echo transport and ladder, as built
- The backend joins the room with daily-python 0.36 (installs and imports on Windows),
  `client_settings={"inputs": {"camera": False, "microphone": False}}`, and is the only
  sender of `conversation.echo` / `conversation.interrupt`. So the `speak_token` fallback
  in the spec is not needed.
- Tier 1 audio echo: ElevenLabs `pcm_16000` -> base64, `sample_rate: 16000`, one stable
  `inference_id`, `done: false` until the last chunk. The OpenAPI says audio is
  "Base64 audio ... (PCM or pipeline-specific encoding)" and that `done` must end true. The
  Daily app-message size limit and the PAL's acceptance of audio echo in `full` mode are
  **not verified**. Chunk size is `AVATAR_CHUNK_BYTES` (16,000 raw bytes); tier 1 can be
  switched off with `AVATAR_AUDIO_ECHO=0`.
- A tier counts as spoken only when `conversation.replica.started_speaking` arrives
  within `AVATAR_START_TIMEOUT_S` (6 s). Otherwise `conversation.interrupt` is sent before
  the next tier, so two tiers never speak one message (tested).
- R9: `synthetic` and `disclosure` are added as top-level keys on every app message, next
  to the documented ones. Whether Tavus tolerates extra keys is unverified live.
- `callback_url` (guardrail webhook) is set only when `TAVUS_CALLBACK_URL` is configured.
  Tavus cannot reach a 127.0.0.1 server without a tunnel. Guardrail app-messages that
  arrive in the room are forwarded too.

### D-044 Not done in M5, by decision
No Tavus API call or conversation was made (user decision: code only). Therefore:
- **The confirmed sentence has not been spoken by the avatar**, and the 10-sentence
  verbatim test (EN / HI / mixed, `tests/test_persona_live.py`) has not run. The decision
  to switch `TAVUS_PIPELINE_MODE` from full to echo is still open.
- The live red-team harness is a placeholder that fails if enabled. It needs the
  `conversation.utterance` (role `pal`) transcript events, collected over daily-python.
- `scripts/tavus_setup.py` has only been dry-run. It creates new guardrails and a new PAL
  (`perception_model: "off"`, `dynamic_greeting: false`, `guardrail_tags: ["ps16"]`) and
  never modifies an existing PAL. Tavus' STT layer is left at its default: the spec asks
  for "STT off", but the OpenAPI `layers.stt` has no documented "off" value. A relay PAL
  only speaks echo text, so STT output is never spoken.
Fallback was verified live: with no avatar session, a real end-to-end turn spoke through
tier 3 (real Scribe -> fallback -> edit-confirm -> real ElevenLabs Flash v2.5, premade
voice via env override). That one turn measured scribe 672 ms, TTS 515 ms, e2e 1,703 ms
(to audio published). "Killing Tavus" is covered by tests (transport raising, and avatar
silent), not live.

## M6 (2026-11-01)

### D-045 Deterministic scoring, no LLM judge
Following the agentic-eval skill's outcome-based pattern, every metric is a rule over
labelled targets. Acceptance means the candidate's content words (tokens minus the
function-word allowlist, minus the scenario's `allowed_additions`) equal the target's.
Intent is correct when the first candidate contains every `intent_keywords` token, or when
clarification was expected and given. Effort is a simulated patient policy: 1 tap to pick
an accepted candidate, answer or reject; otherwise one edit plus the two-step confirm.
These are proxies, and the report says so.

### D-046 Scenario format extensions
Beyond section 9: `split` (tune/test), `synthetic`, `intent_keywords`, `profile_terms`,
`phrasebook`. `gesture_tokens` are `{word, token, score}`. 23 scenarios (16 test, 7 tune),
built reproducibly by `evaluation/build_scenarios.py`. 4 of them are generated by
`make_fragments.py` (seeded). All are synthetic.

### D-047 Synthetic-speech WER and the script mismatch
WER uses ElevenLabs premade-voice TTS (in memory) -> Scribe batch, raw output. Measured on
the test split: corpus 11.82% over 25 utterances. Code-mixed is high because Scribe writes
romanised Hindi in Devanagari ("Mujhe thanda paani" -> "मुझे ठंडा पानी"). Raw WER is
kept, as the spec requires, and the report flags the cause. A transliteration-normalised
WER would be a separate, labelled metric.

### D-048 Ablation blocked by the Groq daily cap (status: incomplete)
The harness caps live calls, caches by prompt plus attempt number (so the spec's retry is a
real retry), stops at the first refusal, and marks every affected scenario `not_run`. It
never scores it as a pass or a fail. On this run Groq refused the first call
(tokens-per-day), so configs A / A+ / B / C are unmeasured except for scenarios that need
no LLM call. R0, WER and Scribe/TTS latency are measured. Prompt tuning (max 3 rounds,
tune split only) has not started, because it needs the same budget. To complete it:
`python evaluation/run_eval.py --reuse-wer` once the Groq budget is free. Completed
answers are cached, so a partial run is never lost.

## Frontend (2026-11-01)

### D-050 Frontend rebuilt as a real client
The supplied v0 zip was a single mock component: hard-coded candidates, timers in place of
turns, and 5 placeholder screens. It was rebuilt in its own visual language (paper, sage,
lavender) on live backend data only. Two backend read-only routes were added for it:
`GET /context` (labelled recent dialogue; the spec's "recent context visible") and
`GET /config` (non-secret timing values, so the silence countdown uses
`FRAGMENT_SILENCE_S` instead of a constant). Vercel Analytics was removed (R8 spirit: nothing
leaves the machine), and `ignoreBuildErrors` was dropped, so the build typechecks.

### D-051 Webcam in the browser = the backend's preview stream
R1 makes the CameraHub the only owner of the webcam, and on Windows a second opener would
fight over the device. So the UI never calls getUserMedia. It shows
`/camera/preview.mjpg` (encoded in memory, loopback only, needs camera consent), mirrored for
a natural self-view, with live tracking overlays. `DEBUG_PREVIEW=1` is now set in the dev
`.env` because the self-view is part of the patient UI. With it off, the UI says so and
tracking still runs.

### D-052 Same-origin proxy instead of CORS
`/backend/*` is rewritten by Next.js to 127.0.0.1:8765, which keeps D-009 (no CORS) intact.
The WS and the MJPEG image connect directly, and both are allowed for loopback origins.

### D-053 Verification of the frontend
`tsc` and `next build` are clean; the impeccable detector reports no findings. A Playwright
(installed Edge) click-through against a scripted backend (real app code; fake mic, Scribe,
LLM and TTS) passed with 0 console errors: switches -> partner context -> start -> live chips
with pauses -> done -> candidates with highlighted additions -> say -> spoken banner -> edit
-> review -> say -> phrasebook (edited x2) -> labelled context -> insights. Overflow was
measured at 390 / 820 / 1440 px. One real bug (grids sized to content on phones) was found
and fixed. With the real backend, the live webcam self-view and face tracking were seen in
the UI. Not verified in the browser: real ElevenLabs audio playback (the configured voices
need a paid plan, D-041) and the avatar iframe (no live Tavus, D-044).

## Voices (2026-11-01)

### D-054 Free-tier premade voices replace the library voices
Raju and Saavi (D-001, D-017) are library voices, which return 402 on the free plan (D-041).
They are replaced with two ElevenLabs premade voices, which the free plan allows over the API:
- `VOICE_ID_MALE=JBFqnCBsd6RMkjVDRZzb`: "George - Warm, Captivating Storyteller", `premade`,
  `labels.gender=male`, British English.
- `VOICE_ID_FEMALE=hpp4J3VqNfWAUOO0d1Us`: "Bella - Professional, Bright, Warm", `premade`,
  `labels.gender=female`, American English.
Verified on the account (tier `free`): `GET /v1/voices/{id}` for both, and
`POST /v1/text-to-speech/{id}` with `eleven_flash_v2_5` returned HTTP 200 audio for both in
`mp3_44100_128` (local fallback) and `pcm_16000` (echo). Both are English voices, so Hindi
output may carry an English accent; Flash v2.5 is multilingual but this was not listened to.
Neither is a clone of the patient, so output stays `voice_kind:"designed"`.

### D-055 Text echo verified live; avatar screen notices an ended room
One live probe (conversation `cb412ba9b3ce44e8`, `full` mode, `AVATAR_AUDIO_ECHO=0`): the
backend joined with daily-python and sent one `conversation.echo` text message, extra
`synthetic`/`disclosure` keys included. `conversation.replica.started_speaking` arrived
0.84 s later, speech lasted 3.0 s, and the Tavus transcript shows the replica said exactly
"Hello. This is a test message." This settles D-043's open question about extra keys and
one English sentence of D-044's verbatim test; the other 9 sentences (Hindi, mixed) and the
audio echo tier are still unverified.
A user report ("the avatar says nothing and doesn't hear me") was traced to: no message had
been confirmed (TTS never called), the patient's mic is off in the room by design (R4), and
the session (`c207c490210524b7`) had been ended through our end endpoint after 52 s while
the page kept showing its last video frame. The player now handles Daily's
`participant-left` / `left-meeting`, shows "session ended", and the screen re-reads
`/avatar/session` when the avatar health detail changes. The screen also says the avatar
does not listen, and links to My message.

### D-056 gpt-oss-20b, one-page hands-free mode, R2 relaxed to "confirm by not cancelling"
- `LLM_MODEL=openai/gpt-oss-20b` (user decision). The 120b model's free daily quota
  (200,000 TPD) was used up; 20b has its own quota. On first try 20b returned one candidate
  (rejected by the 2-3 rule) and a fragment list ("Water, cold."). `fusion_system.md` rule 6
  now says "always 2 or 3, never 1, complete sentences", and the section 8.6 worked example
  was added. Re-run on 3 packets: "wa, water, cold" after "Water or tea?" ->
  "I would like cold water, please." / "Cold water, please." (0.5 s); "I / want / go home"
  -> "I want to go home." (0.7 s); "okay / ... / beta garmi" -> yes/no clarification. This
  is prompt-tuning round 1 of 3 (section 9), on hand-made packets, not the eval test split.
- One page: the avatar panel (shared `AvatarPanel`) now sits beside the message composer,
  so speaking and watching the avatar happen on the same screen.
- **R2 change (user decision):** with Hands-free on (default, stored per browser), the best
  candidate is shown with a 3 s countdown and Cancel / Edit / Say now. If nothing is
  pressed, the frontend calls `/turn/confirm {choice_index: 0}`. The backend gate is
  unchanged: a one-time confirmation ID is still issued and required, and only candidates
  that passed the post-validator can be auto-said. Not auto-said: clarification questions,
  the LLM-unavailable fallback, and edited text (which still needs review).
- After a message is spoken, Hands-free opens a new PATIENT turn once the avatar and local
  audio are silent plus 1.2 s, so the avatar's voice is not captured as a fragment.

### D-057 Silence clock fix, replay, no auto re-listen, one avatar page
- **Bug:** the `FRAGMENT_SILENCE_S` clock reset on every energy-VAD frame above the noise
  floor (fan, typing, other voices) and on every Scribe final, empty ones included, and it
  reset at transcript *arrival* (~1 s after the person stopped). So the draft often never
  closed and the on-screen countdown jumped back. Now only a real fragment moves the clock:
  a non-empty speech final (stamped with the utterance's `end_ms`) or a gesture word.
  While an utterance is open or still being transcribed (`ScribeService.busy`), the draft is
  held open without moving the clock. The frontend countdown restarts on `fragment.added`
  only. Tests: noise does not restart, clock counts from utterance end, open utterance holds.
- **Replay:** `POST /turn/replay` (no body) says the last spoken PATIENT message again. The
  text comes from the finished turn, a fresh one-time confirmation ID is issued (R2), and it
  is not added to context or phrasebook again. Refused (409) while a turn is open or if
  nothing was spoken. UI: "Say again" on the spoken banner (device-audio messages replay
  locally, which costs no ElevenLabs characters).
- **Auto re-listen removed (user decision):** the 3 s auto-say countdown stays (toggle
  renamed "Auto-say in 3 s"); the mic no longer reopens after a message is spoken.
- **Avatar & voice page removed (user decision):** the avatar lives on My message only; the
  voice switch remains in the top bar.

### D-058 One consistent decision view; simpler fallback buttons; lip download still blocked
- gpt-oss-20b sometimes returns candidates *and* `clarification_required` with a question.
  The page then showed a yes/no box and no countdown, and other times only the countdown.
  Now: whenever there are candidates, the view is always the same (best sentence with the
  auto-say countdown, other options below); the yes/no question is shown only when there
  are no candidates. A thumbs gesture answers the question only in that case too (tested).
  A message made only of lip hints is never auto-said (R5).
- The no-candidate panel has two buttons, **Edit** and **Say** (plus a small "Discard and
  start again" link). Say speaks the text already shown on screen: the tap answers the
  backend's show-back step with the same exact text. If only fillers were heard ("Mm-hmm"),
  it says so and Say is disabled.
- Lip reading: all three Auto-AVSR VSR checkpoints still return Google Drive "Quota
  exceeded" (2026-11-01). Not worked around (D-025). Manual download while signed in to
  Google, saved as `assets/lip/vsr.pth`, enables it after a backend restart.
