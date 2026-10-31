# linguistic_assist: PS-16 communication assistant backend

A local backend for people who cannot speak reliably. It collects **fragments** of a
message across long pauses (broken speech from the laptop mic, hand-gesture words and
lip-movement hints from the laptop webcam). It cleans them, proposes 2-3 complete
sentences using the conversation partner's last question and the patient's own vocabulary,
and speaks **only the sentence the patient confirms**: through a Tavus avatar, or as
local audio with subtitles.

> Assistive proof of concept. Not a diagnostic tool, not clinically validated. The build
> spec is [CLAUDE.md](CLAUDE.md); every decision and known gap is in
> [docs/DECISIONS.md](docs/DECISIONS.md).

## What it guarantees

| Rule | How |
|---|---|
| Nothing is spoken without confirmation (R2) | Speech output takes only a one-time, sha256-bound `confirmation_id` and reads the text from the registry. No route speaks text from a request body. Tested. |
| Consent first (R3) | Camera, microphone, avatar and personalisation each start only after `POST /consent`. Camera processing runs exactly while camera consent is held. |
| No raw media leaves the machine (R4, R8) | Only text evidence packets go to Groq. Frames and audio stay in memory and are never written to disk. The Tavus room is receive-only for the patient. |
| No invented words (R10) | A code post-validator drops any candidate that adds a word not traceable to the fragments, the partner's lines, profile terms or the phrasebook (beyond a function-word list). Added words are shown. |
| Disclosure (R9) | Every avatar and synthetic-voice payload carries `synthetic: true`, `disclosure: "AI avatar"`. |
| Local only | Binds to `127.0.0.1`, checks Host (DNS rebinding) and Origin (`/ws`), and supports an optional `ACCESS_TOKEN`. |

## Requirements

- Python **3.10 or 3.11**, git, a laptop webcam and mic.
- Accounts: ElevenLabs (Scribe + TTS), Groq, Tavus (optional; without it the output is local audio).
- Tested on **Windows 11** only. macOS and Linux use the same steps (see `run.sh`), but
  they have not been tested.

## Install

Windows (PowerShell):

```powershell
git clone <repo-url> linguistic_assist; cd linguistic_assist
py -3.10 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
copy .env.example .env      # then fill in the keys
.\.venv\Scripts\python scripts\download_models.py
.\.venv\Scripts\python scripts\check_env.py
```

macOS / Linux:

```bash
git clone <repo-url> linguistic_assist && cd linguistic_assist
python3.10 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
cp .env.example .env        # then fill in the keys
.venv/bin/python scripts/download_models.py
.venv/bin/python scripts/check_env.py
```

`check_env.py` opens the webcam for one frame and the mic for 0.2 s (`--no-camera`,
`--no-mic` skip them). It makes cheap read-only calls to each service, checks that each
voice slot's ElevenLabs gender label matches the slot, and prints PASS/FAIL/SKIP.

### Optional: lip reading (Auto-AVSR, non-commercial research use only)

```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-lip.txt
git clone https://github.com/mpc001/auto_avsr third_party/auto_avsr
python scripts/download_lip_model.py   # may fail with a Google Drive quota; retry later
```

Without a checkpoint, lip reading reports `unavailable` and only `mouth_activity` is used.

## Configure (`.env`)

| Key | Meaning |
|---|---|
| `ELEVENLABS_API_KEY`, `GROQ_API_KEY`, `TAVUS_API_KEY` | service keys |
| `VOICE_ID_MALE`, `VOICE_ID_FEMALE`, `VOICE_DEFAULT` | the two output voices; switch at runtime with `PUT /voice`. **On the ElevenLabs free plan only premade voices work** (library voices return 402). |
| `TAVUS_PERSONA_ID`, `TAVUS_REPLICA_ID` | Tavus PAL id and face id (Tavus renamed persona -> PAL, replica -> face) |
| `TAVUS_PIPELINE_MODE` | `full` or `echo` |
| `SIMULATE=1`, `CAMERA_SOURCE` | run everything offline on a video file plus labelled fakes |
| `ACCESS_TOKEN` | optional; then every call except `/health` needs `X-PS16-Token` (WS: `?token=`) |
| `FRAGMENT_SILENCE_S`, `FRAGMENT_MAX_S`, ... | timing constants from CLAUDE.md section 8.10 |

## Run

```powershell
.\scripts\run.ps1            # Windows
./scripts/run.sh             # macOS / Linux
```

The server listens on `http://127.0.0.1:8765` (`PORT` to change).

## Use it (minimal flow)

```bash
B=http://127.0.0.1:8765
curl -X POST $B/consent -H 'content-type: application/json' -d '{"purpose":"microphone"}'
curl -X POST $B/consent -H 'content-type: application/json' -d '{"purpose":"camera"}'   # webcam + gestures
# partner asks a question
curl -X POST $B/turn/start -H 'content-type: application/json' -d '{"speaker":"PARTNER"}'
curl -X POST $B/turn/end
# patient answers in fragments, with pauses; the draft stays open across them
curl -X POST $B/turn/start -H 'content-type: application/json' -d '{"speaker":"PATIENT","modalities":["speech","gesture"]}'
curl -X POST $B/turn/end          # -> candidates with added_words, or a yes/no question
curl -X POST $B/turn/confirm -H 'content-type: application/json' -d '{"turn_id":"<id>","choice_index":0}'
```

Watch events live: `python scripts/watch_events.py` (or connect any frontend to `WS /ws`).
Main routes: `/health`, `/consent`, `/turn/{start,end,confirm,reject,clarify}`, `/voice`,
`/gesture/{lexicon,calibrate}`, `/profile/terms`, `/phrasebook`, `/avatar/session`,
`/metrics`. Interactive docs: `http://127.0.0.1:8765/docs`.

## Test and evaluate

```bash
python -m pytest            # offline; real webcam / mic / APIs are never touched
python -m ruff check .
python evaluation/run_eval.py --wer   # ablation R0/A/A+/B/C + synthetic WER -> evaluation/report.md
```

The report contains measured numbers only. Scenarios are synthetic.

## Current status (see docs/DECISIONS.md)

Working and verified live on the dev laptop: webcam + face tracking (~15 results/s),
gesture tokens, Scribe on synthetic speech and the real mic, local ElevenLabs output, and
the full confirmation flow.

Not yet verified live:
- Groq reconstruction (daily token cap, D-028/D-048).
- Avatar speech and the verbatim test (no live Tavus calls by decision, D-044).
- Lip text (checkpoint download blocked, D-025).
- `mouth_activity` thresholds and the speech segmenter on real speech (D-012, D-031).
