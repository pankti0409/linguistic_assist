# Sampark: the complete flow

Built from actual source and non-secret configuration, 1 November 2026. This is an architecture snapshot, not a claim that every optional service is currently active.

**In one sentence:** collect small expressions → add conversation context → suggest complete wording → validate it → approve the exact text → speak it.

**Open the visual guide:** [Interactive HTML](sampark-flow.html) · [Standalone SVG](sampark-flow.svg).

## Read the colours

- **Green — open-source libraries:** tools we use to build the app and process inputs.
- **Blue — hosted services:** external APIs or remotely deployed models.
- **Amber — open-weight model on a hosted API:** gpt-oss-20b served by Groq.
- **Lilac — our code:** permission gates, fragments, context, validation, and confirmation.
- **Grey — browser APIs:** standards such as browser audio; not additional model dependencies.

An open-source SDK does not make its cloud service open-source. A model can have public weights while this app still calls it remotely.

## Main flow

```mermaid
flowchart TD
  UI["React app: choose inputs and permissions"] --> GATE["Our consent and turn controller"]
  GATE --> MIC["sounddevice: laptop microphone"]
  GATE --> CAM["OpenCV: one shared webcam"]
  MIC --> STT["ElevenLabs Scribe v2: audio to words — hosted"]
  CAM --> HAND["MediaPipe: recognize hand gestures — local"]
  CAM --> FACE["MediaPipe: track face and mouth — local"]
  HAND --> MAP["Our mapping: stable gesture to word"]
  FACE --> LIP["Auto-AVSR on HF Space: lip clip to hint — hosted"]
  STT -->|Patient turn| DRAFT["Our FragmentCollector: raw + cleaned draft"]
  STT -->|Partner turn| CONTEXT["Partner question: recent dialogue context"]
  MAP --> DRAFT
  LIP --> DRAFT
  DRAFT --> PACKET["EvidencePacket: text and derived signals"]
  CONTEXT --> PACKET
  PERSONAL["Optional local phrasebook + profile terms"] --> PACKET
  PACKET --> LLM["gpt-oss-20b: complete sentences — hosted by Groq"]
  LLM --> VALIDATE["Pydantic + our rules: reject unsupported additions"]
  VALIDATE -->|Unclear| ASK["Clarify or edit"]
  ASK --> PACKET
  VALIDATE --> REVIEW["Review sentence; optional 3-second auto-say"]
  REVIEW --> CONFIRM["One-time confirmation ID tied to exact text"]
  CONFIRM --> TTS["ElevenLabs Flash v2.5: confirmed text to audio"]
  TTS --> AVATAR["Tavus + Daily: avatar echo"]
  CONFIRM -. Text echo fallback .-> AVATAR
  AVATAR --> PLAYER["Daily.js: receive avatar video/audio"]
  TTS -. No avatar or failed avatar .-> AUDIO["Browser audio + subtitles"]
  DRAFT -. WebSocket: draft.updated .-> UI
```

## What each stage means

| Stage | Plain English | Actual implementation |
|---|---|---|
| Choose | Select speech, gestures, or lip hints and permit their devices. | ConsentRegistry; TurnMachine; frontend setup/composer |
| Hear | Record the selected microphone and recognize words after a pause. | sounddevice → our Segmenter → hosted Scribe v2 |
| See gestures | Recognize a supported hand label and map it to a configured word. | OpenCV CameraHub → MediaPipe → our Debouncer/Lexicon |
| See lips | Track the face and turn an eligible clip into a weak text hint. | MediaPipe Face → HFSpaceLipReader / optional local AutoAvsrReader |
| Collect | Keep the pieces in order and display raw and cleaned versions. | FragmentCollector; speech.final / fragment.added / draft.updated |
| Add context | Include the partner’s question and optional personal vocabulary. | Conversation; Phrasebook; ProfileTerms |
| Suggest | Produce whole sentences or ask what was meant. | FusionService → Groq → gpt-oss-20b |
| Check | Reject malformed responses or unsupported added words. | Pydantic; coverage checks; post_validate |
| Choose | Select, edit, or cancel; optional auto-say offers 3 seconds to cancel. | Decision; AutoSay; backend edit show-back |
| Approve | Bind the exact final text to a single-use, expiring ID. | ConfirmationRegistry |
| Speak | Generate voice and try avatar output, then local audio fallback. | Flash v2.5 → Tavus/Daily or HTMLAudioElement |

