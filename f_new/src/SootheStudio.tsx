import { useEffect, useRef, useState, type CSSProperties } from "react";
import { ArrowRight, Check, Mic, Play, RotateCcw, Volume2, VolumeX } from "lucide-react";

interface SootheStudioProps {
  onToast: (message: string) => void;
}

const EXAMPLES = [
  {
    label: "A few words",
    fragments: ["water", "…", "cold"],
    text: "I would like cold water, please.",
    note: "A word. A pause. Another word. There is room for all of it.",
  },
  {
    label: "A familiar feeling",
    fragments: ["need", "a break"],
    text: "I need to take a break.",
    note: "Even a small expression can carry a complete thought.",
  },
  {
    label: "A shared moment",
    fragments: ["sit", "with me"],
    text: "Please sit with me for a moment.",
    note: "The little things you want to say deserve to be heard.",
  },
];

const REST_WAVE = Array.from({ length: 28 }, (_, i) =>
  0.12 + Math.sin(((i + 0.5) / 28) * Math.PI) * (0.16 + Math.abs(Math.sin(i * 1.7)) * 0.42),
);

export default function SootheStudio({ onToast }: SootheStudioProps) {
  const [selected, setSelected] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [barsHeight, setBarsHeight] = useState(REST_WAVE);
  const sampleTimeout = useRef<number | null>(null);
  const waveInterval = useRef<number | null>(null);
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);
  const example = EXAMPLES[selected];
  const supportsSpeech = typeof window !== "undefined" && "speechSynthesis" in window;

  const stopPreview = () => {
    if (sampleTimeout.current !== null) window.clearTimeout(sampleTimeout.current);
    if (waveInterval.current !== null) window.clearInterval(waveInterval.current);
    sampleTimeout.current = null;
    waveInterval.current = null;
    setIsPlaying(false);
    setBarsHeight(REST_WAVE);
  };

  const stopSpeech = () => {
    if (utteranceRef.current) {
      utteranceRef.current.onend = null;
      utteranceRef.current.onerror = null;
      window.speechSynthesis.cancel();
      utteranceRef.current = null;
    }
    setIsSpeaking(false);
  };

  const playExample = (index: number) => {
    stopPreview();
    stopSpeech();
    setSelected(index);
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    setIsPlaying(true);
    let frame = 0;
    waveInterval.current = window.setInterval(() => {
      frame += 1;
      setBarsHeight(REST_WAVE.map((height, i) =>
        Math.max(0.1, height * (0.5 + Math.abs(Math.sin(frame * 0.4 + i * 0.65)))),
      ));
    }, 90);
    sampleTimeout.current = window.setTimeout(stopPreview, 1100);
  };

  const hearExample = () => {
    if (isSpeaking) {
      stopSpeech();
      return;
    }
    if (!supportsSpeech) return;
    const utterance = new SpeechSynthesisUtterance(example.text);
    utterance.rate = 0.9;
    utterance.onend = () => {
      utteranceRef.current = null;
      setIsSpeaking(false);
    };
    utterance.onerror = (event) => {
      utteranceRef.current = null;
      setIsSpeaking(false);
      if (event.error !== "canceled" && event.error !== "interrupted") {
        onToast("Device voice is unavailable. You can still read the example.");
      }
    };
    utteranceRef.current = utterance;
    setIsSpeaking(true);
    window.speechSynthesis.speak(utterance);
  };

  useEffect(() => () => {
    if (sampleTimeout.current !== null) window.clearTimeout(sampleTimeout.current);
    if (waveInterval.current !== null) window.clearInterval(waveInterval.current);
    if (utteranceRef.current) {
      utteranceRef.current.onend = null;
      utteranceRef.current.onerror = null;
      window.speechSynthesis.cancel();
    }
  }, []);

  return (
    <div className="s-studio-wrap">
      <div className="s-studio-top">
        <span className="eyebrow muted">INTERACTIVE PREVIEW</span>
        <h2>A little expression.<br /><em>A complete thought.</em></h2>
        <p>See how a few words can come together. This is a sample experience; your microphone and camera stay off.</p>
      </div>

      <div className="s-studio-grid">
        <div className={`s-studio-speak ${isPlaying ? "is-playing" : ""}`}>
          <span className="s-preview-label"><span className="status-dot" /> A LITTLE EXPRESSION</span>
          <div className="s-orbwrap">
            <button
              type="button"
              className={`s-orb ${isPlaying ? "is-listening" : ""}`}
              aria-label={isPlaying ? "Restart example" : "Try an example"}
              onClick={() => playExample(selected)}
            >
              {isPlaying ? <Mic size={36} strokeWidth={1.4} /> : <Play size={32} strokeWidth={1.4} fill="currentColor" />}
            </button>
            <span className="s-orb-label">{isPlaying ? "Bringing words together…" : "Try an example"}</span>
          </div>
          <div className="s-wave" aria-hidden="true">
            {barsHeight.map((height, i) => (
              <i key={i} style={{ "--h": height } as CSSProperties} />
            ))}
          </div>
          <div className="s-input-fragments" aria-label="Example words">
            {example.fragments.map((fragment, index) => (
              <span key={`${selected}-${index}`} className={fragment === "…" ? "is-pause" : ""}>{fragment}</span>
            ))}
          </div>
          <p className="s-preview-note">{example.note}</p>
        </div>

        <div className="s-panel">
          <div className="s-panel-heading">
            <span className="eyebrow muted">A POSSIBLE WAY TO SAY IT</span>
            <span className="s-sample-tag">Sample</span>
          </div>
          <p className="s-said" aria-live="polite" aria-busy={isPlaying}>
            {isPlaying ? "Finding the words…" : `“${example.text}”`}
          </p>
          <span className="s-review-note"><Check size={15} strokeWidth={1.7} /> Yours to review. Always your choice.</span>
          <div className="s-action-row">
            <button type="button" className="s-btn" onClick={hearExample} disabled={isPlaying || !supportsSpeech}>
              {isSpeaking ? <VolumeX size={16} /> : <Volume2 size={16} />}
              {isSpeaking ? "Stop playback" : "Hear this example"}
            </button>
            <button type="button" className="s-btn s-btn--soft" onClick={() => playExample((selected + 1) % EXAMPLES.length)}>
              <RotateCcw size={15} /> Next example
            </button>
          </div>
          <span className="s-device-note">{supportsSpeech ? "Plays only when you choose, using your device voice." : "Device voice is unavailable in this browser."}</span>
        </div>
      </div>

      <div className="s-studio-section">
        <div className="s-section-title"><span className="eyebrow muted">SMALL WORDS. EVERYDAY MOMENTS.</span></div>
        <div className="s-phrases" role="group" aria-label="Choose a sample expression">
          {EXAMPLES.map((item, index) => (
            <button type="button" key={item.label} className="s-phrase" aria-pressed={selected === index} onClick={() => playExample(index)}>
              {item.label}<ArrowRight size={15} strokeWidth={1.5} />
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
