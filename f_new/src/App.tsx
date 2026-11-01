import { lazy, Suspense, useEffect, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Check,
  Hand,
  Menu,
  Mic,
  Pause,
  Play,
  ShieldCheck,
  Sparkles,
  Sun,
  Moon,
  X,
} from "lucide-react";
import HeroScene from "./HeroScene";
import SootheStudio from "./SootheStudio";
import ParallaxCard from "./ParallaxCard";
const PS16App = lazy(() => import("./components/ps16-app"));

const APP_SCREENS = ["message", "partner", "camera", "words", "setup", "insights", "app"];
const APP_URL = "#message";

function Flower({ className = "" }: { className?: string }) {
  return (
    <svg
      className={`flower ${className}`}
      viewBox="0 0 48 48"
      fill="none"
      aria-hidden="true"
    >
      <g transform="translate(24 24)" fill="currentColor">
        {Array.from({ length: 8 }, (_, i) => (
          <ellipse
            key={i}
            cy="-10"
            rx="3.5"
            ry="9"
            transform={`rotate(${i * 45})`}
          />
        ))}
        <circle r="3.5" />
      </g>
    </svg>
  );
}

const expressions = [
  {
    id: "words",
    name: "A few words",
    icon: Mic,
    label: "SPEECH, AT YOUR PACE",
    title: "Small words.\nWhole meanings.",
    body: "A word, a pause, another word. SAMPARK brings the pieces together and offers a complete thought for you to review.",
    fragments: ["water", "…", "cold"],
    result: "I would like cold water, please.",
  },
  {
    id: "gestures",
    name: "A simple gesture",
    icon: Hand,
    label: "MOVEMENT WITH MEANING",
    title: "Let your hands\njoin the conversation.",
    body: "A familiar gesture can carry a word. Choose what your gestures mean, then combine them with speech to shape your message.",
    fragments: ["I", "want", "water"],
    result: "I want water, please.",
  },
  {
    id: "together",
    name: "A shared moment",
    icon: Sparkles,
    label: "A LITTLE CONTEXT HELPS",
    title: "Understanding\nstarts with listening.",
    body: "Your conversation partner’s question gives your words context. You choose the sentence that says what you mean.",
    fragments: ["tea or water?", "water"],
    result: "Water, please.",
  },
];

