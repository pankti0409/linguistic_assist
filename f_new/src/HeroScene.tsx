import { useEffect, useRef, useState } from "react";

// Both daylight and night videos are stacked (RGB on top, foreground mask on bottom).
// The fragment shader samples both videos in lockstep and blends between them smoothly
// using themeMix (0.0 = dark, 1.0 = light), without breaking, pausing, or resetting frames.
const VERTEX = `
attribute vec2 position;
varying vec2 uv;
void main() {
  uv = position * 0.5 + 0.5;
  gl_Position = vec4(position, 0.0, 1.0);
}
`;

const FRAGMENT = `
precision mediump float;
varying vec2 uv;
uniform sampler2D filmDark;
uniform sampler2D filmLight;
uniform sampler2D lettering;
uniform vec2 resolution;
uniform float themeMix;
uniform vec3 textDarkColor;
uniform vec3 textLightColor;

void main() {
  vec2 screen = vec2(uv.x, 1.0 - uv.y);
  float aspect = resolution.x / resolution.y;
  float sourceAspect = 1280.0 / 720.0;
  vec2 cover = vec2(min(1.0, aspect / sourceAspect), min(1.0, sourceAspect / aspect));
  float focalX = mix(0.43, 0.5, smoothstep(0.6, 1.2, aspect));
  vec2 source = (screen - 0.5) * cover + vec2(focalX, 0.5);

  vec3 colorDark = texture2D(filmDark, vec2(source.x, source.y * 0.5)).rgb;
  float foregroundDark = texture2D(filmDark, vec2(source.x, 0.5 + source.y * 0.5)).r;

  vec3 colorLight = texture2D(filmLight, vec2(source.x, source.y * 0.5)).rgb;
  float foregroundLight = texture2D(filmLight, vec2(source.x, 0.5 + source.y * 0.5)).r;

  // Seamless continuation: interpolate color and occlusion between dark and light
  vec3 color = mix(colorDark, colorLight, themeMix);
  float foreground = mix(foregroundDark, foregroundLight, themeMix);

  float titleAlpha = texture2D(lettering, screen).a;
  vec3 textColor = mix(textDarkColor, textLightColor, themeMix);
  float ink = titleAlpha * (1.0 - smoothstep(0.08, 0.92, foreground));

  gl_FragColor = vec4(mix(color, textColor, ink), 1.0);
}
`;

interface Props {
  theme: "light" | "dark";
  motion: boolean;
  onPlayback: (playing: boolean) => void;
  onAvailable: (available: boolean) => void;
}

