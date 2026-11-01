// HTTP client for the PS-16 backend. Requests go to /backend/*, which Vite proxies to
// the backend on 127.0.0.1, so the browser stays same-origin (the backend deliberately has no
// CORS). The WebSocket and the MJPEG preview go to the backend directly; both are allowed for
// loopback origins.

import type {
  AvatarSession, BackendConfig, ConfirmResult, ConsentRecord, DialogueTurn, Gender, Health,
  Language, Metrics, Modality, PhraseEntry, Purpose, Speaker, TurnView, VoiceState,
} from './types'

const envBackend =
  (typeof import.meta !== 'undefined' && import.meta.env?.VITE_BACKEND_URL) ||
  'http://127.0.0.1:8765'
export const BACKEND_URL = envBackend.replace(/\/$/, '')
const TOKEN_KEY = 'ps16.token'

export function getToken(): string {
  try { return localStorage.getItem(TOKEN_KEY) ?? '' } catch { return '' }
}
export function setToken(token: string) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch { /* storage blocked: token lives for this page only */ }
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public recoverable: boolean) {
    super(message)
  }
}

const UNREACHABLE = 'The backend is not reachable. Start scripts/run.sh (macOS/Linux) or scripts/run.ps1 (Windows), then try again.'

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken()
  let res: Response
  try {
    res = await fetch(`/backend${path}`, {
      ...init,
      headers: {
        ...(init.body ? { 'content-type': 'application/json' } : {}),
        ...(token ? { 'x-ps16-token': token } : {}),
        ...init.headers,
      },
      cache: 'no-store',
    })
  } catch {
    throw new ApiError(0, 'backend_unreachable', UNREACHABLE, true)
  }
  const text = await res.text()
  let body: unknown = null
  try { body = text ? JSON.parse(text) : null } catch { body = null }
  if (!res.ok) {
    const b = (body ?? {}) as { error_code?: string; message?: string; recoverable?: boolean }
    if (res.status >= 500 && !b.error_code) throw new ApiError(res.status, 'backend_unreachable', UNREACHABLE, true)
    throw new ApiError(res.status, b.error_code ?? `http_${res.status}`, b.message ?? res.statusText, b.recoverable ?? true)
  }
  return body as T
}

const post = <T,>(path: string, body?: unknown) =>
  call<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
const put = <T,>(path: string, body: unknown) => call<T>(path, { method: 'PUT', body: JSON.stringify(body) })
const del = <T,>(path: string) => call<T>(path, { method: 'DELETE' })

export const api = {
  health: () => call<Health>('/health'),
  config: () => call<BackendConfig>('/config'),
  consent: () => call<ConsentRecord[]>('/consent'),
  grant: (purpose: Purpose) => post<ConsentRecord>('/consent', { purpose }),
  revoke: (purpose: Purpose) => del<ConsentRecord>(`/consent/${purpose}`),
  voice: () => call<VoiceState>('/voice'),
  setVoice: (gender: Gender) => put<VoiceState>('/voice', { gender }),
  turn: () => call<TurnView>('/turn'),
  start: (speaker: Speaker, modalities: Modality[], language_pref: Language) =>
    post<TurnView>('/turn/start', { speaker, modalities, language_pref }),
  end: (turn_id?: string | null) => post<TurnView>('/turn/end', { turn_id: turn_id ?? null }),
  confirm: (turn_id: string, body: { choice_index?: number; edited_text?: string }) =>
    post<ConfirmResult>('/turn/confirm', { turn_id, ...body }),
  // no body: the backend replays the text the patient already confirmed (R2)
  replay: () => post<ConfirmResult>('/turn/replay'),
  reject: (turn_id?: string | null) => post<TurnView>('/turn/reject', { turn_id: turn_id ?? null }),
  clarify: (answer: string, turn_id?: string | null) =>
    post<TurnView>('/turn/clarify', { answer, turn_id: turn_id ?? null }),
  context: () => call<DialogueTurn[]>('/context'),
  terms: () => call<string[]>('/profile/terms'),
  setTerms: (terms: string[]) => put<string[]>('/profile/terms', terms),
  phrasebook: () => call<PhraseEntry[]>('/phrasebook'),
  wipePhrasebook: () => del<{ deleted: number }>('/phrasebook'),
  lexicon: () => call<Record<string, string>>('/gesture/lexicon'),
  setLexicon: (map: Record<string, string>) => put<Record<string, string>>('/gesture/lexicon', map),
  calibrate: (word: string) => post<{ token: string; word: string }>('/gesture/calibrate', { word }),
  avatarSession: () => call<AvatarSession>('/avatar/session'),
  startAvatar: () => post<AvatarSession>('/avatar/session'),
  endAvatar: () => del<{ ended: boolean }>('/avatar/session'),
  metrics: () => call<Metrics>('/metrics'),
}

export function previewUrl(nonce: number): string {
  const token = getToken()
  const q = new URLSearchParams({ n: String(nonce) })
  if (token) q.set('token', token)
  return `${BACKEND_URL}/camera/preview.mjpg?${q}`
}

export function wsUrl(): string {
  const token = getToken()
  return `${BACKEND_URL.replace(/^http/, 'ws')}/ws${token ? `?token=${encodeURIComponent(token)}` : ''}`
}

export function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.message
  return e instanceof Error ? e.message : 'Something went wrong.'
}
