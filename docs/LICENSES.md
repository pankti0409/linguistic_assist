# Third-party licences

Entries are completed as each component is integrated. Each one gets verified against its
source at that milestone. Nothing below is assumed.

| Component | Used for | Licence | Verified at | Status |
|-----------|----------|---------|-------------|--------|
| FastAPI | HTTP/WS server | MIT | M0 | in use |
| websockets | WS server/client (via uvicorn[standard]) | BSD-3-Clause | M1 | in use |
| Pydantic | schemas | MIT | M0 | in use |
| Uvicorn | ASGI server | BSD-3-Clause | M0 | in use |
| python-dotenv | config | BSD-3-Clause | M0 | in use |
| NumPy | arrays | BSD-3-Clause | M0 | in use |
| OpenCV (opencv-contrib-python 5.0) | camera / video | Apache 2.0 (package metadata) | M1 | in use |
| MediaPipe 1.2.0 (library) | face / gesture | Apache 2.0 (package metadata) | M1 | in use |
| MediaPipe `face_landmarker.task`, `gesture_recognizer.task` | model bundles | per each model card; not yet checked | M1 | in use, licence to confirm before M7 |
| Auto-AVSR code (mpc001/auto_avsr @182b628) | lip reading | Apache 2.0 (repo LICENSE) | M3 | in use (third_party, not redistributed) |
| PyTorch 2.14.1 / torchvision / torchaudio (CPU) | lip extra | torch metadata: "Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND ..." (bundled components) | M3 | in use (optional) |
| pytorch-lightning, sentencepiece, av (PyAV), scikit-image | lip extra | Apache 2.0, Apache 2.0, BSD-3-Clause, BSD-3-Clause | M3 | in use (optional) |
| Auto-AVSR VSR checkpoint `vsr_trlrs3vox2_base` | lip reading | trained on LRS3 (TED, non-commercial research only) + VoxCeleb2; **use is limited to non-commercial research** (user decision, 2026-10-31) | M3 | not yet downloaded (Drive quota, D-025) |
| ElevenLabs, Groq, Tavus | hosted services | provider terms of service | M4/M5 | pending |