## Component inventory: where, what, and status

Includes every direct frontend/backend dependency group, named optional model/media tooling, and our main orchestration modules. It is not an exhaustive transitive dependency SBOM. “Configured” is not proof of successful inference. Licence labels come from repository records or installed package metadata unless an official source is linked below.

| Area | Component | Type | Used when | What it does | Code location | Licence / terms |
|---|---|---|---|---|---|---|
| Experience | React + React DOM | Open-source | Live | Build and update the six application screens. | f_new/src/App.tsx; f_new/src/components/ps16-app.tsx | MIT |
| Experience | TypeScript | Open-source | Build-time | Checks frontend data shapes and catches coding errors. | f_new/tsconfig.json; f_new/src/lib/types.ts | Apache-2.0 |
| Experience | Vite + React plugin | Open-source | Dev/build | Serves the frontend on 5173, builds production files, and proxies /backend requests to Python. | f_new/vite.config.ts | MIT |
| Experience | Tailwind CSS + @tailwindcss/vite | Open-source | Build-time | Turns styling utilities and theme tokens into the app’s CSS. | f_new/src/app-theme.css; f_new/vite.config.ts | MIT |
| Experience | Motion | Open-source | Live | Animates screen transitions, fragments, and confirmation views; honors reduced motion. | f_new/src/components/ps16-app.tsx; f_new/src/components/screens/message.tsx | MIT |
| Experience | Lucide React | Open-source | Live | Provides microphone, camera, permission, and navigation icons. | f_new/src/components/ | ISC |
| Experience | Sonner | Open-source | Live | Shows success messages and actionable errors. | f_new/src/lib/backend.tsx; f_new/src/components/ps16-app.tsx | MIT |
| Experience | clsx + tailwind-merge | Open-source | Live | Combines conditional CSS classes and resolves conflicting Tailwind classes. | f_new/src/lib/utils.ts | MIT |
| Experience | tw-animate-css | Open-source | Build-time | Supplies reusable CSS animation utilities. | f_new/src/app-theme.css | MIT |
| Experience | Base UI + class-variance-authority | Open-source | Included wrapper | Accessible button primitive and variant helper in the generic button wrapper; active screens mainly use the custom UI kit. | f_new/src/components/ui/button.tsx | MIT / Apache-2.0 |
| Experience | @types/react + @types/react-dom | Open-source | Build-time | React type declarations used by TypeScript. | f_new/package.json | MIT |
| Backend | FastAPI + Starlette | Open-source | Live / local | Expose permission, turn, voice, context, avatar, and WebSocket endpoints on 8765. | app/main.py; app/api/ | MIT / BSD-3-Clause |
| Backend | Uvicorn + websockets | Open-source | Live / local | Run the Python web server and carry live events to the browser. | app/main.py; app/api/ws.py | BSD-3-Clause |
| Backend | Pydantic | Open-source | Live / local | Validate API requests, evidence packets, candidates, and model JSON. | app/schemas.py; app/services/fusion.py | MIT |
| Backend | python-dotenv | Open-source | Startup / local | Reads local configuration and API credentials from .env. Secrets are not sent to the frontend. | app/config.py | BSD-3-Clause |
| Backend | HTTPX | Open-source | Live | Makes external HTTP requests, including Tavus operations and service checks. | app/services/avatar.py; scripts/check_env.py | BSD-3-Clause |
| Input | sounddevice / PortAudio | Open-source | Live / local | Records the selected laptop microphone at 16 kHz mono PCM. Current device: MacBook Air Microphone. | app/services/scribe.py | MIT / see PortAudio distribution |
| Input | NumPy | Open-source | Live / local | Computes audio levels and manipulates image arrays and landmark coordinates. | app/services/scribe.py; app/services/face.py; app/services/lip.py | BSD-3-Clause |
| Input | OpenCV / opencv-contrib-python | Open-source | Live / local | Owns webcam capture through CameraHub; prepares preview images and lip clips. | app/services/camera.py; app/services/lip.py | Apache-2.0 |
| Input | MediaPipe Face Landmarker | Open-source toolkit + separate model asset | Live / local | Finds face landmarks, head direction, and mouth movement. It does not produce lip-reading sentences by itself. | app/services/face.py; assets/face_landmarker.task | Toolkit Apache-2.0; model-asset licence not confirmed in repository audit |
| Input | MediaPipe Gesture Recognizer | Open-source toolkit + separate model asset | Live / local | Recognizes supported hand labels, then custom rules map stable labels to words such as yes, no, or wait. | app/services/gesture.py; calibration/default.json | Toolkit Apache-2.0; model-asset licence not confirmed in repository audit |
| Recognition | ElevenLabs SDK | Open-source client | Live | Connects Python to ElevenLabs speech recognition and voice generation. The SDK licence does not make the hosted models open-source. | app/services/scribe.py; app/services/tts.py | MIT |
| Recognition | ElevenLabs Scribe v2 | Hosted service | Live / cloud | Transcribes microphone audio segments into words after pauses. Model ID: scribe_v2. | app/services/scribe.py | Hosted service terms |
| Recognition | gradio-client | Open-source client | Configured / cloud connector | Uploads an eligible lip clip to the configured Hugging Face Space and calls /predict. | app/services/lip.py; requirements.txt | Apache-2.0 client; hosted model has separate terms |
| Recognition | Hugging Face Space: marshal-yash/vsr_trlrs3vox2_base | Hosted deployment of a research lip-reading model | Current configured path | Converts a short greyscale face/mouth video into a weak text hint; cloud processing, not a local checkpoint. | app/config.py; app/services/lip.py | Hosted deployment and underlying checkpoint terms apply |
| Recognition | Auto-AVSR | Open-source research code + separate pretrained weights | Optional local path | Alternative to the Space: aligns and crops mouth frames, then decodes visual speech locally when source and checkpoint are installed. | app/services/lip.py; requirements-lip.txt | Code Apache-2.0; this project restricts the selected checkpoint to non-commercial research |
| Recognition | PyTorch + TorchVision + TorchAudio | Open-source | Optional local path | Tensor computation and model/audio/video support for local Auto-AVSR. Not needed for the current hosted path. | requirements-lip.txt; app/services/lip.py | Component-specific distribution licences |
| Recognition | PyTorch Lightning + SentencePiece | Open-source | Optional local path | Load/run Auto-AVSR’s model module and support text tokenization. | requirements-lip.txt; app/services/lip.py | Apache-2.0 |
| Recognition | PyAV + scikit-image | Open-source | Optional local path | Video/image processing dependencies for local Auto-AVSR. | requirements-lip.txt | BSD-3-Clause; PyAV FFmpeg build terms also apply |
| Understanding | Groq SDK | Open-source client | Live | Sends the text evidence packet to the hosted language model. | app/services/fusion.py | Apache-2.0 |
| Understanding | gpt-oss-20b | Open-weight model | Current model / cloud via Groq | Uses fragments and context to propose complete sentences or a clarifying question. It is hosted remotely in this project. | app/config.py; app/services/fusion.py | Apache-2.0 model release; see official model card |
| Understanding | Groq inference API | Hosted service | Live / cloud | Runs the configured gpt-oss-20b model and returns structured JSON. Groq is the host; gpt-oss is the model. | app/services/fusion.py | Hosted service terms |
| Output | ElevenLabs Flash v2.5 | Hosted service | Live / cloud | Turns the confirmed sentence into synthetic voice audio. Model ID: eleven_flash_v2_5. | app/services/tts.py | Hosted service terms |
| Output | Tavus | Hosted service | Optional / needs session | Makes an AI avatar say the confirmed sentence using an echo message. The avatar is a relay, not the sentence generator. | app/services/avatar.py | Hosted service terms |
| Output | daily-python + @daily-co/daily-js | Open-source clients | When avatar is used | Python joins and sends controlled echo messages; the browser receives the avatar’s real-time room video/audio. | app/services/avatar.py; f_new/src/components/avatar-player.tsx | BSD-2-Clause; Daily service has separate terms |
| Browser APIs | WebSocket + HTMLAudioElement | Browser standards | Live | WebSocket delivers draft/status events; browser audio plays the local voice fallback. | f_new/src/lib/backend.tsx; app/api/ws.py | Browser APIs; not additional Python/npm dependencies |
| Browser APIs | WebGL + Canvas + HTML video | Browser standards | Landing only | Composite the existing video, title lettering, and foreground mask. They do not perform patient recognition. | f_new/src/HeroScene.tsx | Browser APIs |
| Browser APIs | SpeechSynthesis | Browser API | Landing preview only | Reads a sample sentence on explicit click using the device voice. Separate from the real ElevenLabs app pipeline. | f_new/src/SootheStudio.tsx | Browser-provided API/voices |
| Our logic | ConsentRegistry + TurnMachine | Project code | Live / local | Gate inputs by permission and coordinate capture, suggestion, clarification, editing, and speaking states. | app/core/consent.py; app/core/turn_machine.py | Repository MIT |
| Our logic | FragmentCollector + deterministic cleanup | Project code | Live / local | Keep word order and pauses; flag repeats, fillers, stutters, and weak evidence; produce the cleaned draft. | app/core/fragments.py | Repository MIT |
| Our logic | Conversation + Phrasebook + ProfileTerms | Project code | Live / local | Keep recent speaker-labelled context in memory; optionally save personalized words/sentences to local JSON after consent. | app/core/conversation.py; app/core/phrasebook.py; data/ | Repository MIT |
| Our logic | FusionService + evidence validator | Project code + Pydantic | Live / local | Build model input, check output coverage, and reject unsupported added words. This is orchestration, not a separate trained model. | app/services/fusion.py; app/schemas.py | Repository MIT + Pydantic MIT |
| Our logic | ConfirmationRegistry | Project code | Live / local | Issue an expiring, one-time ID bound to the selected text before speech output can run. | app/core/confirmation.py | Repository MIT |
| Our logic | EventBus + HealthRegistry + Metrics | Project code | Live / local | Publish fragment/draft events, report availability, and record stage timings and counters. | app/core/events.py; app/core/health.py; app/core/timing.py | Repository MIT |
| Verification | pytest + fake adapters | Open-source test runner + project code | Tests only | Test capture, permissions, fragments, model-output checks, confirmation, and fallback without using live devices or APIs. | tests/; app/adapters/fakes.py | pytest MIT; adapters repository MIT |
| Verification | Playwright | Open-source | Browser tests | Check navigation, responsive layouts, video controls, themes, and browser errors. | f_new/scripts/check-browser.mjs; f_new/scripts/verify-in-app.mjs | Apache-2.0 |
| Verification | Ruff | Open-source | Development only | Checks Python code style and common mistakes. | requirements-dev.txt; pyproject.toml | MIT |
| Verification | Custom evaluation harness | Project code | Evaluation only | Measures word error rate, intent proxies, latency, and different input combinations. Synthetic scenarios are labelled. | evaluation/ | Repository MIT |
| Asset preparation | rembg / U²-Net + Pillow + SciPy | Open-source tools + separate model | Offline asset preparation | Create foreground masks for the supplied landing video. Not the user’s live camera or lip-reading pipeline. | f_new/scripts/prepare-media.py | Check tool/model licences in their distributions |
| Asset preparation | FFmpeg + OpenCV | Open-source tools | Offline asset preparation | Encode the packed hero video; OpenCV removes a fixed symbol from supplied frames. No patient-media processing in these scripts. | f_new/scripts/prepare-media.py; f_new/scripts/remove-symbol.py | FFmpeg build-dependent LGPL/GPL; OpenCV Apache-2.0 |
| Asset preparation | DM Sans + Cormorant Garamond | Open font assets | Landing/app assets | Self-hosted typography; local font licence files ship with the frontend. | f_new/public/fonts/ | See bundled OFL licence files |

