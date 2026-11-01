"""LipService (section 8.4): mouth clips -> Auto-AVSR -> low-reliability lip text hint.

Frames come from the CameraHub at camera rate, are converted to greyscale on arrival
(Auto-AVSR's VideoTransform greyscales them anyway), and are held in a ~LIP_BUFFER_S ring
buffer in memory only (R8). Landmarks come from FaceService. At evaluation the clip is
resampled to 25 fps (the rate of Auto-AVSR's training data) and handed to Auto-AVSR's own
`VideoProcess` (affine alignment to its mean face, 96x96 mouth crop, temporal smoothing,
interpolation of frames without landmarks), then to its `VideoTransform("test")` and
`ModelModule`. None of that is reimplemented here (D-022).

The only bridge written here maps FaceLandmarker's mesh to the 4 points Auto-AVSR's own
MediaPipe detector produces: right eye, left eye, nose tip, mouth centre.

HuggingFace Space backend (D-050)
----------------------------------
When ``LIP_HF_SPACE`` is set (e.g. ``"marshal-yash/vsr_trlrs3vox2_base"``),
``load_reader()`` returns a ``HFSpaceLipReader`` instead of ``AutoAvsrReader``.
The HF backend:

1. Encodes the greyscale clip frames to a temporary MP4 at 25 fps using OpenCV.
2. Calls the Gradio ``/predict`` endpoint via ``gradio_client.Client``.
3. Deletes the temp file and returns the predicted text as ``LipEvidence``.

No checkpoint file or Auto-AVSR source tree is needed in this mode.
"""

from __future__ import annotations

import logging
import math
import sys
import threading
from collections import deque
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path

import numpy as np

from app.config import ROOT, Settings
from app.core.consent import ConsentRegistry
from app.core.events import EventBus
from app.core.health import HealthRegistry
from app.schemas import LipEvidence
from app.services.camera import CameraHub, Frame
from app.services.face import FaceObservation, FaceService

log = logging.getLogger(__name__)

AVSR_DIR = ROOT / "third_party" / "auto_avsr"
TARGET_FPS = 25.0  # LRS3 / VoxCeleb2 frame rate the checkpoints were trained on
MATCH_TOL_MS = 45  # a face observation belongs to a frame within this distance
MAX_YAW_FRACTION = 0.2  # D-023: more than 20% of frames over LIP_MAX_YAW_DEG -> insufficient
MAX_MISSING_FRACTION = 0.2  # section 8.4: face missing for over 20% of frames


# --- evidence rules -----------------------------------------------------


@dataclass(frozen=True)
class Clip:
    frames: list[np.ndarray]  # greyscale uint8, resampled to TARGET_FPS
    landmarks: list[np.ndarray | None]  # (4, 2) pixel coordinates, or None
    missing_fraction: float
    yaw_over_fraction: float


def resample_times(t0: int, t1: int, fps: float = TARGET_FPS) -> list[float]:
    step = 1000.0 / fps
    n = int(math.floor((t1 - t0) / step)) + 1
    return [t0 + k * step for k in range(max(0, n))]


def nearest(ts_sorted: Sequence[int], t: float) -> int:
    import bisect

    i = bisect.bisect_left(ts_sorted, t)
    if i == 0:
        return 0
    if i >= len(ts_sorted):
        return len(ts_sorted) - 1
    return i if ts_sorted[i] - t < t - ts_sorted[i - 1] else i - 1


def build_clip(
    frames: Sequence[tuple[int, np.ndarray]],
    observations: Sequence[FaceObservation],
    max_yaw_deg: float,
) -> Clip:
    """Resample frames to 25 fps and attach the nearest face keypoints to each."""
    if not frames:
        return Clip([], [], 1.0, 0.0)
    f_ts = [t for t, _ in frames]
    times = resample_times(f_ts[0], f_ts[-1])
    obs = [o for o in observations if f_ts[0] - MATCH_TOL_MS <= o.ts_ms <= f_ts[-1] + MATCH_TOL_MS]
    o_ts = [o.ts_ms for o in obs]
    out_frames, out_lm = [], []
    for t in times:
        img = frames[nearest(f_ts, t)][1]
        out_frames.append(img)
        lm = None
        if obs:
            o = obs[nearest(o_ts, t)]
            if abs(o.ts_ms - t) <= MATCH_TOL_MS and o.face_present and o.keypoints is not None:
                h, w = img.shape[:2]
                lm = o.keypoints * np.array([w, h], dtype=np.float32)
        out_lm.append(lm)
    # rules are judged on the raw observations, not on interpolated frames
    missing = 1.0 if not obs else sum(not o.face_present for o in obs) / len(obs)
    yaws = [abs(o.yaw_deg) for o in obs if o.face_present and o.yaw_deg is not None]
    yaw_over = (sum(y > max_yaw_deg for y in yaws) / len(yaws)) if yaws else 0.0
    return Clip(out_frames, out_lm, missing, yaw_over)


