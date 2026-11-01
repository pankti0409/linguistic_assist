'use client'

import { AnimatePresence, MotionConfig, motion } from 'motion/react'
import {
  Activity, Camera, Ellipsis, FileText, HeartHandshake, History, KeyRound, Moon,
  ShieldCheck, Sun, UserRound, WifiOff, X,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Toaster } from 'sonner'

import { BackendProvider, useBackend } from '@/lib/backend'
import { cn } from '@/lib/utils'

import { CameraScreen } from './screens/camera'
import { InsightsScreen } from './screens/insights'
import { MessageScreen } from './screens/message'
import { PartnerScreen } from './screens/partner'
import { SetupScreen } from './screens/setup'
import { WordsScreen } from './screens/words'
import { Badge, Button, Dot, Segmented } from './ui/kit'

type Screen = 'message' | 'partner' | 'camera' | 'words' | 'setup' | 'insights'

const NAV: { id: Screen; label: string; short: string; icon: typeof Activity; primary?: boolean }[] = [
  { id: 'message', label: 'My message', short: 'Message', icon: HeartHandshake, primary: true },
  { id: 'partner', label: 'Partner', short: 'Partner', icon: UserRound, primary: true },
  { id: 'camera', label: 'Camera & gestures', short: 'Camera', icon: Camera, primary: true },
  { id: 'words', label: 'My words', short: 'Words', icon: FileText, primary: true },
  { id: 'setup', label: 'Setup & permissions', short: 'Setup', icon: ShieldCheck },
  { id: 'insights', label: 'Insights', short: 'Insights', icon: Activity },
]
const SCREENS = NAV.map((n) => n.id)

export default function PS16App({ onLanding }: { onLanding?: () => void }) {
  return (
    <BackendProvider>
      <MotionConfig reducedMotion="user">
        <Shell onLanding={onLanding} />
      </MotionConfig>
    </BackendProvider>
  )
}