## Current model choices

| Task | Current model / tool | Where it runs |
|---|---|---|
| Speech recognition | ElevenLabs `scribe_v2` | ElevenLabs cloud |
| Sentence reconstruction | `openai/gpt-oss-20b` | Groq cloud |
| Face/mouth tracking | MediaPipe `face_landmarker.task` | Laptop |
| Gesture recognition | MediaPipe `gesture_recognizer.task` | Laptop |
| Lip recognition | HF Space `marshal-yash/vsr_trlrs3vox2_base` | Hosted Space; optional local Auto-AVSR alternative |
| Voice generation | ElevenLabs `eleven_flash_v2_5` | ElevenLabs cloud |
| Avatar | Configured Tavus persona/replica, activated by a session | Tavus / Daily hosted room |

The currently configured input is **MacBook Air Microphone**. Backend uses **8765**; Vite frontend uses **5173**. Camera target is 30 fps; face/gesture processing target is 15 fps. These are configured targets, not measured guarantees. The lip buffer is 4 seconds; the fragment-silence setting is 6 seconds. Speech segmentation waits roughly 700 ms of quiet to close an utterance before batch recognition. Pressing “I’m done” also flushes the final utterance.

## Partner example

1. **Partner turn:** “Would you like water or tea?” → same microphone and Scribe → recent labelled context.
2. **Patient turn:** “water … cold” → two pieces in the draft.
3. **Model:** uses those pieces and the partner’s question to suggest a sentence such as “I would like cold water, please.”
4. **Validation + choice:** check allowed additions; review or use the enabled cancelable auto-say window.
5. **Output:** confirmed wording becomes voice; the avatar can relay it if a session is available.

