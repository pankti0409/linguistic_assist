'use client'

// One live connection to the backend: polls /health, keeps consent / voice / turn / context in
// sync, and turns WebSocket events into UI state. Every screen reads from here.

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'

import { api, ApiError, errorText, wsUrl } from './api'
import type {
  BackendConfig, BackendEvent, ConsentRecord, DialogueTurn, Fragment, Gender, Health, Language,
  LipResult, Modality, MouthActivity, Purpose, Speaker, TurnView, VoiceState,
} from './types'

export type Link = 'connecting' | 'live' | 'offline' | 'locked'

export interface GestureSeen { token: string; word: string | null; score: number; at: number }
export interface SpeechLine { speaker: Speaker; text: string; confidence: number | null; at: number }
export interface Spoken { text: string; tier: string | null; subtitles: string | null; playing: boolean; at: number }

interface Ctx {
  link: Link
  health: Health | null
  config: BackendConfig | null
  consent: Record<Purpose, boolean>
  voice: VoiceState | null
  context: DialogueTurn[]
  turn: TurnView
  draft: { fragments: Fragment[]; cleaned: string[] }
  lastActivity: number | null
  question: { text: string; round: number } | null
  spoken: Spoken | null
  fallbackReason: string | null
  avatarSpeaking: boolean
  camera: { ok: boolean; detail: string } | null
  mouth: MouthActivity | null
  gesture: GestureSeen | null
  lip: LipResult | null
  speech: SpeechLine | null
  events: BackendEvent[]
  language: Language
  modalities: Modality[]
  busy: string | null
  setLanguage: (l: Language) => void
  setModalities: (m: Modality[]) => void
  refresh: () => Promise<void>
  refreshTurn: () => Promise<void>
  refreshContext: () => Promise<void>
  setConsent: (p: Purpose, on: boolean) => Promise<boolean>
  setVoice: (g: Gender) => Promise<void>
  startTurn: (speaker: Speaker) => Promise<void>
  endTurn: () => Promise<void>
  confirm: (body: { choice_index?: number; edited_text?: string }) => Promise<{ needsReconfirm: boolean; finalText?: string } | null>
  reject: () => Promise<void>
  clarify: (answer: string) => Promise<void>
  clearEvents: () => void
}

const BackendCtx = createContext<Ctx | null>(null)

const IDLE: TurnView = { turn_id: null, state: 'IDLE' }
const NO_CONSENT: Record<Purpose, boolean> = {
  camera: false, microphone: false, voice_clone: false, avatar: false, personalization: false,
}
const MAX_EVENTS = 400

function stored<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key)
    return v ? (JSON.parse(v) as T) : fallback
  } catch { return fallback }
}
function store(key: string, value: unknown) {
  try { localStorage.setItem(key, JSON.stringify(value)) } catch { /* storage blocked */ }
}