export default function App() {
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    try {
      return localStorage.getItem("sampark.scene") === "dark"
        ? "dark"
        : "light";
    } catch {
      return "light";
    }
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("sampark.scene", theme);
    } catch {
      /* optional storage */
    }
  }, [theme]);

  const [menuOpen, setMenuOpen] = useState(false);
  const [motion, setMotion] = useState(
    () => !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  const [playing, setPlaying] = useState(false);
  const [sceneAvailable, setSceneAvailable] = useState(true);
  const [active, setActive] = useState(0);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const toastTimerRef = useRef<number | null>(null);
  const menuRef = useRef<HTMLButtonElement>(null);
  const expression = expressions[active];

  const [inApp, setInApp] = useState(() => {
    if (typeof window === "undefined") return false;
    const h = window.location.hash.slice(1);
    return APP_SCREENS.includes(h);
  });

  useEffect(() => {
    const onHash = () => {
      const h = window.location.hash.slice(1);
      const isApp = APP_SCREENS.includes(h);
      setInApp(isApp);
      if (!isApp) setTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
      if (isApp) setMenuOpen(false);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const showToast = (msg: string) => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setToastMessage(msg);
    toastTimerRef.current = window.setTimeout(() => {
      setToastMessage(null);
    }, 2600);
  };

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12 },
    );
    document
      .querySelectorAll("[data-reveal]")
      .forEach((element) => observer.observe(element));
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMenuOpen(false);
        menuRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      observer.disconnect();
      document.removeEventListener("keydown", onKey);
    };
  }, [inApp]);

  useEffect(() => () => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
  }, []);

  if (inApp) {
    return (
      <Suspense fallback={<div className="app-loading" role="status"><Flower /><span>Opening your space…</span></div>}>
      <PS16App
        onLanding={() => {
          setTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
          window.location.hash = "#home";
          setInApp(false);
          window.scrollTo({ top: 0 });
        }}
      />
      </Suspense>
    );
  }

  return (
    <>
      <a className="skip-link" href="#purpose">
        Skip to content
      </a>
      <main className="landing">
        {/* Preserved Hero Section */}
        <section
          className="hero"
          id="home"
          aria-label="SAMPARK: connection beyond words"
        >
          <HeroScene
            theme={theme}
            motion={motion}
            onPlayback={setPlaying}
            onAvailable={setSceneAvailable}
          />
          <header className="header">
            <a href="#home" className="brand" aria-label="Sampark home">
              <Flower />
              <span>
                sampark<span className="brand-period">.</span>
              </span>
            </a>
            <nav className="desktop-nav" aria-label="Main navigation">
              <a href="#purpose">Our purpose</a>
              <a href="#studio">Studio</a>
              <a href="#possibilities">Ways to connect</a>
              <a href="#how-it-works">How it works</a>
            </nav>
            <a
              href={APP_URL}
              className="header-cta"
              onClick={(e) => {
                e.preventDefault();
                window.location.hash = "#message";
                setInApp(true);
              }}
            >
              Open Sampark <ArrowUpRight size={15} strokeWidth={1.5} />
            </a>
            <button
              ref={menuRef}
              className="menu-toggle"
              aria-label={menuOpen ? "Close navigation" : "Open navigation"}
              aria-expanded={menuOpen}
              aria-controls="mobile-nav"
              onClick={() => setMenuOpen(!menuOpen)}
            >
              {menuOpen ? <X /> : <Menu />}
            </button>
          </header>
          {menuOpen && (
            <nav
              id="mobile-nav"
              className="mobile-nav"
              aria-label="Mobile navigation"
            >
              <a href="#purpose" onClick={() => setMenuOpen(false)}>
                Our purpose <ArrowUpRight />
              </a>
              <a href="#studio" onClick={() => setMenuOpen(false)}>
                Interactive studio <ArrowUpRight />
              </a>
              <a href="#possibilities" onClick={() => setMenuOpen(false)}>
                Ways to connect <ArrowUpRight />
              </a>
              <a href="#milestones" onClick={() => setMenuOpen(false)}>
                Serene spaces <ArrowUpRight />
              </a>
              <a href="#how-it-works" onClick={() => setMenuOpen(false)}>
                How it works <ArrowUpRight />
              </a>
              <a
                href={APP_URL}
                onClick={(e) => {
                  e.preventDefault();
                  setMenuOpen(false);
                  window.location.hash = "#message";
                  setInApp(true);
                }}
              >
                Enter your space <ArrowUpRight />
              </a>
            </nav>
          )}
          <div className="hero-overline">
            <span className="status-dot" /> A CALMER WAY TO CONNECT
          </div>
          <p className="hero-subline">There’s more than one way to be heard.</p>
          <div className="hero-bottom">
            <div className="hero-thought">
              <span className="eyebrow">CONNECTION, BEYOND WORDS</span>
              <h2>
                Your voice.
                <br />Your own <em>rhythm.</em>
              </h2>
            </div>
            <a className="scroll-cue" href="#purpose">
              <span>EXPLORE SAMPARK</span>
              <span className="scroll-line" />
              <ArrowDown size={15} strokeWidth={1.25} />
            </a>
            <div className="hero-invitation">
              <p>
                A gentle bridge between what you feel
                <br className="desktop-break" /> and what the world hears.
              </p>
              <a
                className="button button-cream"
                href={APP_URL}
                onClick={(e) => {
                  e.preventDefault();
                  window.location.hash = "#message";
                  setInApp(true);
                }}
              >
                Find your expression{" "}
                <span className="button-icon">
                  <ArrowUpRight size={18} strokeWidth={1.5} />
                </span>
              </a>
            </div>
          </div>
          <div className="hero-meta">
            <button
              className="theme-toggle"
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
              onClick={() => {
                setSceneAvailable(true);
                const nextTheme = theme === "dark" ? "light" : "dark";
                setTheme(nextTheme);
                showToast(`Switched to ${nextTheme} mode`);
              }}
            >
              <span className="scene-switch" aria-hidden="true"><span className="scene-switch-cloud" /><span className="scene-switch-thumb">{theme === "dark" ? <Moon size={15} /> : <Sun size={15} />}</span></span>
              <span className="theme-copy">{theme === "dark" ? "After hours" : "A brighter moment"}</span>
            </button>
            <span>
              <span className="status-dot" /> A LITTLE SPACE TO BE YOURSELF
            </span>
            {sceneAvailable && (
              <button
                className="scene-control"
                aria-label={
                  motion ? "Pause background scene" : "Play background scene"
                }
                aria-pressed={!motion}
                onClick={() => setMotion(!motion)}
              >
                {motion && playing ? (
                  <Pause size={12} fill="currentColor" />
                ) : (
                  <Play size={12} fill="currentColor" />
                )}{" "}
                <span>
                  {motion && playing ? "A moment of calm" : "Scene paused"}
                </span>
              </button>
            )}
          </div>
        </section>

        {/* 01 / Purpose */}
        <section className="purpose section-wrap" id="purpose">
          <div className="section-index" data-reveal>
            <span>01 / OUR PURPOSE</span>
            <span>THOUGHTFULLY HUMAN</span>
          </div>
          <div className="purpose-grid">
            <div className="purpose-heading" data-reveal>
              <span className="eyebrow muted">EVERY EXPRESSION BELONGS</span>
              <h2>
                So much to say.
                <br />
                <span>So many ways</span>
                <br />
                to say it.
              </h2>
            </div>
            <div className="purpose-body" data-reveal>

              <p>
                A thought doesn’t always arrive as a perfect sentence. Sometimes
                it’s a word. A movement. A quiet moment between the two.
              </p>
              <p className="secondary-copy">
                SAMPARK makes room for all of it. A communication companion that
                helps bring your expressions together, so you can connect with
                the people who matter.
              </p>
              <a className="text-link" href="#studio">
                Explore the studio <ArrowRight size={18} />
              </a>
            </div>
          </div>
          <div className="purpose-footnote" data-reveal>
            <span className="hindi-word" lang="hi">
              संपर्क
            </span>
            <span>
              <strong>sampark</strong>{" "}
              <span className="phonetic">/ səmˈpərk /</span>
              <br />A connection. A meeting. A way to reach one another.
            </span>
            <span className="purpose-values"><span><ShieldCheck size={16} /> You stay in control</span><span><Sparkles size={16} /> Room for every expression</span></span>
          </div>
        </section>

        {/* 02 / Interactive sample preview */}
        <section className="studio-wrap section-wrap" id="studio" data-reveal>
          <div className="section-index">
            <span>02 / A MOMENT TO EXPLORE</span>
            <span>SMALL INPUTS. WHOLE MEANINGS.</span>
          </div>
          <SootheStudio onToast={showToast} />
        </section>

        {/* 03 / Ways to connect */}
        <section className="possibilities section-wrap" id="possibilities">
          <div className="section-index" data-reveal>
            <span>03 / WAYS TO CONNECT</span>
            <span>AS INDIVIDUAL AS YOU ARE</span>
          </div>
          <div className="possibilities-header" data-reveal>
            <h2>
              Expression has
              <br />
              <em>many languages.</em>
            </h2>
            <p>
              Start wherever feels natural.
              <br />
              We’ll meet you there.
            </p>
          </div>
          <div className="expression-layout" data-reveal>
            <div className="expression-details">
              <div
                className="expression-tabs"
                role="tablist"
                aria-label="Ways to communicate"
              >
                {expressions.map((item, i) => (
                  <button
                    key={item.id}
                    id={`tab-${item.id}`}
                    role="tab"
                    aria-selected={active === i}
                    aria-controls="expression-panel"
                    tabIndex={active === i ? 0 : -1}
                    className={active === i ? "active" : ""}
                    onClick={() => setActive(i)}
                    onKeyDown={(event) => {
                      const next =
                        event.key === "ArrowRight"
                          ? (active + 1) % 3
                          : event.key === "ArrowLeft"
                            ? (active + 2) % 3
                            : event.key === "Home"
                              ? 0
                              : event.key === "End"
                                ? 2
                                : null;
                      if (next !== null) {
                        event.preventDefault();
                        setActive(next);
                        document
                          .getElementById(`tab-${expressions[next].id}`)
                          ?.focus();
                      }
                    }}
                  >
                    <item.icon size={15} strokeWidth={1.5} />
                    <span>{item.name}</span>
                  </button>
                ))}
              </div>
              <div
                id="expression-panel"
                role="tabpanel"
                aria-labelledby={`tab-${expression.id}`}
                className="expression-panel"
                key={active}
                tabIndex={0}
              >
                <span className="eyebrow muted">{expression.label}</span>
                <h3>
                  {expression.title.split("\n").map((line, i) => (
                    <span key={i}>
                      {line}
                      <br />
                    </span>
                  ))}
                </h3>
                <p>{expression.body}</p>
                <span className="quiet-note">
                  <ShieldCheck size={15} strokeWidth={1.5} /> Your meaning. Your
                  choice.
                </span>
              </div>
            </div>
            <div
              className="expression-demo"
              aria-label="Illustrative example of a reconstructed message"
            >
              <div className="demo-orbit orbit-one" />
              <div className="demo-orbit orbit-two" />
              <div className="demo-label">
                <span className="status-dot" /> A LITTLE EXPRESSION, COMING
                TOGETHER
              </div>
              <div className="fragment-row" key={`fragments-${active}`}>
                {expression.fragments.map((word, i) => (
                  <span
                    key={i}
                    className={
                      word === "…" ? "fragment pause-fragment" : "fragment"
                    }
                  >
                    {word}
                  </span>
                ))}
              </div>
              <div className="connection-thread">
                <span />
                <Flower />
                <span />
              </div>
              <div className="message-example" key={`message-${active}`}>
                <span className="eyebrow">A POSSIBLE WAY TO SAY IT</span>
                <p>“{expression.result}”</p>
                <span className="review-note">
                  <Check size={13} /> Yours to review, edit, or choose.
                </span>
              </div>
              <span className="demo-disclaimer">
                An illustration of the experience
              </span>
            </div>
          </div>
        </section>

        {/* 04 / A quiet visual interlude */}
        <section className="milestones-wrap section-wrap" id="milestones" data-reveal>
          <div className="section-index">
            <span>04 / DESIGNED TO FEEL DIFFERENT</span>
            <span>A BREATH OF FRESH AIR</span>
          </div>
          <div className="milestones-header">
            <div>
              <span className="eyebrow muted">A SOFTER KIND OF TECHNOLOGY</span>
              <h2>A little less noise.<br /><em>A little more nature.</em></h2>
            </div>
            <p>Soft light. Open spaces. Time to breathe.<br />Because finding your words should feel natural.</p>
          </div>
          <div className="milestones-grid">
            <ParallaxCard pill="Room to breathe" index="01" title="A quieter place."
              description="A little distance from the noise. A little closer to yourself."
              image="/images/forest.jpg" caption="Into the green" />
            <ParallaxCard pill="Find your stillness" index="02" title="At your own pace."
              description="Nothing to rush. No perfect words to find."
              image="/images/still-water.jpg" caption="A moment of stillness" />
            <ParallaxCard pill="A fresh perspective" index="03" title="Space to be you."
              description="A new horizon for the things you want to say."
              image="/images/mountain-air.jpg" caption="A wider horizon" />
          </div>
        </section>

        {/* 05 / At Your Pace */}
        <section className="how section-wrap" id="how-it-works">
          <div className="section-index" data-reveal>
            <span>05 / AT YOUR PACE</span>
            <span>A LITTLE SUPPORT. ALL YOUR OWN WORDS.</span>
          </div>
          <div className="how-heading" data-reveal>
            <h2>
              A little closer
              <br />
              to <em>being understood.</em>
            </h2>
            <p>
              No rush. No perfect sentences needed.
              <br />
              Just you, one expression at a time.
            </p>
          </div>
          <div className="steps">
            {[
              [
                "01",
                "Make it yours.",
                "Choose your inputs, your language, and the voice that feels right. Turn permissions on when you’re ready.",
              ],
              [
                "02",
                "Let it take shape.",
                "Speak in pieces or add a gesture. Take your time. Your expressions come together as a message.",
              ],
              [
                "03",
                "Let your meaning through.",
                "Review the suggested words, make them your own, and choose what you want to say aloud.",
              ],
            ].map(([n, title, body]) => (
              <article className="step" data-reveal key={n}>
                <div className="step-top">
                  <span>{n}</span>
                  <span className="step-line" />
                  <span className="step-dot" />
                </div>
                <h3>{title}</h3>
                <p>{body}</p>
              </article>
            ))}
          </div>
        </section>

        {/* Closing Section */}
        <section className="closing" aria-labelledby="closing-heading">
          <div className="closing-glow" />
          <div className="closing-inner" data-reveal>
            <Flower />
            <span className="eyebrow">
              THE WORLD IS BETTER WITH YOU IN THE CONVERSATION.
            </span>
            <h2 id="closing-heading">
              A little connection.
              <br />
              <em>A beautiful beginning.</em>
            </h2>
            <a
              className="button button-cream"
              href={APP_URL}
              onClick={(e) => {
                e.preventDefault();
                window.location.hash = "#message";
                setInApp(true);
              }}
            >
              Enter your space{" "}
              <span className="button-icon">
                <ArrowUpRight size={18} />
              </span>
            </a>
            <p>Your words. Your rhythm. Your world.</p>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="footer">
        <a href="#home" className="brand">
          <Flower />
          <span>sampark.</span>
        </a>
        <span>Made with care. Made for connection.</span>
        <a href="#home">
          Back to the beginning <ArrowUpRight size={14} />
        </a>
      </footer>

      {/* Preview feedback */}
      <div
        className={`s-toast ${toastMessage ? "show" : ""}`}
        role="status"
        aria-live="polite"
      >
        {toastMessage}
      </div>
    </>
  );
}