Speaker identity is chosen by the turn; there is no automatic speaker diarization. Gestures use configured labels, not full sign-language translation. Mouth movement is not emotion inference or reliable standalone meaning.

## What stays local and what is sent out

| Destination | What it receives | Why |
|---|---|---|
| Local microphone path | PCM audio in memory | Capture and pause segmentation |
| ElevenLabs Scribe | Audio segments | Speech-to-text |
| Local MediaPipe | Webcam frames | Gesture/face tracking |
| Hosted HF lip Space | Encoded greyscale video clip, when lip recognition is used | Visual speech inference |
| Groq | Text fragments, cleaned words, context, and derived evidence metadata | Sentence suggestions |
| ElevenLabs voice API | Confirmed text and configured voice selection | Synthetic speech |
| Tavus / Daily | Avatar session and approved text/audio echo | Avatar delivery |
| Local personal vocabulary files | Profile terms and phrasebook entries, with permission | Personalization |

**Important implementation detail:** the hosted lip path currently writes an MP4 to a temporary file, uploads it, and deletes it in `finally`. Therefore the actual implementation is not “raw media never leaves the laptop” or “all raw media is memory-only.” The local checkpoint path is different. Existing older README claims should not be used as the data-flow description.

## Confirmation and fallback details

- Permission gates protect microphone, camera, avatar, personalization, and voice cloning independently.
- The browser can optionally confirm an eligible suggestion after a cancelable 3-second countdown. This still calls the backend confirmation route; it is not an always-manual-only flow.
- Lip-only evidence never triggers auto-say. Edited text has a review/show-back step.
- Invalid, expired, reused, or text-mismatched confirmation IDs cannot unlock output.
- Output order: **ElevenLabs audio → Tavus audio echo**, then **Tavus text echo**, then **local ElevenLabs audio + subtitles** if avatar output is unavailable. An earlier successful tier prevents later tiers from also speaking.
- Normal backend microphone input does not go through the avatar room. The browser’s avatar-room camera and microphone stay off.
- Failed model calls do not create fake fragments; health/error feedback explains the failure.

