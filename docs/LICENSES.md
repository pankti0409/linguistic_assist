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
| Auto-AVSR code | lip reading | to verify | M3 | pending |
| Auto-AVSR checkpoints and training datasets (LRS3 etc.) | lip reading | to verify; dataset terms may restrict use | M3 | pending |
| ElevenLabs, Groq, Tavus | hosted services | provider terms of service | M4/M5 | pending |
