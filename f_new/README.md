# SAMPARK

The landing page and communication app, built in React, TypeScript, and Vite. The visual system uses mist, sage, ivory, and muted blue, with locally hosted DM Sans and Cormorant Garamond for the preserved cinematic video title. Daylight is the default appearance; a tactile day/night switch remembers your preference across the landing page and app.

## Run

```sh
cd f_new
npm install
npm run dev
```

Open http://127.0.0.1:5173. Production: `npm run build`, then `npm run preview`.

The landing page runs independently of the Python backend. **Open Sampark**, **Find your expression**, and **Enter your space** open the integrated app at `/#message`; no second frontend is needed. For live app functionality, start the Python backend on `127.0.0.1:8765` using `scripts/run.sh` from the repository root. Vite proxies `/backend/*` and the camera preview to that backend.

The studio is explicitly an illustrative preview. It cycles through local samples, never requests microphone/camera access, and speaks an example only after you choose **Hear this example**, using your device voice. The live app preserves its existing permission, capture, candidate-review, and confirmation flows. The app loads on demand so its avatar and conferencing dependencies do not block the landing page.

## Design assets

Nature photographs are bundled locally in `public/images/` (approximately 630 KB total); no image or font requests go to third-party services at runtime. Scene names are descriptive, with no geographic claims. Source images from Unsplash:

- Woodland: https://images.unsplash.com/photo-1448375240586-882707db888b
- Lake: https://images.unsplash.com/photo-1470770841072-f978cf4d019e
- Mountains: https://images.unsplash.com/photo-1454496522488-7a8e488e8606

## Video and title masking

Each supplied 10-second, 24 fps video has **240 full-resolution JPEG frames**: the original night clip is in `frames/dark/`, and the daylight clip is in `frames/light/`. Runtime videos and posters are separated into `public/media/dark/` and `public/media/light/`. The scene toggle switches between them and remembers the selection. Intermediate frames and segmentation caches remain local and aren't shipped with the site.

`scripts/prepare-media.py` creates a foreground matte for each frame using U²-Net, then includes the bright monitor in that matte. FFmpeg stacks the original frame above its grayscale mask into one H.264 video. Both layers share the exact same decoded frame, so their timing cannot drift.

`src/HeroScene.tsx` composites the video, an ivory SAMPARK text texture, and the foreground matte using WebGL. The boy and monitor occlude the lettering. A portrait-aware crop keeps the subject in view on phones. The clip plays forward and back at 0.85× for a gentle return to its first frame, with no hard loop cut. There is no audio track.

The delivered runtime assets are ready to use; Python is only needed to regenerate them:

```sh
# From f_new; requires ffmpeg and Python 3.11+
uv venv .media-cache/venv --python 3.11
uv pip install --python .media-cache/venv/bin/python 'rembg[cpu]==2.0.86' opencv-python-headless
.media-cache/venv/bin/python scripts/prepare-media.py --theme light
.media-cache/venv/bin/python scripts/prepare-media.py --theme dark
```

The first generation downloads the U²-Net model. Only the supplied generated design clip is processed; this script never accesses a camera or patient recordings.

The preparation pipeline also runs `scripts/remove-symbol.py --theme light|dark`: OpenCV Telea inpainting removes the fixed lower-right sparkle from every frame. Clean PNGs are saved in `.media-cache/light/clean-frames/` and `.media-cache/dark/clean-frames/`; each playback video and both posters use the corresponding cleaned frames. The originals are preserved. The mask coordinates are specific to these supplied 1280×720 clips.

Reduced motion renders a masked still image, with an explicit play option. Playback pauses when the hero leaves the viewport or the tab is hidden. A regular poster and HTML heading remain available if WebGL cannot run.

## Files

- `src/App.tsx`: navigation, story sections, expression examples, application links.
- `src/HeroScene.tsx`: synchronized video/matte compositing and playback lifecycle.
- `src/styles.css`: responsive landing design, tactile controls, and motion preferences.
- `src/app-theme.css`: scoped app palette and shared component treatments.
- `src/SootheStudio.tsx`: clearly labelled interactive sample preview.
- `src/components/`: six live application screens and shared controls.
- `public/media/`: optimized packed video and still-image fallbacks.
- `public/fonts/`: self-hosted fonts and their OFL licenses.
- `scripts/prepare-media.py`: reproducible frame extraction, matting, and encoding.
- `scripts/check-browser.mjs`: desktop/mobile browser verification and screenshots.

## Verify

```sh
npm run build
# With the dev server running (Chrome installed):
npm run test:browser
```

Browser checks cover video pause/play, reduced motion, WebGL fallback, responsive overflow, navigation, sample selection, expression tabs and keyboard controls, app links, and browser errors. `node scripts/verify-in-app.mjs` checks all six app routes and return navigation against the running backend without changing permissions. Screenshots are saved in `artifacts/` (ignored by Git). Set `TEST_URL` for a different preview URL or `PLAYWRIGHT_CHANNEL` for a different installed browser channel.