export default function HeroScene({
  theme,
  motion,
  onPlayback,
  onAvailable,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const control = useRef<(play: boolean) => void>(() => {});
  const triggerRender = useRef<() => void>(() => {});
  const onPlaybackRef = useRef(onPlayback);
  onPlaybackRef.current = onPlayback;
  const motionRef = useRef(motion);
  motionRef.current = motion;
  const themeRef = useRef(theme);
  themeRef.current = theme;

  const targetMixRef = useRef(theme === "light" ? 1.0 : 0.0);
  const currentMixRef = useRef(theme === "light" ? 1.0 : 0.0);

  const [ready, setReady] = useState(false);

  // Respond immediately to theme toggle without unmounting or resetting video frames
  useEffect(() => {
    targetMixRef.current = theme === "light" ? 1.0 : 0.0;
    triggerRender.current();
  }, [theme]);

  useEffect(() => {
    const canvas = canvasRef.current!;
    const gl = canvas.getContext("webgl", {
      alpha: false,
      antialias: false,
      powerPreference: "low-power",
    });
    if (!gl) {
      onAvailable(false);
      return;
    }

    let disposed = false;
    let frameId = 0;
    let videoFrameId = 0;
    let inView = true;
    let fontReady = false;
    let darkReady = false;
    let lightReady = false;
    let lastTime = performance.now();

    // Dual video streams synchronized to the exact same frame
    const videoDark = document.createElement("video");
    videoDark.muted = true;
    videoDark.loop = true;
    videoDark.playsInline = true;
    videoDark.playbackRate = 0.85;
    videoDark.preload = "auto";
    videoDark.src = `/media/dark/sampark-packed.mp4?v=clean`;

    const videoLight = document.createElement("video");
    videoLight.muted = true;
    videoLight.loop = true;
    videoLight.playsInline = true;
    videoLight.playbackRate = 0.85;
    videoLight.preload = "auto";
    videoLight.src = `/media/light/sampark-packed.mp4?v=clean`;

    const posterDark = new Image();
    posterDark.src = `/media/dark/poster-packed.webp?v=clean`;

    const posterLight = new Image();
    posterLight.src = `/media/light/poster-packed.webp?v=clean`;

    const textCanvas = document.createElement("canvas");
    const ctx = textCanvas.getContext("2d")!;

    const shader = (type: number, code: string) => {
      const result = gl.createShader(type)!;
      gl.shaderSource(result, code);
      gl.compileShader(result);
      if (!gl.getShaderParameter(result, gl.COMPILE_STATUS))
        throw new Error("Scene shader could not compile");
      return result;
    };

    let program: WebGLProgram;
    let vertex: WebGLShader;
    let fragment: WebGLShader;
    try {
      vertex = shader(gl.VERTEX_SHADER, VERTEX);
      fragment = shader(gl.FRAGMENT_SHADER, FRAGMENT);
      program = gl.createProgram()!;
      gl.attachShader(program, vertex);
      gl.attachShader(program, fragment);
      gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS))
        throw new Error("Scene could not link");
    } catch {
      onAvailable(false);
      return;
    }

    gl.useProgram(program);

    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]),
      gl.STATIC_DRAW,
    );
    const position = gl.getAttribLocation(program, "position");
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);

    const makeTexture = (unit: number) => {
      const texture = gl.createTexture()!;
      gl.activeTexture(gl.TEXTURE0 + unit);
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      return texture;
    };

    const filmDarkTexture = makeTexture(0);
    const filmLightTexture = makeTexture(1);
    const textTexture = makeTexture(2);

    gl.uniform1i(gl.getUniformLocation(program, "filmDark"), 0);
    gl.uniform1i(gl.getUniformLocation(program, "filmLight"), 1);
    gl.uniform1i(gl.getUniformLocation(program, "lettering"), 2);

    const resolution = gl.getUniformLocation(program, "resolution");
    const themeMixLoc = gl.getUniformLocation(program, "themeMix");
    const textDarkColorLoc = gl.getUniformLocation(program, "textDarkColor");
    const textLightColorLoc = gl.getUniformLocation(program, "textLightColor");

    // Colors: Ivory for dark theme (#f3eedb), Deep Teal for light theme (#183e43)
    gl.uniform3f(textDarkColorLoc, 243 / 255, 238 / 255, 219 / 255);
    gl.uniform3f(textLightColorLoc, 24 / 255, 62 / 255, 67 / 255);

    const render = () => {
      if (disposed || (!darkReady && !lightReady) || !fontReady || gl.isContextLost())
        return;

      // Smoothstep easing for a silky visual cross-dissolve
      const m = currentMixRef.current;
      const eased = m * m * (3.0 - 2.0 * m);
      gl.uniform1f(themeMixLoc, eased);

      gl.drawArrays(gl.TRIANGLES, 0, 6);
      setReady(true);
    };

    triggerRender.current = () => {
      if (disposed) return;
      if (!motionRef.current || document.hidden) {
        currentMixRef.current = targetMixRef.current;
      }
      render();
    };

    const resize = () => {
      if (disposed) return;
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 1.75);
      const w = Math.round(rect.width * dpr);
      const h = Math.round(rect.height * dpr);
      canvas.width = textCanvas.width = w;
      canvas.height = textCanvas.height = h;
      gl.viewport(0, 0, w, h);
      gl.uniform2f(resolution, w, h);

      // Render white title texture mask for fragment shader tinting
      const size = w * (rect.width < 600 ? 0.172 : 0.174);
      ctx.font = `400 ${size}px "Cormorant Garamond"`;
      ctx.textBaseline = "alphabetic";
      ctx.fillStyle = "#ffffff";
      const title = "SAMPARK";
      const tracking = size * 0.027;
      const width =
        ctx.measureText(title).width + tracking * (title.length - 1);
      let x = (w - width) / 2;
      const measured = ctx.measureText(title);
      const centerY = h * (rect.width < 600 ? 0.4 : 0.435);
      const y = centerY + measured.actualBoundingBoxAscent / 2;
      for (const char of title) {
        ctx.fillText(char, x, y);
        x += ctx.measureText(char).width + tracking;
      }

      gl.activeTexture(gl.TEXTURE2);
      gl.bindTexture(gl.TEXTURE_2D, textTexture);
      gl.texImage2D(
        gl.TEXTURE_2D,
        0,
        gl.RGBA,
        gl.RGBA,
        gl.UNSIGNED_BYTE,
        textCanvas,
      );
      render();
    };

    const tick = () => {
      if (disposed) return;

      const now = performance.now();
      const dt = Math.min((now - lastTime) / 1000, 0.1);
      lastTime = now;

      // Animate transition between matching frames smoothly
      const target = targetMixRef.current;
      let current = currentMixRef.current;
      let needsDraw = false;

      if (!motionRef.current) {
        current = target;
      } else if (current !== target) {
        const step = dt / 0.42; // 420ms smooth continuation curve
        if (current < target) {
          current = Math.min(target, current + step);
        } else {
          current = Math.max(target, current - step);
        }
        needsDraw = true;
      }
      currentMixRef.current = current;

      // Upload latest video frames
      if (videoDark.readyState >= 2) {
        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, filmDarkTexture);
        gl.texImage2D(
          gl.TEXTURE_2D,
          0,
          gl.RGB,
          gl.RGB,
          gl.UNSIGNED_BYTE,
          videoDark,
        );
        darkReady = true;
        needsDraw = true;
      }

      if (videoLight.readyState >= 2) {
        // Enforce lockstep sync between dark and daylight streams
        if (videoDark.readyState >= 2) {
          const drift = videoLight.currentTime - videoDark.currentTime;
          if (Math.abs(drift) > 0.04) {
            videoLight.currentTime = videoDark.currentTime;
          }
        }
        gl.activeTexture(gl.TEXTURE1);
        gl.bindTexture(gl.TEXTURE_2D, filmLightTexture);
        gl.texImage2D(
          gl.TEXTURE_2D,
          0,
          gl.RGB,
          gl.RGB,
          gl.UNSIGNED_BYTE,
          videoLight,
        );
        lightReady = true;
        needsDraw = true;
      }

      if (needsDraw) {
        render();
      }

      if (motionRef.current && inView && !document.hidden) {
        if ("requestVideoFrameCallback" in videoDark) {
          videoFrameId = videoDark.requestVideoFrameCallback(tick);
        } else {
          frameId = requestAnimationFrame(tick);
        }
      } else if (current !== target) {
        // Keep animating transition even while scene is paused
        frameId = requestAnimationFrame(tick);
      }
    };

    const updatePlayback = () => {
      if (disposed) return;
      if (motionRef.current && inView && !document.hidden) {
        videoDark.play().catch(() => onPlaybackRef.current(false));
        videoLight.play().catch(() => {});
      } else {
        videoDark.pause();
        videoLight.pause();
      }
    };

    control.current = updatePlayback;

    videoDark.addEventListener("play", () => onPlaybackRef.current(true));
    videoDark.addEventListener("pause", () => onPlaybackRef.current(false));
    videoDark.addEventListener("loadeddata", () => {
      darkReady = true;
      render();
    });
    videoLight.addEventListener("loadeddata", () => {
      lightReady = true;
      render();
    });

    posterDark.onload = () => {
      if (disposed) return;
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, filmDarkTexture);
      gl.texImage2D(
        gl.TEXTURE_2D,
        0,
        gl.RGB,
        gl.RGB,
        gl.UNSIGNED_BYTE,
        posterDark,
      );
      darkReady = true;
      render();
    };

    posterLight.onload = () => {
      if (disposed) return;
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, filmLightTexture);
      gl.texImage2D(
        gl.TEXTURE_2D,
        0,
        gl.RGB,
        gl.RGB,
        gl.UNSIGNED_BYTE,
        posterLight,
      );
      lightReady = true;
      render();
    };

    document.fonts.load('400 100px "Cormorant Garamond"').then(() => {
      if (disposed) return;
      fontReady = true;
      resize();
    });

    const observer = new ResizeObserver(resize);
    observer.observe(canvas);

    const intersection = new IntersectionObserver(([entry]) => {
      inView = entry.isIntersecting;
      updatePlayback();
    });
    intersection.observe(canvas);

    const lostContext = (event: Event) => {
      event.preventDefault();
      setReady(false);
      onAvailable(false);
      videoDark.pause();
      videoLight.pause();
    };
    canvas.addEventListener("webglcontextlost", lostContext);
    document.addEventListener("visibilitychange", updatePlayback);

    tick();
    updatePlayback();

    return () => {
      disposed = true;
      cancelAnimationFrame(frameId);
      if (videoFrameId && "cancelVideoFrameCallback" in videoDark) {
        videoDark.cancelVideoFrameCallback(videoFrameId);
      }
      videoDark.pause();
      videoDark.removeAttribute("src");
      videoDark.load();

      videoLight.pause();
      videoLight.removeAttribute("src");
      videoLight.load();

      observer.disconnect();
      intersection.disconnect();
      document.removeEventListener("visibilitychange", updatePlayback);
      canvas.removeEventListener("webglcontextlost", lostContext);

      gl.deleteTexture(filmDarkTexture);
      gl.deleteTexture(filmLightTexture);
      gl.deleteTexture(textTexture);
      gl.deleteBuffer(buffer);
      gl.deleteProgram(program);
      gl.deleteShader(vertex);
      gl.deleteShader(fragment);
    };
  }, []);

  useEffect(() => {
    control.current(motion);
  }, [motion]);

  return (
    <div className="hero-scene" data-ready={ready}>
      <div className="scene-fallback" />
      <h1 className={ready ? "sr-only" : "fallback-title"}>SAMPARK</h1>
      <canvas ref={canvasRef} className="scene-canvas" aria-hidden="true" />
      <div className="scene-shade" />
    </div>
  );
}