def judge(clip: Clip, min_frames: int) -> str | None:
    """Return a reason when evidence is insufficient (section 8.4), else None."""
    if len(clip.frames) < min_frames:
        return f"only {len(clip.frames)} frames (< {min_frames})"
    if clip.missing_fraction > MAX_MISSING_FRACTION:
        return f"face missing in {clip.missing_fraction:.0%} of frames"
    if all(lm is None for lm in clip.landmarks):
        return "no face landmarks in clip"
    if clip.yaw_over_fraction > MAX_YAW_FRACTION:
        return f"head turned beyond yaw limit in {clip.yaw_over_fraction:.0%} of frames"
    return None


# --- Auto-AVSR reader -----------------------------------------------------


class AutoAvsrReader:
    """LipReader around Auto-AVSR's own preprocessing and ModelModule (VSR)."""

    def __init__(
        self, checkpoint: Path, avsr_dir: Path = AVSR_DIR, load_model: bool = True
    ) -> None:
        import argparse

        import torch

        if str(avsr_dir) not in sys.path:
            sys.path.insert(0, str(avsr_dir))
        from datamodule.transforms import VideoTransform  # type: ignore[import-not-found]
        from lightning import ModelModule  # type: ignore[import-not-found]
        from preparation.detectors.mediapipe.video_process import (  # type: ignore[import-not-found]
            VideoProcess,
        )

        self._torch = torch
        self.video_process = VideoProcess(convert_gray=False)  # frames arrive greyscale
        self.video_transform = VideoTransform(subset="test")
        self.checkpoint = checkpoint
        self.modelmodule = None
        if load_model:  # False only in tests that exercise preprocessing alone
            self.modelmodule = ModelModule(argparse.Namespace(modality="video"))
            ckpt = torch.load(str(checkpoint), map_location=lambda storage, loc: storage)
            self.modelmodule.model.load_state_dict(ckpt)
            self.modelmodule.eval()

    @property
    def available(self) -> bool:
        return self.modelmodule is not None

    def preprocess(self, frames: Sequence[np.ndarray], landmarks: Sequence[np.ndarray | None]):
        video = np.stack(frames)  # T x H x W (grey)
        cropped = self.video_process(video, list(landmarks))  # Auto-AVSR: T x 96 x 96
        if cropped is None:
            raise ValueError("Auto-AVSR VideoProcess returned no patch")
        t = self._torch.tensor(cropped).unsqueeze(1)  # T x 1 x 96 x 96
        return self.video_transform(t)  # T x 1 x 88 x 88, normalised

    def read(
        self, frames: Sequence[np.ndarray], landmarks: Sequence[np.ndarray | None] = ()
    ) -> LipEvidence:
        video = self.preprocess(frames, landmarks)
        text, score = self._decode(video)
        return LipEvidence(status="ok", text=text, score=score, frames=len(frames))

    def _decode(self, video) -> tuple[str, float]:
        # Same steps as ModelModule.forward (lightning.py), also keeping the best hypothesis
        # score, which forward() discards. Score = exp(mean log-prob per output token): a
        # relative hint, not a calibrated probability (D-024).
        from lightning import get_beam_search_decoder  # type: ignore[import-not-found]

        mm = self.modelmodule
        with self._torch.no_grad():
            beam = get_beam_search_decoder(mm.model, mm.token_list)
            x = mm.model.frontend(video.unsqueeze(0))
            x = mm.model.proj_encoder(x)
            enc, _ = mm.model.encoder(x, None)
            hyps = beam(enc.squeeze(0))
        best = hyps[0].asdict()
        yseq = list(map(int, best["yseq"][1:]))
        text = mm.text_transform.post_process(self._torch.tensor(yseq)).replace("<eos>", "")
        n = max(1, len(yseq))
        score = float(math.exp(float(best["score"]) / n))
        return text.strip(), round(min(1.0, score), 4)


# --- HuggingFace Space lip reader (D-050) ---------------------------------


