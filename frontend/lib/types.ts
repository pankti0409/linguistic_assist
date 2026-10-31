// Mirrors app/schemas.py and the route payloads of the PS-16 backend.

export type Speaker = 'PATIENT' | 'PARTNER'
export type Modality = 'speech' | 'gesture' | 'lip'
export type Language = 'en' | 'hi' | 'mixed' | 'auto'
export type FragmentFlag = 'low_confidence' | 'repeat' | 'stutter_prefix' | 'filler' | 'answer_to_question'
export type TurnState =
  | 'IDLE' | 'CAPTURING' | 'FUSING' | 'AWAITING_CONFIRM' | 'SPEAKING' | 'EDITING' | 'REJECTED' | 'CLARIFY'
export type Purpose = 'camera' | 'microphone' | 'voice_clone' | 'avatar' | 'personalization'
export type Gender = 'male' | 'female'

export interface Fragment {
  id: number
  ts_ms: number
  gap_ms: number
  source: 'speech' | 'gesture' | 'lip'
  text: string
  is_final: boolean
  confidence: number | null
  flags: FragmentFlag[]
}

export interface Candidate {
  text: string
  covers: number[]
  added_words: string[]
}

export interface FusionResult {
  intent: string
  candidates: Candidate[]
  unexplained_fragment_ids: number[]
  clarifying_question: string | null
  clarification_required: boolean
  reasoning_summary: string
}

export interface TurnView {
  turn_id: string | null
  speaker?: Speaker
  state: TurnState
  modalities?: Modality[]
  language_pref?: Language
  fragments?: Fragment[]
  cleaned_fragments?: string[]
  result?: FusionResult | null
  fallback?: { text: string; prompt: string } | null
  clarify_rounds?: number
  pending_edit?: string | null
  final_text?: string | null
  raw_transcripts?: string[]
  end_reason?: string | null
  spoken?: { tier: string } | null
}

export interface ConfirmResult {
  turn_id: string
  state: TurnState
  final_text: string
  confirm_required?: boolean
  spoken?: { tier: string; voice_gender: Gender; voice_kind: string }
}

export interface ServiceHealth {
  status: 'ok' | 'degraded' | 'unavailable'
  detail: string
  configured: boolean | null
  backend: 'real' | 'fake' | 'none'
}

export interface Health {
  simulate: boolean
  services: Record<string, ServiceHealth>
  avatar_mode: string
  limits: Record<string, string[]>
}

export interface ConsentRecord {
  purpose: Purpose
  granted: boolean
  ts_ms: number | null
}

export interface VoiceState {
  selected: Gender | null
  voices: { gender: Gender; configured: boolean; voice_id: string | null }[]
  voice_kind: string
}

export interface DialogueTurn {
  speaker: Speaker
  text: string
  ts_ms: number
}

export interface PhraseEntry {
  text: string
  uses: number
  last_used_ms: number
}

export interface BackendConfig {
  fragment_silence_s: number
  fragment_max_s: number
  turn_max_s: number
  max_clarify_rounds: number
  confirm_ttl_s: number
  context_turns: number
  calibrate_timeout_s: number
  lip_enabled: boolean
  debug_preview: boolean
  simulate: boolean
  avatar_mode: string
  avatar_audio_echo: boolean
  token_required: boolean
  languages: Language[]
}

export interface TurnSummary {
  turn_id: string
  speaker: Speaker
  stages: Record<string, number>
  tier: string | null
  taps: number
  edits: number
  clarify_rounds: number
}

export interface Metrics {
  turns: TurnSummary[]
  counters: Record<string, number>
  summary: Record<string, { n: number; p50: number | null; p95: number | null }>
}

export interface AvatarSession {
  conversation_id: string | null
  conversation_url: string | null
  join_settings: { camera: boolean; microphone: boolean }
  synthetic: boolean
  disclosure: string
}

export interface BackendEvent<T = Record<string, unknown>> {
  type: string
  ts_ms: number
  data: T
}

export interface MouthActivity {
  active: boolean
  changed: boolean
  face_present: boolean
  level: number
  yaw_deg: number | null
  pitch_deg: number | null
  obs_ts_ms: number
  lag_ms: number
}

export interface LipResult {
  status: 'ok' | 'insufficient_visual_evidence' | 'unavailable'
  text: string | null
  score: number | null
  frames: number
  reason: string | null
}