export function BackendProvider({ children }: { children: React.ReactNode }) {
  const [link, setLink] = useState<Link>('connecting')
  const [health, setHealth] = useState<Health | null>(null)
  const [config, setConfig] = useState<BackendConfig | null>(null)
  const [consent, setConsentMap] = useState(NO_CONSENT)
  const [voice, setVoiceState] = useState<VoiceState | null>(null)
  const [context, setContext] = useState<DialogueTurn[]>([])
  const [turn, setTurn] = useState<TurnView>(IDLE)
  const [draft, setDraft] = useState<{ fragments: Fragment[]; cleaned: string[] }>({ fragments: [], cleaned: [] })
  const [lastActivity, setLastActivity] = useState<number | null>(null)
  const [question, setQuestion] = useState<{ text: string; round: number } | null>(null)
  const [spoken, setSpoken] = useState<Spoken | null>(null)
  const [fallbackReason, setFallbackReason] = useState<string | null>(null)
  const [avatarSpeaking, setAvatarSpeaking] = useState(false)
  const [camera, setCamera] = useState<{ ok: boolean; detail: string } | null>(null)
  const [mouth, setMouth] = useState<MouthActivity | null>(null)
  const [gesture, setGesture] = useState<GestureSeen | null>(null)
  const [lip, setLip] = useState<LipResult | null>(null)
  const [speech, setSpeech] = useState<SpeechLine | null>(null)
  const [events, setEvents] = useState<BackendEvent[]>([])
  const [language, setLanguageState] = useState<Language>('en')
  const [modalities, setModalitiesState] = useState<Modality[]>(['speech', 'gesture'])
  const [busy, setBusy] = useState<string | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const turnRef = useRef(turn)
  turnRef.current = turn

  useEffect(() => {
    setLanguageState(stored<Language>('ps16.language', 'en'))
    setModalitiesState(stored<Modality[]>('ps16.modalities', ['speech', 'gesture']))
  }, [])
  const setLanguage = useCallback((l: Language) => { setLanguageState(l); store('ps16.language', l) }, [])
  const setModalities = useCallback((m: Modality[]) => { setModalitiesState(m); store('ps16.modalities', m) }, [])

  const handleError = useCallback((e: unknown) => {
    if (e instanceof ApiError && e.code === 'unauthorized') setLink('locked')
    toast.error(errorText(e))
  }, [])

  const refreshTurn = useCallback(async () => {
    try {
      const t = await api.turn()
      setTurn(t.turn_id ? t : IDLE)
      if (t.fragments) setDraft({ fragments: t.fragments, cleaned: t.cleaned_fragments ?? [] })
      const q = t.result?.clarification_required ? t.result.clarifying_question : null
      setQuestion(q ? { text: q, round: (t.clarify_rounds ?? 0) + 1 } : null)
    } catch { /* surfaced by health */ }
  }, [])

  const refreshContext = useCallback(async () => {
    try { setContext(await api.context()) } catch { /* surfaced by health */ }
  }, [])

  const refresh = useCallback(async () => {
    try {
      const [h, cfg, c, v] = await Promise.all([api.health(), api.config(), api.consent(), api.voice()])
      setHealth(h); setConfig(cfg); setVoiceState(v)
      setConsentMap(Object.fromEntries(c.map((r: ConsentRecord) => [r.purpose, r.granted])) as Record<Purpose, boolean>)
      setLink((l) => (l === 'locked' || l === 'offline' ? 'connecting' : l))
      await Promise.all([refreshTurn(), refreshContext()])
    } catch (e) {
      if (e instanceof ApiError && e.code === 'unauthorized') setLink('locked')
      else setLink('offline')
    }
  }, [refreshTurn, refreshContext])

  // health poll (cheap, keeps the service list honest)
  useEffect(() => {
    refresh()
    const id = window.setInterval(async () => {
      try { setHealth(await api.health()) } catch { setLink((l) => (l === 'locked' ? l : 'offline')) }
    }, 5000)
    return () => window.clearInterval(id)
  }, [refresh])

  const playAudio = useCallback((b64: string, text: string, tier: string | null) => {
    try {
      audioRef.current?.pause()
      const audio = new Audio(`data:audio/mpeg;base64,${b64}`)
      audioRef.current = audio
      setSpoken({ text, tier, subtitles: text, playing: true, at: Date.now() })
      audio.onended = () => setSpoken((s) => (s ? { ...s, playing: false } : s))
      audio.play().catch((err: unknown) => {
        setSpoken((s) => (s ? { ...s, playing: false } : s))
        if (err instanceof DOMException && err.name === 'NotAllowedError') {
          toast.message('Tap “Play again” to hear the message', { description: 'The browser blocked autoplay.' })
        } else {
          toast.error('This device could not play the audio', { description: 'The subtitles show what was said.' })
        }
      })
    } catch { /* subtitles still show */ }
  }, [])

  useEffect(() => {
    const replay = () => {
      const a = audioRef.current
      if (!a) return
      a.currentTime = 0
      setSpoken((s) => (s ? { ...s, playing: true } : s))
      a.play().catch(() => setSpoken((s) => (s ? { ...s, playing: false } : s)))
    }
    window.addEventListener('ps16:replay', replay)
    return () => window.removeEventListener('ps16:replay', replay)
  }, [])

  const onEvent = useCallback((ev: BackendEvent) => {
    const d = ev.data as Record<string, unknown>
    const safe = 'audio_b64' in d ? { ...ev, data: { ...d, audio_b64: `[${String(d.audio_b64).length} chars]` } } : ev
    setEvents((list) => [safe, ...list].slice(0, MAX_EVENTS))
    switch (ev.type) {
      case 'turn.state': {
        const state = d.state as TurnView['state']
        setTurn((t) => ({ ...t, turn_id: (d.turn_id as string) ?? t.turn_id, speaker: d.speaker as Speaker, state }))
        if (state === 'CAPTURING' && turnRef.current.state === 'IDLE') {
          setDraft({ fragments: [], cleaned: [] }); setQuestion(null); setFallbackReason(null)
          setLastActivity(Date.now())
        }
        if (state === 'IDLE') { refreshContext(); refreshTurn() }
        break
      }
      case 'fragment.added': setLastActivity(Date.now()); break
      case 'draft.updated':
        setDraft({ fragments: (d.fragments as Fragment[]) ?? [], cleaned: (d.cleaned as string[]) ?? [] })
        break
      case 'fusion.candidates': refreshTurn(); break
      case 'fusion.question': setQuestion({ text: String(d.question), round: Number(d.round) || 1 }); break
      case 'confirm.issued': setSpoken({ text: String(d.text), tier: null, subtitles: null, playing: false, at: Date.now() }); break
      case 'tts.started':
        if (typeof d.audio_b64 === 'string') playAudio(d.audio_b64, String(d.subtitles ?? ''), String(d.tier ?? 'local'))
        else setSpoken({ text: String(d.subtitles ?? ''), tier: String(d.tier ?? ''), subtitles: String(d.subtitles ?? ''), playing: true, at: Date.now() })
        break
      case 'output.fallback': setFallbackReason(String(d.reason ?? '')); break
      case 'avatar.speaking':
        setAvatarSpeaking(Boolean(d.speaking))
        if (!d.speaking) setSpoken((s) => (s ? { ...s, playing: false } : s))
        break
      case 'avatar.guardrail': toast.warning('Avatar guardrail triggered', { description: String(d.guardrail_name ?? d.event_type ?? '') }); break
      case 'camera.status': setCamera({ ok: Boolean(d.ok), detail: String(d.detail ?? '') }); break
      case 'mouth.activity': setMouth(d as unknown as MouthActivity); break
      case 'gesture.token': setGesture({ token: String(d.token), word: null, score: Number(d.score), at: Date.now() }); break
      case 'gesture.word':
        setGesture({ token: String(d.token), word: String(d.word), score: Number(d.score), at: Date.now() })
        break
      case 'lip.result': setLip(d as unknown as LipResult); break
      case 'speech.final':
        setSpeech({ speaker: d.speaker as Speaker, text: String(d.text ?? ''), confidence: (d.confidence as number) ?? null, at: Date.now() })
        setLastActivity(Date.now())
        break
      case 'error': toast.error(`${String(d.source ?? 'Backend')} problem`, { description: String(d.error ?? 'Unknown error') }); break
    }
  }, [playAudio, refreshContext, refreshTurn])

  // WebSocket with reconnect + backoff
  const onEventRef = useRef(onEvent)
  onEventRef.current = onEvent
  useEffect(() => {
    let ws: WebSocket | null = null
    let tries = 0
    let timer: number | undefined
    let closed = false
    const connect = () => {
      setLink((l) => (l === 'locked' ? l : 'connecting'))
      ws = new WebSocket(wsUrl())
      ws.onopen = () => { tries = 0; setLink('live'); refresh() }
      ws.onmessage = (m) => { try { onEventRef.current(JSON.parse(m.data)) } catch { /* ignore malformed */ } }
      ws.onclose = () => {
        if (closed) return
        // a single drop is usually a blip: say "connecting" first, "offline" only after retries fail
        setLink((l) => (l === 'locked' ? l : tries >= 2 ? 'offline' : 'connecting'))
        tries += 1
        timer = window.setTimeout(connect, Math.min(8000, 500 * 2 ** tries))
      }
    }
    connect()
    const reconnect = () => { ws?.close() }
    window.addEventListener('ps16:token', reconnect)
    return () => {
      closed = true
      window.removeEventListener('ps16:token', reconnect)
      window.clearTimeout(timer)
      ws?.close()
    }
  }, [refresh])

  const run = useCallback(async <T,>(label: string, fn: () => Promise<T>): Promise<T | null> => {
    setBusy(label)
    try { return await fn() } catch (e) { handleError(e); return null } finally { setBusy(null) }
  }, [handleError])

  const setConsent = useCallback(async (p: Purpose, on: boolean) => {
    const r = await run(`consent:${p}`, () => (on ? api.grant(p) : api.revoke(p)))
    if (r) { setConsentMap((m) => ({ ...m, [p]: r.granted })); window.setTimeout(refresh, 600) }
    return Boolean(r)
  }, [refresh, run])

  const setVoice = useCallback(async (g: Gender) => {
    const v = await run('voice', () => api.setVoice(g))
    if (v) setVoiceState(v)
  }, [run])

  const startTurn = useCallback(async (speaker: Speaker) => {
    const mods = speaker === 'PARTNER' ? (['speech'] as Modality[]) : modalities
    const t = await run('start', () => api.start(speaker, mods, language))
    if (t) {
      setTurn(t); setDraft({ fragments: [], cleaned: [] }); setQuestion(null); setSpoken(null)
      setFallbackReason(null); setLastActivity(Date.now())
    }
  }, [language, modalities, run])

  const endTurn = useCallback(async () => {
    const t = await run('end', () => api.end(turnRef.current.turn_id))
    if (t) { setTurn(t); if (t.speaker === 'PARTNER') refreshContext(); else refreshTurn() }
  }, [refreshContext, refreshTurn, run])

  const confirm = useCallback(async (body: { choice_index?: number; edited_text?: string }) => {
    const id = turnRef.current.turn_id
    if (!id) return null
    const r = await run('confirm', () => api.confirm(id, body))
    if (!r) { refreshTurn(); return null }
    if (r.confirm_required) { refreshTurn(); return { needsReconfirm: true, finalText: r.final_text } }
    return { needsReconfirm: false, finalText: r.final_text }
  }, [refreshTurn, run])

  const reject = useCallback(async () => {
    const t = await run('reject', () => api.reject(turnRef.current.turn_id))
    if (t) { setTurn(IDLE); setDraft({ fragments: [], cleaned: [] }); setQuestion(null) }
  }, [run])

  const clarify = useCallback(async (answer: string) => {
    const t = await run('clarify', () => api.clarify(answer, turnRef.current.turn_id))
    if (t) { setTurn(t); setDraft({ fragments: t.fragments ?? [], cleaned: t.cleaned_fragments ?? [] }) }
  }, [run])

  const value = useMemo<Ctx>(() => ({
    link, health, config, consent, voice, context, turn, draft, lastActivity, question, spoken,
    fallbackReason, avatarSpeaking, camera, mouth, gesture, lip, speech, events, language,
    modalities, busy, setLanguage, setModalities, refresh, refreshTurn, refreshContext,
    setConsent, setVoice, startTurn, endTurn, confirm, reject, clarify,
    clearEvents: () => setEvents([]),
  }), [link, health, config, consent, voice, context, turn, draft, lastActivity, question, spoken,
    fallbackReason, avatarSpeaking, camera, mouth, gesture, lip, speech, events, language,
    modalities, busy, setLanguage, setModalities, refresh, refreshTurn, refreshContext,
    setConsent, setVoice, startTurn, endTurn, confirm, reject, clarify])

  return <BackendCtx.Provider value={value}>{children}</BackendCtx.Provider>
}

export function useBackend(): Ctx {
  const c = useContext(BackendCtx)
  if (!c) throw new Error('useBackend outside BackendProvider')
  return c
}