class HFSpaceLipReader:
    """LipReader that calls the deployed Gradio Space instead of a local checkpoint.

    The Space expects a face video file and returns the transcribed text.
    Frames (greyscale uint8, 25 fps after resampling) are written to a
    temporary MP4, sent to the Space via ``gradio_client``, then the temp
    file is deleted immediately (R8: no raw media left on disk after the
    call returns).

    Parameters
    ----------
    space_id:
        HuggingFace Space ID, e.g. ``"marshal-yash/vsr_trlrs3vox2_base"``.
    beam_size:
        Beam-search width passed to the Space (5..40, default 20).
    hf_token:
        Optional HF token for private Spaces.
    """

    def __init__(
        self,
        space_id: str = "marshal-yash/vsr_trlrs3vox2_base",
        beam_size: int = 20,
        hf_token: str | None = None,
    ) -> None:
        self._space_id = space_id
        self._beam_size = int(beam_size)
        self._hf_token = hf_token
        self._client = None  # lazy-initialised on first call

    def _get_client(self):
        if self._client is None:
            try:
                from gradio_client import Client  # noqa: PLC0415
            except ImportError as exc:
                raise RuntimeError(
                    "gradio-client is not installed; "
                    "run: pip install gradio-client"
                ) from exc
            kwargs = {}
            if self._hf_token:
                kwargs["hf_token"] = self._hf_token
            self._client = Client(self._space_id, **kwargs)
        return self._client

    @property
    def available(self) -> bool:
        return find_spec("gradio_client") is not None

    @property
    def reason(self) -> str:
        return "" if self.available else (
            "gradio-client is not installed; run: pip install gradio-client"
        )

    def read(
        self,
        frames: Sequence[np.ndarray],
        landmarks: Sequence[np.ndarray | None] = (),
    ) -> LipEvidence:
        """Encode *frames* to a temp MP4, call the HF Space, return LipEvidence."""
        import tempfile  # noqa: PLC0415

        import cv2  # noqa: PLC0415
        from gradio_client import handle_file  # noqa: PLC0415

        if not frames:
            return LipEvidence(status="insufficient_visual_evidence", frames=0)

        h, w = frames[0].shape[:2]
        tmp = None
        try:
            # Write greyscale frames to a temp file as a BGR MP4 (OpenCV needs BGR)
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
                tmp = tf.name
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            out = cv2.VideoWriter(tmp, fourcc, TARGET_FPS, (w, h))
            for frame in frames:
                # Convert greyscale -> BGR so VideoWriter accepts it
                bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                out.write(bgr)
            out.release()

            client = self._get_client()
            result: str = client.predict(
                video_path=handle_file(tmp),
                beam_size=float(self._beam_size),
                api_name="/predict",
            )
        finally:
            # Always delete the temp file (R8)
            if tmp is not None:
                try:
                    Path(tmp).unlink(missing_ok=True)
                except Exception:
                    log.warning("could not delete temp clip %s", tmp)

        text = (result or "").strip()
        log.debug("HF Space returned: %r", text)
        # The Space does not return a confidence score; use 0.5 as a neutral hint
        return LipEvidence(status="ok", text=text, score=0.5, frames=len(frames))



class UnavailableLipReader:
    def __init__(self, reason: str) -> None:
        self.reason = reason

    @property
    def available(self) -> bool:
        return False

    def read(self, frames, landmarks=()) -> LipEvidence:
        return LipEvidence(status="unavailable", frames=len(frames))


def load_reader(
    settings: Settings,
) -> HFSpaceLipReader | AutoAvsrReader | UnavailableLipReader:
    """Return the best available LipReader for *settings*.

    Priority
    --------
    1. ``HFSpaceLipReader`` when ``LIP_HF_SPACE`` is set.
    2. ``AutoAvsrReader`` when the local checkpoint and Auto-AVSR tree are present.
    3. ``UnavailableLipReader`` otherwise.
    """
    if not settings.lip_enabled:
        return UnavailableLipReader("LIP_ENABLED=0")

    # D-050: prefer the HuggingFace Space when configured
    if settings.lip_hf_space:
        log.info("lip: using HuggingFace Space %s", settings.lip_hf_space)
        return HFSpaceLipReader(
            space_id=settings.lip_hf_space,
            beam_size=settings.lip_hf_beam_size,
            hf_token=settings.lip_hf_token or None,
        )

    if not settings.lip_checkpoint.is_file():
        return UnavailableLipReader(
            f"checkpoint {settings.lip_checkpoint.name} missing; run scripts/download_lip_model.py"
        )
    if not (AVSR_DIR / "lightning.py").is_file():
        return UnavailableLipReader("third_party/auto_avsr not cloned")
    try:
        return AutoAvsrReader(settings.lip_checkpoint)
    except ImportError as exc:
        return UnavailableLipReader(
            f"lip extra not installed ({exc.name}); see requirements-lip.txt"
        )
    except Exception as exc:
        log.exception("Auto-AVSR failed to load")
        return UnavailableLipReader(f"Auto-AVSR load failed: {type(exc).__name__}")


