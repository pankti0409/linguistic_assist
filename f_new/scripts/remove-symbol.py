"""Remove the fixed lower-right sparkle from every supplied 1280x720 frame.

OpenCV Telea inpainting reconstructs only the masked pixels from their surroundings.
Original frames remain untouched. Run before prepare-media.py to regenerate playback.
"""
from pathlib import Path
import argparse

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", choices=["light", "dark"], default="dark")
    args = parser.parse_args()
    sources = sorted((ROOT / "frames" / args.theme).glob("frame-*.jpg"))
    if not sources:
        raise SystemExit("No extracted frames found. Run prepare-media.py first.")
    output = ROOT / ".media-cache" / args.theme / "clean-frames"
    output.mkdir(parents=True, exist_ok=True)
    # Work in a small crop; coordinates are for the supplied clip, not arbitrary videos.
    x0, y0, x1, y1 = 1100, 540, 1220, 660
    mask = np.zeros((y1 - y0, x1 - x0), np.uint8)
    contour = np.array([
        [1160, 571], [1169, 589], [1189, 600], [1169, 610],
        [1160, 630], [1150, 610], [1130, 600], [1150, 589],
    ], np.int32) - [x0, y0]
    cv2.fillPoly(mask, [contour], 255)
    mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    for index, source in enumerate(sources):
        frame = cv2.imread(str(source))
        if frame is None or frame.shape[:2] != (720, 1280):
            raise ValueError(f"Expected a 1280x720 frame: {source}")
        crop = frame[y0:y1, x0:x1]
        frame[y0:y1, x0:x1] = cv2.inpaint(crop, mask, 5, cv2.INPAINT_TELEA)
        target = output / source.with_suffix(".png").name
        if not cv2.imwrite(str(target), frame):
            raise OSError(f"Could not save {target}")
        if (index + 1) % 60 == 0:
            print(f"Cleaned {index + 1}/{len(sources)} frames", flush=True)
    print(f"Clean frames: {output}")


if __name__ == "__main__":
    main()