function useTheme() {
  const [theme, setThemeState] = useState<'light' | 'dark'>('light')
  useEffect(() => { setThemeState(document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light') }, [])
  const setTheme = useCallback((t: 'light' | 'dark') => {
    setThemeState(t)
    document.documentElement.dataset.themeSwitching = 'true'
    document.documentElement.dataset.theme = t
    requestAnimationFrame(() => requestAnimationFrame(() => { delete document.documentElement.dataset.themeSwitching }))
    try {
      localStorage.setItem('ps16.theme', JSON.stringify(t))
      localStorage.setItem('sampark.scene', t)
    } catch { /* storage blocked */ }
  }, [])
  return { theme, setTheme }
}

function Shell({ onLanding }: { onLanding?: () => void }) {
  const b = useBackend()
  const [screen, setScreen] = useState<Screen>('message')
  const [more, setMore] = useState(false)
  const [log, setLog] = useState(false)
  const { theme, setTheme } = useTheme()

  useEffect(() => {
    const read = () => {
      const h = window.location.hash.slice(1) as Screen
      if (SCREENS.includes(h)) setScreen(h)
    }
    read()
    window.addEventListener('hashchange', read)
    return () => window.removeEventListener('hashchange', read)
  }, [])
  const go = useCallback((s: string) => {
    if (!SCREENS.includes(s as Screen)) return
    setScreen(s as Screen); setMore(false)
    if (window.location.hash !== `#${s}`) history.pushState(null, '', `#${s}`)
    window.scrollTo({ top: 0 })
  }, [])

  return (
    <div className="min-h-dvh bg-paper ps16-app">
      <a href="#main" onClick={(event) => { event.preventDefault(); document.getElementById('main')?.focus() }} className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-lg focus:bg-panel focus:px-4 focus:py-2 focus:font-bold">
        Skip to content
      </a>
      <Header onLog={() => setLog(true)} theme={theme} setTheme={setTheme} go={go} onLanding={onLanding} />
      <ConnectionBanner go={go} />
      <div className="flex">
        <nav aria-label="Main" className="app-sidebar sticky top-[73px] hidden h-[calc(100dvh-73px)] w-60 shrink-0 flex-col border-r border-line bg-rail px-4 py-8 lg:flex">
          <p className="app-nav-caption px-3 pb-4 text-[10px] font-semibold uppercase tracking-[0.18em] text-muted">Your personal space</p>
          <ul className="grid grid-cols-1 gap-1">
            {NAV.map(({ id, label, icon: Icon }) => (
              <li key={id}>
                <button
                  onClick={() => go(id)}
                  aria-current={screen === id ? 'page' : undefined}
                  className={cn(
                    'app-nav-item flex h-12 w-full items-center gap-3 rounded-2xl px-3 text-left text-[14px] transition-colors',
                    screen === id ? 'bg-panel font-bold text-ink shadow-card' : 'text-ink-soft hover:bg-panel/70 hover:text-ink',
                  )}
                >
                  <Icon className={cn('size-5', screen === id ? 'text-sage-ink' : '')} aria-hidden />{label}
                </button>
              </li>
            ))}
          </ul>
          <div className="mt-auto grid grid-cols-1 gap-4 pt-8">
            <div className="app-privacy-note rounded-2xl border border-line p-4">
              <ShieldCheck className="mb-3 size-5 text-sage-ink" aria-hidden />
              <p className="text-[13px] font-semibold text-ink">A space you can trust.</p>
              <p className="mt-1.5 text-xs leading-relaxed text-muted">Video and audio stay in memory and are never saved.</p>
            </div>
            <Button variant="secondary" size="sm" onClick={() => setLog(true)} className="justify-start">
              <History className="size-4" aria-hidden /> Event log
              <span className="ml-auto text-muted tabular">{b.events.length}</span>
            </Button>
          </div>
        </nav>

        <main id="main" tabIndex={-1} className="app-main min-w-0 flex-1 px-4 pb-28 pt-7 sm:px-7 lg:px-10 lg:pb-12 lg:pt-10">
          <AnimatePresence mode="popLayout" initial={false}>
            <motion.div
              key={screen}
              className="mx-auto w-full max-w-[1440px]"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, transition: { duration: 0.1 } }}
              transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            >
              {screen === 'message' && <MessageScreen go={go} />}
              {screen === 'partner' && <PartnerScreen />}
              {screen === 'camera' && <CameraScreen />}
              {screen === 'words' && <WordsScreen />}
              {screen === 'setup' && <SetupScreen theme={theme} setTheme={setTheme} />}
              {screen === 'insights' && <InsightsScreen />}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>

      <BottomNav screen={screen} go={go} more={more} setMore={setMore} />
      <EventLog open={log} onClose={() => setLog(false)} />
      <Toaster position="top-center" richColors closeButton toastOptions={{ className: 'font-sans' }} />
    </div>
  )
}

const STATE_LABEL: Record<string, string> = {
  IDLE: 'Ready', CAPTURING: 'Listening', FUSING: 'Thinking', AWAITING_CONFIRM: 'Waiting for you',
  SPEAKING: 'Speaking', EDITING: 'Editing', REJECTED: 'Cleared', CLARIFY: 'Answering',
}

function Header({ onLog, theme, setTheme, go, onLanding }: { onLog: () => void; theme: 'light' | 'dark'; setTheme: (t: 'light' | 'dark') => void; go: (s: string) => void; onLanding?: () => void }) {
  const b = useBackend()
  const st = b.turn.state
  const tone = st === 'CAPTURING' ? 'butter' : st === 'SPEAKING' ? 'sage' : st === 'AWAITING_CONFIRM' ? 'lavender' : 'neutral'
  const linkLabel = { live: 'Connected', connecting: 'Connecting…', offline: 'Backend offline', locked: 'Token needed' }[b.link]
  return (
    <header className="app-header sticky top-0 z-30 flex h-[73px] items-center gap-3 border-b border-line bg-paper/90 px-4 backdrop-blur-md sm:px-6">
      <button onClick={() => go('message')} className="flex items-center gap-2.5 rounded-xl text-left" aria-label="Sampark, go to My message">
        <span className="app-emblem grid grid-cols-1 size-10 place-items-center rounded-2xl bg-lavender text-lavender-ink"><svg className="size-6" viewBox="0 0 48 48" aria-hidden="true"><g transform="translate(24 24)" fill="currentColor">{Array.from({ length: 8 }, (_, i) => <ellipse key={i} cy="-10" rx="3.5" ry="9" transform={`rotate(${i * 45})`} />)}<circle r="3.5" /></g></svg></span>
        <span className="hidden sm:block">
          <span className="block text-xl font-semibold leading-none tracking-[-0.06em]">sampark<span className="text-sage-ink">.</span></span>
          <span className="mt-1 block text-[10px] tracking-[0.02em] text-muted">Connection, at your pace</span>
        </span>
      </button>
      {onLanding && (
        <Button variant="secondary" size="sm" onClick={onLanding} className="text-xs font-semibold">
          ← Landing
        </Button>
      )}
      <Badge tone={tone} className="ml-1">
        <Dot tone={tone === 'neutral' ? 'muted' : tone === 'butter' ? 'butter' : tone === 'sage' ? 'sage' : 'lavender'} pulse={st === 'CAPTURING' || st === 'SPEAKING'} />
        {b.turn.speaker === 'PARTNER' && st === 'CAPTURING' ? 'Partner speaking' : STATE_LABEL[st] ?? st}
      </Badge>
      <div className="ml-auto flex items-center gap-2 sm:gap-3">
        <span className="hidden items-center gap-2 text-sm text-muted md:flex" role="status">
          <Dot tone={b.link === 'live' ? 'sage' : b.link === 'connecting' ? 'butter' : 'blush'} />{linkLabel}
        </span>
        {b.voice?.selected && (
          <div className="hidden sm:block">
            <Segmented label="Voice" size="sm" value={b.voice.selected} onChange={(g) => b.setVoice(g)}
              options={b.voice.voices.map((v) => ({ value: v.gender, label: v.gender === 'female' ? 'Female voice' : 'Male voice', disabled: !v.configured }))} />
          </div>
        )}
        <Button variant="quiet" size="sm" aria-label={theme === 'dark' ? 'Use light theme' : 'Use dark theme'} onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
          {theme === 'dark' ? <Sun className="size-5" aria-hidden /> : <Moon className="size-5" aria-hidden />}
        </Button>
        <Button variant="quiet" size="sm" aria-label="Open event log" onClick={onLog} className="lg:hidden"><History className="size-5" aria-hidden /></Button>
      </div>
    </header>
  )
}

function ConnectionBanner({ go }: { go: (s: string) => void }) {
  const b = useBackend()
  if (b.link === 'live' || b.link === 'connecting') return null
  return (
    <div role="alert" className="app-connection-banner flex flex-wrap items-center gap-3 border-b border-blush-ink/20 bg-blush px-4 py-3 text-blush-ink sm:px-6">
      {b.link === 'locked' ? <KeyRound className="size-5" aria-hidden /> : <WifiOff className="size-5" aria-hidden />}
      <p className="min-w-0 flex-1 text-sm">
        {b.link === 'locked'
          ? 'An access token is needed to connect your space. Add it in Setup & permissions.'
          : 'Your communication service is offline. Your space will reconnect automatically when it is available.'}
      </p>
      {b.link === 'locked'
        ? <Button size="sm" variant="secondary" onClick={() => go('setup')}>Enter token</Button>
        : <Button size="sm" variant="secondary" onClick={() => b.refresh()}>Try now</Button>}
    </div>
  )
}

function BottomNav({ screen, go, more, setMore }: { screen: Screen; go: (s: string) => void; more: boolean; setMore: (v: boolean) => void }) {
  const primary = NAV.filter((n) => n.primary)
  const rest = NAV.filter((n) => !n.primary)
  return (
    <>
      <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-panel/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-md lg:hidden">
        <ul className="grid grid-cols-5">
          {primary.map(({ id, short, icon: Icon }) => (
            <li key={id}>
              <button onClick={() => go(id)} aria-current={screen === id ? 'page' : undefined}
                className={cn('flex h-16 w-full flex-col items-center justify-center gap-1 text-[11px] font-bold', screen === id ? 'text-sage-ink' : 'text-muted')}>
                <Icon className="size-5" aria-hidden />{short}
              </button>
            </li>
          ))}
          <li>
            <button onClick={() => setMore(!more)} aria-expanded={more}
              className={cn('flex h-16 w-full flex-col items-center justify-center gap-1 text-[11px] font-bold', rest.some((r) => r.id === screen) ? 'text-sage-ink' : 'text-muted')}>
              <Ellipsis className="size-5" aria-hidden />More
            </button>
          </li>
        </ul>
      </nav>
      <AnimatePresence>
        {more && (
          <motion.div className="fixed inset-0 z-40 lg:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <button className="absolute inset-0 bg-ink/30" aria-label="Close menu" onClick={() => setMore(false)} />
            <motion.ul
              initial={{ y: 40, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 40, opacity: 0, transition: { duration: 0.12 } }}
              transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
              className="absolute inset-x-3 bottom-20 grid grid-cols-1 gap-1 rounded-2xl border border-line bg-panel p-2 shadow-lift"
            >
              {rest.map(({ id, label, icon: Icon }) => (
                <li key={id}>
                  <button onClick={() => go(id)} className={cn('flex h-12 w-full items-center gap-3 rounded-xl px-3 font-bold', screen === id ? 'bg-sage text-sage-ink' : 'hover:bg-rail')}>
                    <Icon className="size-5" aria-hidden />{label}
                  </button>
                </li>
              ))}
            </motion.ul>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  )
}

function EventLog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const b = useBackend()
  const [filter, setFilter] = useState<'all' | 'turn' | 'vision' | 'output'>('all')
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])
  const groups: Record<string, string[]> = {
    turn: ['turn.state', 'fragment.added', 'draft.updated', 'fusion.candidates', 'fusion.question', 'speech.final', 'speech.partial', 'confirm.issued'],
    vision: ['camera.status', 'mouth.activity', 'gesture.token', 'gesture.word', 'lip.result'],
    output: ['tts.started', 'output.fallback', 'avatar.speaking', 'avatar.guardrail', 'error'],
  }
  const list = filter === 'all' ? b.events : b.events.filter((e) => groups[filter].includes(e.type))
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-50" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          <button className="absolute inset-0 bg-ink/30" aria-label="Close event log" onClick={onClose} />
          <motion.aside
            role="dialog" aria-modal="true" aria-labelledby="log-title"
            initial={{ x: 40, opacity: 0 }} animate={{ x: 0, opacity: 1 }} exit={{ x: 40, opacity: 0, transition: { duration: 0.12 } }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
            className="absolute inset-y-0 right-0 flex w-full max-w-lg flex-col border-l border-line bg-panel shadow-lift"
          >
            <div className="flex items-center gap-3 border-b border-line px-5 py-4">
              <h2 id="log-title" className="text-lg font-bold">Event log</h2>
              <Badge className="tabular">{list.length}</Badge>
              <Button size="sm" variant="quiet" className="ml-auto" onClick={b.clearEvents}>Clear</Button>
              <Button size="sm" variant="quiet" aria-label="Close" onClick={onClose} autoFocus><X className="size-5" aria-hidden /></Button>
            </div>
            <div className="border-b border-line px-5 py-3">
              <Segmented label="Filter events" size="sm" value={filter} onChange={setFilter}
                options={[{ value: 'all', label: 'All' }, { value: 'turn', label: 'Turn' }, { value: 'vision', label: 'Camera' }, { value: 'output', label: 'Output' }]} />
            </div>
            <ol className="flex-1 overflow-y-auto px-5 py-3 font-mono text-xs">
              {list.length === 0 && <li className="py-6 font-sans text-sm text-muted">No events yet. They stream in live from the backend.</li>}
              {list.map((e, i) => (
                <li key={`${e.ts_ms}-${i}`} className="border-b border-line py-2">
                  <div className="flex justify-between gap-3"><span className="font-bold text-ink">{e.type}</span><span className="text-muted tabular">{e.ts_ms}</span></div>
                  <pre className="mt-1 whitespace-pre-wrap break-words text-ink-soft">{JSON.stringify(e.data)}</pre>
                </li>
              ))}
            </ol>
            <p className="border-t border-line px-5 py-3 text-xs text-muted">Derived data only. Audio is shown as a size, never the content.</p>
          </motion.aside>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