# --- service -------------------------------------------------------------

LipCallback = Callable[[LipEvidence], None]


class LipService:
    """Capture modes: `push` (start/stop driven by turns) and `auto` (driven by mouth_activity)."""

    def __init__(
        self,
        settings: Settings,
        hub: CameraHub,
        face: FaceService,
        bus: EventBus,
        health: HealthRegistry,
        consent: ConsentRegistry,
        reader_factory: Callable[[], object] | None = None,
        mode: str = "push",
    ) -> None:
        if mode not in {"push", "auto"}:
            raise ValueError("mode must be 'push' or 'auto'")
        self._s = settings
        self._hub = hub
        self._face = face
        self._bus = bus
        self._health = health
        self._consent = consent
        self._reader_factory = reader_factory or (lambda: load_reader(settings))
        self.mode = mode
        self.reader = None
        self._lock = threading.Lock()
        n = max(1, int(settings.lip_buffer_s * settings.camera_fps) + 2)
        self._frames: deque[tuple[int, np.ndarray]] = deque(maxlen=n)
        self._capturing = False
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lip")
        self._subs: list[LipCallback] = []
        self._was_active = False
        hub.subscribe(self._on_frame)
        face.subscribe(self._on_observation)

    # --- lifecycle --------------------------------------------------

    def load(self) -> None:
        """Load the reader once (slow for Auto-AVSR: ~1 GB of weights)."""
        if self.reader is None:
            self.reader = self._reader_factory()
        if getattr(self.reader, "available", False):
            if isinstance(self.reader, HFSpaceLipReader):
                detail = f"HF Space {self.reader._space_id} (beam={self.reader._beam_size})"
            else:
                detail = f"Auto-AVSR {self._s.lip_checkpoint.name}"
            self._health.set("lip", "ok", detail, "real")
        else:
            reason = getattr(self.reader, "reason", "unavailable")
            self._health.set("lip", "unavailable", f"{reason}; mouth_activity only")

    def subscribe(self, cb: LipCallback) -> None:
        with self._lock:
            self._subs.append(cb)

    # --- capture ------------------------------------------------------

    def start_capture(self) -> None:
        self._consent.require("camera")
        with self._lock:
            self._frames.clear()
            self._capturing = True

    def stop_capture(self) -> Future[LipEvidence]:
        """Stop capturing and read the clip in the worker thread (never the camera thread)."""
        with self._lock:
            self._capturing = False
            frames = list(self._frames)
            self._frames.clear()  # the clip lives only in this call from here on (R8)
        observations = self._face.history()
        return self._pool.submit(self._evaluate, frames, observations)

    @property
    def capturing(self) -> bool:
        return self._capturing

    def _on_frame(self, frame: Frame) -> None:
        if not self._capturing:
            return
        import cv2

        grey = cv2.cvtColor(frame.image, cv2.COLOR_BGR2GRAY)
        with self._lock:
            if self._capturing:
                self._frames.append((frame.ts_ms, grey))

    def _on_observation(self, obs: FaceObservation) -> None:
        if self.mode != "auto":
            return
        active = self._face.mouth_activity
        if active and not self._was_active and not self._capturing:
            self.start_capture()
        elif not active and self._was_active and self._capturing:
            self.stop_capture()
        self._was_active = active

    # --- evaluation ---------------------------------------------------

    def _evaluate(
        self, frames: list[tuple[int, np.ndarray]], observations: list[FaceObservation]
    ) -> LipEvidence:
        reason: str | None
        if self.reader is None:
            self.load()
        reader = self.reader
        if not getattr(reader, "available", False):
            ev = LipEvidence(status="unavailable", frames=len(frames))
            reason = getattr(reader, "reason", "unavailable")
        else:
            clip = build_clip(frames, observations, self._s.lip_max_yaw_deg)
            reason = judge(clip, self._s.lip_min_frames)
            if reason is not None:
                ev = LipEvidence(status="insufficient_visual_evidence", frames=len(clip.frames))
            else:
                try:
                    ev = reader.read(clip.frames, clip.landmarks)  # type: ignore[union-attr]
                except Exception as exc:
                    log.exception("lip inference failed")
                    reason = f"inference failed: {type(exc).__name__}"
                    ev = LipEvidence(status="insufficient_visual_evidence", frames=len(clip.frames))
        del frames  # drop the clip (R8)
        self._bus.publish("lip.result", {**ev.model_dump(), "reason": reason, "hint_only": True})
        with self._lock:
            subs = list(self._subs)
        for cb in subs:
            try:
                cb(ev)
            except Exception:
                log.exception("lip subscriber failed")
        return ev

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