## Landing page is a separate path

`SootheStudio` uses labelled local examples and optional browser SpeechSynthesis; it does not capture a microphone or run Scribe/Groq. `HeroScene` uses WebGL, Canvas, and the supplied video; it is presentation, not the live avatar. Offline video-preparation tools (rembg/U²-Net, Pillow, SciPy, OpenCV, FFmpeg) create those design assets and are not the live communication pipeline.

## Licensing distinctions and sources

- [Official gpt-oss-20b model card](https://huggingface.co/openai/gpt-oss-20b): open-weight model released under Apache-2.0. In this app it is hosted through Groq.
- [Auto-AVSR source repository](https://github.com/mpc001/auto_avsr): research code; pretrained checkpoint/dataset terms must be treated separately. This project’s licence notes restrict the selected checkpoint to non-commercial research.
- [Repository licence inventory](../LICENSES.md): existing audit; some version/status statements predate the current configuration.
- [Dependency manifests](../../requirements.txt), [optional lip extras](../../requirements-lip.txt), [frontend manifest](../../f_new/package.json).
- MediaPipe toolkit licence and downloaded model-asset licences are distinct; the latter are not confirmed in the repository’s current licence audit.
- Hosted API/service terms are separate from SDK licences. This guide is a technical dependency map, not a new licence audit.
