"""Extract the supplied design clip, segment its subject, and pack synchronized video layers.

Run with Python 3.11+ and rembg[cpu] installed; ffmpeg must be on PATH.
Only processes the supplied, generated design video. Never uses camera/patient media.
"""
from pathlib import Path
import argparse
import os
import subprocess
import sys

os.environ.setdefault("OMP_NUM_THREADS", "4")

import numpy as np
from PIL import Image, ImageFilter, ImageChops
from rembg import new_session, remove
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--theme", choices=["light", "dark"], default="dark")
    args = parser.parse_args()
    source_video = ROOT / {
        "dark": "gemini_generated_video_473a762e.mp4",
        "light": "gemini_generated_video_6c8214ea.mp4",
    }[args.theme]
    frames = ROOT / "frames" / args.theme
    cache = ROOT / ".media-cache" / args.theme
    masks = cache / "masks"
    refined = cache / "refined"
    output = ROOT / "public/media" / args.theme
    output.mkdir(parents=True, exist_ok=True)
    frames.mkdir(parents=True, exist_ok=True)
    masks.mkdir(parents=True, exist_ok=True)
    refined.mkdir(parents=True, exist_ok=True)
    if not (frames / "frame-0240.jpg").exists():
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i",
            str(source_video),
            "-vf", "fps=24,scale=1280:-1", "-q:v", "2", str(frames / "frame-%04d.jpg"),
        ], check=True)
    session = new_session("u2net", providers=["CPUExecutionProvider"])
    sources = sorted(frames.glob("frame-*.jpg"))
    if args.sample:
        sources = sources[:1]
    for i, source in enumerate(sources):
        target = masks / source.with_suffix(".png").name
        if not target.exists():
            with Image.open(source) as frame:
                matte = remove(frame, session=session, only_mask=True).convert("L")
                matte = matte.filter(ImageFilter.GaussianBlur(0.6))
                matte.save(target)
        # The segmentation model selects the boy but omits the glowing monitor.
        # Track its bright connected region within its known location in this
        # supplied clip, preserving the monitor's depth without masking its glow.
        with Image.open(source) as frame, Image.open(target) as matte:
            rgb = np.asarray(frame)
            screen = np.zeros(rgb.shape[:2], dtype=bool)
            region = rgb[290:485, 670:850].astype(np.int16)
            screen[290:485, 670:850] = (
                (region[:, :, 0] > 220) & (region[:, :, 1] > 205)
                & (region[:, :, 2] > 100) & (region[:, :, 0] > region[:, :, 2] + 35)
            )
            if args.theme == "light":
                screen[:] = False
                region = rgb[310:450, 700:840]
                screen[310:450, 700:840] = region.max(axis=2) < 125
            labels, count = ndimage.label(screen)
            if count:
                sizes = np.bincount(labels.ravel())
                sizes[0] = 0
                screen = labels == sizes.argmax()
                screen = ndimage.binary_fill_holes(screen)
                screen = ndimage.binary_dilation(screen, iterations=5)
            screen_matte = Image.fromarray((screen * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.7))
            ImageChops.lighter(matte, screen_matte).save(refined / target.name)
        if i % 24 == 0:
            print(f"Segmented {i + 1}/{len(sources)} frames", flush=True)
    if args.sample:
        return
    # Inpaint the design clip's fixed sparkle before encoding the visible layer.
    # Reuse the existing subject mattes: the edited corner is outside the subject.
    subprocess.run([sys.executable, str(ROOT / "scripts/remove-symbol.py"), "--theme", args.theme], check=True)
    clean_frames = cache / "clean-frames"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-framerate", "24", "-i", str(clean_frames / "frame-%04d.png"),
        "-framerate", "24", "-i", str(refined / "frame-%04d.png"),
        "-filter_complex", "[0:v]fps=24,setsar=1[color];[1:v]format=yuv420p[mask];[color][mask]vstack=inputs=2,split[forward][backward];[backward]reverse[reversed];[forward][reversed]concat=n=2:v=1:a=0[packed]",
        "-map", "[packed]", "-an", "-c:v", "libx264", "-crf", "21", "-preset", "slow",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-shortest",
        str(output / "sampark-packed.mp4"),
    ], check=True)
    with Image.open(clean_frames / "frame-0001.png") as frame:
        frame.save(output / "poster.webp", quality=92)
        packed = Image.new("RGB", (1280, 1440))
        packed.paste(frame, (0, 0))
        with Image.open(refined / "frame-0001.png") as matte:
            packed.paste(matte.convert("RGB"), (0, 720))
        packed.save(output / "poster-packed.webp", quality=95)
    print(f"{args.theme.capitalize()} packed video and posters ready.", flush=True)


if __name__ == "__main__":
    main()
