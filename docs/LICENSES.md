# Third-party licences

Each entry was checked at the milestone shown: Python packages against their installed
package metadata (`importlib.metadata`), repositories against their LICENSE file, and
hosted services against their own terms. "Not confirmed" means it could not be
verified here; it is not an assumption that the item is fine.

## Python packages (core install)

| Package (version checked) | Used for | Licence (package metadata) | Checked |
|---|---|---|---|
| fastapi 0.162 | HTTP / WS server | MIT | M0 |
| starlette 1.7.0 | ASGI toolkit (via FastAPI) | BSD-3-Clause | M7 |
| uvicorn 0.54 | ASGI server | BSD-3-Clause | M0 |
| websockets 16.1.1 | WS (via uvicorn[standard]) | BSD-3-Clause | M1 |
| pydantic 2.14 | schemas | MIT | M0 |
| python-dotenv 1.2 | config | BSD-3-Clause | M0 |
| httpx 0.28.1 | REST calls (Tavus, scripts) | BSD-3-Clause | M7 |
| numpy 2.2.6 | arrays | BSD-3-Clause | M0 |
| opencv-contrib-python 5.0.0.93 | camera / video | Apache 2.0 | M1 |
| mediapipe 1.2.0 | face / gesture | Apache 2.0 | M1 |
| elevenlabs 2.75.0 | Scribe + TTS SDK | MIT | M4 |
| groq 1.7.0 | LLM SDK | Apache-2.0 | M4 |
| sounddevice 0.5.6 | laptop mic | MIT | M4 |
| daily-python 0.36.0 | backend joins the Tavus room | BSD 2-Clause | M5 |

Dev only: pytest 9.2 (MIT), ruff 0.17 (MIT), httpx2 2.14 (BSD-3-Clause).

## Optional lip-reading extra (`requirements-lip.txt`)

| Component | Licence | Notes |
|---|---|---|
| Auto-AVSR code, mpc001/auto_avsr @ 182b628 | Apache 2.0 (repo LICENSE) | Cloned into `third_party/`, not redistributed |
| torch 2.14.1 (CPU) | "Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause ..." (bundled components) | |
| torchvision 0.29.2 / torchaudio 2.11.1 | BSD | |
| pytorch-lightning, sentencepiece | Apache-2.0 | |
| av (PyAV), scikit-image | BSD-3-Clause | |
| **VSR checkpoint `vsr_trlrs3vox2_base`** | Trained on LRS3 (TED; non-commercial research only) and VoxCeleb2. **Use is limited to non-commercial research** (user decision, 2026-10-31). | Not downloaded yet: Google Drive quota (D-025) |

## Model files

| Asset | Licence | Status |
|---|---|---|
| `face_landmarker.task`, `gesture_recognizer.task` (MediaPipe "latest", SHA-256 in D-010) | **Not confirmed.** The guide pages state no model licence; it is in the per-component model cards (PDFs linked from the guides). The pages' own text is CC BY 4.0 and their code samples Apache 2.0, which says nothing about the models. | Read the model cards before any distribution |

## Hosted services (terms of service, not open-source licences)

| Service | Used for | Notes from this build |
|---|---|---|
| ElevenLabs (Scribe v2, Flash v2.5) | speech in / speech out | On the free plan, library voices are refused via the API (402). Only premade voices work (D-041). |
| Groq (`openai/gpt-oss-120b`) | reconstruction | `on_demand` tier: 200k tokens/day, shared by everything that uses the key (D-028) |
| Tavus (PALs / faces, CVI) | avatar | Not called live during the build (D-044) |

The project's own code is under the repository's `LICENSE` (MIT, © 2026 Pankti Akbari).
