'use client'

import { AnimatePresence, LayoutGroup, motion } from 'motion/react'
import {
  ArrowRight, Check, CircleAlert, Ear, Hand, Mic, MicOff, Pencil, RotateCcw, ScanFace, Square,
  ThumbsDown, ThumbsUp, Volume2, Waves, X,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { api } from '@/lib/api'
import { useBackend } from '@/lib/backend'
import type { Candidate, Fragment, Modality } from '@/lib/types'
import { cn } from '@/lib/utils'

import { CameraView, prettyToken } from '../camera-view'
import { Badge, Button, Panel, Segmented } from '../ui/kit'

const EASE = [0.16, 1, 0.3, 1] as const

export function MessageScreen({ go }: { go: (s: string) => void }) {
  const b = useBackend()
  const { turn } = b
  const partnerTurn = turn.speaker === 'PARTNER' && turn.state === 'CAPTURING'
  const lastPartner = useMemo(() => [...b.context].reverse().find((t) => t.speaker === 'PARTNER'), [b.context])

  return (
    <div className="mx-auto grid grid-cols-1 max-w-[1320px] gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="grid grid-cols-1 min-w-0 content-start gap-5">
        <ContextBar line={lastPartner?.text} onPartner={() => go('partner')} />
        {partnerTurn ? (
          <Panel className="p-6">
            <p className="text-lg font-bold">Your partner is speaking</p>
            <p className="mt-1 text-muted">Their words become context for your next message. Finish their turn on the Partner screen.</p>
            <Button className="mt-4" onClick={() => go('partner')}>Open Partner <ArrowRight className="size-4" /></Button>
          </Panel>
        ) : (
          <>
            <SpokenBanner />
            <Composer />
            <Draft />
            <Decision />
          </>
        )}
      </div>
      <aside className="grid grid-cols-1 content-start gap-5">
        <Panel className="p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="font-bold">You, on camera</h2>
            <button className="text-sm font-bold text-sky-ink hover:underline" onClick={() => go('camera')}>Gestures</button>
          </div>
          <CameraView />
          <GestureHints />
        </Panel>
      </aside>
    </div>
  )
}

function ContextBar({ line, onPartner }: { line?: string; onPartner: () => void }) {
  return (
    <div className="flex items-center gap-4 rounded-2xl border border-sky-ink/15 bg-sky px-5 py-4">
      <span className="grid grid-cols-1 size-10 shrink-0 place-items-center rounded-xl bg-panel/70 text-sky-ink"><Ear className="size-5" aria-hidden /></span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-bold text-sky-ink">{line ? 'Your partner asked' : 'No question from your partner yet'}</p>
        <p className={cn('line-clamp-2 sm:truncate', line ? 'font-serif text-xl text-ink' : 'text-sm text-sky-ink')}>
          {line ? `“${line}”` : 'Their last question helps PS-16 understand short answers.'}
        </p>
      </div>
      <Button size="sm" variant="secondary" onClick={onPartner}>{line ? 'New question' : 'Record partner'}</Button>
    </div>
  )
}

const MODES: { value: Modality; label: string; icon: typeof Mic; needs: 'microphone' | 'camera' }[] = [
  { value: 'speech', label: 'Speech', icon: Mic, needs: 'microphone' },
  { value: 'gesture', label: 'Gestures', icon: Hand, needs: 'camera' },
  { value: 'lip', label: 'Lip hints', icon: ScanFace, needs: 'camera' },
]

function Composer() {
  const b = useBackend()
  const { turn, config, lastActivity, draft, speech } = b
  const state = turn.state
  const capturing = state === 'CAPTURING'
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!capturing) return
    const id = window.setInterval(() => setNow(Date.now()), 200)
    return () => window.clearInterval(id)
  }, [capturing])

  const missing = MODES.filter((m) => b.modalities.includes(m.value) && !b.consent[m.needs])
  const silence = (config?.fragment_silence_s ?? 6) * 1000
  const hasFragments = draft.fragments.length > 0
  const quiet = lastActivity ? Math.max(0, now - lastActivity) : 0
  const left = Math.max(0, silence - quiet)
  const lipOff = b.health?.services.lip?.status === 'unavailable'

  if (state === 'FUSING') {
    return (
      <Panel className="grid grid-cols-1 gap-3 p-6" aria-live="polite">
        <p className="flex items-center gap-2 font-bold"><Waves className="size-5 text-lavender-ink" aria-hidden /> Putting your words together…</p>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {[0, 1, 2].map((i) => <div key={i} className="skeleton h-28" />)}
        </div>
      </Panel>
    )
  }
  if (state !== 'IDLE' && !capturing) return null

  return (
    <Panel className="overflow-hidden">
      <div className="grid grid-cols-1 gap-5 p-5 sm:p-6 lg:grid-cols-[1fr_auto] lg:items-center">
        <div className="min-w-0">
          {capturing ? (
            <div aria-live="polite">
              <p className="text-2xl font-bold">I’m listening. Take your time.</p>
              <p className="mt-1 text-muted">
                {speech && Date.now() - speech.at < 8000 && speech.speaker === 'PATIENT'
                  ? <>Heard: <span className="font-serif text-lg text-ink">“{speech.text || '…'}”</span></>
                  : 'Pauses are fine. Each piece you say, sign or mouth is kept.'}
              </p>
              <div className="mt-4 flex items-center gap-3 text-sm text-muted">
                {hasFragments ? (
                  <>
                    <div className="h-1.5 w-40 overflow-hidden rounded-full bg-rail" aria-hidden>
                      <div className="h-full rounded-full bg-butter-ink transition-[width] duration-200 ease-linear" style={{ width: `${(left / silence) * 100}%` }} />
                    </div>
                    <span className="tabular">Finishes by itself after {Math.ceil(left / 1000)} s of quiet</span>
                  </>
                ) : (
                  <span>Your draft stays open until you start, then finish.</span>
                )}
              </div>
            </div>
          ) : (
            <>
              <p className="text-2xl font-bold">Say it in pieces</p>
              <p className="mt-1 max-w-prose text-muted">Single words, broken syllables, gestures. PS-16 offers full sentences, and nothing is spoken until you choose one.</p>
              <div className="mt-5 flex flex-wrap items-center gap-3">
                <div className="flex flex-wrap gap-2" role="group" aria-label="Inputs for this message">
                  {MODES.map(({ value, label, icon: Icon }) => {
                    const on = b.modalities.includes(value)
                    return (
                      <button
                        key={value}
                        type="button"
                        aria-pressed={on}
                        onClick={() => {
                          const next = on ? b.modalities.filter((m) => m !== value) : [...b.modalities, value]
                          if (next.length) b.setModalities(next)
                        }}
                        className={cn(
                          'inline-flex h-10 items-center gap-2 rounded-xl border px-3.5 text-sm font-bold transition-colors',
                          on ? 'border-sage-ink/30 bg-sage text-sage-ink' : 'border-line bg-panel text-muted hover:text-ink',
                        )}
                      >
                        {on ? <Check className="size-4" aria-hidden /> : <Icon className="size-4" aria-hidden />}
                        {label}
                        {value === 'lip' && lipOff && <span className="text-xs font-normal">(not installed)</span>}
                      </button>
                    )
                  })}
                </div>
                <Segmented
                  label="Language of this message"
                  size="sm"
                  value={b.language}
                  onChange={b.setLanguage}
                  options={[
                    { value: 'en', label: 'English' }, { value: 'hi', label: 'हिन्दी' },
                    { value: 'mixed', label: 'Mixed' }, { value: 'auto', label: 'Auto' },
                  ]}
                />
              </div>
              {missing.length > 0 && (
                <div className="mt-4 flex flex-wrap items-center gap-2 rounded-xl bg-butter px-3.5 py-2.5 text-sm text-butter-ink">
                  <CircleAlert className="size-4 shrink-0" aria-hidden />
                  <span>{missing.map((m) => m.needs).filter((v, i, a) => a.indexOf(v) === i).join(' and ')} permission needed.</span>
                  {Array.from(new Set(missing.map((m) => m.needs))).map((p) => (
                    <Button key={p} size="sm" variant="secondary" loading={b.busy === `consent:${p}`} onClick={() => b.setConsent(p, true)}>
                      Allow {p}
                    </Button>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
        <div className="flex justify-start lg:justify-end">
          {capturing ? (
            <Button size="xl" variant="primary" loading={b.busy === 'end'} onClick={b.endTurn} className="w-full min-w-56 sm:w-auto">
              <span className="listen-ring relative grid grid-cols-1 size-7 place-items-center rounded-full"><Square className="size-4 fill-current" aria-hidden /></span>
              I’m done
            </Button>
          ) : (
            <Button
              size="xl"
              variant="primary"
              loading={b.busy === 'start'}
              disabled={missing.length > 0 || b.link === 'offline'}
              onClick={() => b.startTurn('PATIENT')}
              className="w-full min-w-56 sm:w-auto"
            >
              <Mic className="size-6" aria-hidden /> Start my message
            </Button>
          )}
        </div>
      </div>
    </Panel>
  )
}

function Draft() {
  const { draft, turn } = useBackend()
  // the draft belongs to an open turn; once it is spoken or rejected it leaves the screen
  if (turn.speaker === 'PARTNER' || turn.state === 'IDLE') return null
  return (
    <Panel className="p-5 sm:p-6" aria-labelledby="draft-title">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="draft-title" className="text-lg font-bold">What I caught</h2>
        <span className="text-sm text-muted">{draft.fragments.length} piece{draft.fragments.length === 1 ? '' : 's'}</span>
      </div>
      <LayoutGroup>
        <ol className="mt-4 flex min-h-16 flex-wrap items-center gap-x-2 gap-y-3" aria-live="polite">
          {draft.fragments.length === 0 && <li className="text-muted">Your words will appear here, one piece at a time.</li>}
          <AnimatePresence initial={false}>
            {draft.fragments.map((f, i) => (
              <motion.li
                key={f.id}
                layout
                initial={{ opacity: 0, y: 10, scale: 0.96, filter: 'blur(3px)' }}
                animate={{ opacity: 1, y: 0, scale: 1, filter: 'blur(0px)' }}
                exit={{ opacity: 0, scale: 0.96, transition: { duration: 0.12 } }}
                transition={{ duration: 0.32, ease: EASE }}
                className="flex items-center gap-2"
              >
                {i > 0 && f.gap_ms >= 600 && (
                  <span className="flex items-center gap-1 text-xs text-muted tabular" aria-label={`pause ${(f.gap_ms / 1000).toFixed(1)} seconds`}>
                    <span className="h-px w-4 border-t border-dashed border-line-strong" />{(f.gap_ms / 1000).toFixed(1)} s
                  </span>
                )}
                <Chip f={f} />
              </motion.li>
            ))}
          </AnimatePresence>
        </ol>
      </LayoutGroup>
      <div className="mt-4 flex flex-wrap items-baseline gap-x-3 gap-y-1 border-t border-dashed border-line pt-3">
        <span className="text-sm font-bold text-muted">Cleaned</span>
        <span className="font-serif text-lg">{draft.cleaned.length ? draft.cleaned.join(' · ') : 'Nothing yet'}</span>
      </div>
    </Panel>
  )
}

function Chip({ f }: { f: Fragment }) {
  const struck = f.flags.includes('stutter_prefix') || (f.flags.includes('repeat') && f.text.trim().split(/\s+/).length === 1)
  const filler = f.flags.includes('filler')
  const unsure = f.flags.includes('low_confidence')
  const answer = f.flags.includes('answer_to_question')
  const Icon = f.source === 'speech' ? Mic : f.source === 'gesture' ? Hand : ScanFace
  const tone = answer ? 'bg-sky text-sky-ink border-sky-ink/20'
    : f.source === 'gesture' ? 'bg-lavender text-lavender-ink border-lavender-ink/20'
      : f.source === 'lip' ? 'bg-butter text-butter-ink border-butter-ink/25'
        : 'bg-rail text-ink border-line'
  const note = answer ? 'answer' : f.source === 'lip' ? 'weak hint' : unsure ? 'unsure' : filler ? 'filler' : struck ? 'stutter' : null
  return (
    <span
      className={cn('inline-flex min-h-11 items-center gap-2 rounded-xl border px-3 text-lg', tone, (unsure || f.source === 'lip') && 'border-dashed', (filler || struck) && 'opacity-60')}
      title={f.confidence !== null ? `confidence ${(f.confidence * 100).toFixed(0)}%` : undefined}
    >
      <Icon className="size-4 shrink-0 opacity-75" aria-label={f.source} />
      <span className={cn(struck && 'line-through decoration-2', filler && 'italic')}>{f.text}</span>
      {note && <span className="text-xs font-bold opacity-80">{note}</span>}
    </span>
  )
}

function Decision() {
  const b = useBackend()
  const { turn, question } = b
  const [edit, setEdit] = useState<string | null>(null)
  const [review, setReview] = useState<string | null>(null)
  useEffect(() => { setEdit(null); setReview(null) }, [turn.turn_id])
  if (turn.state !== 'AWAITING_CONFIRM' && turn.state !== 'EDITING') return null
  const r = turn.result
  const cands = r?.candidates ?? []
  const rounds = b.config?.max_clarify_rounds ?? 2

  const sayExact = async (text: string) => {
    const res = await b.confirm({ edited_text: text })
    if (res?.needsReconfirm) setReview(res.finalText ?? text)
  }

  if (review !== null) {
    return (
      <Panel className="border-sage-ink/25 p-6" aria-live="polite">
        <p className="text-sm font-bold text-sage-ink">Check before it is spoken</p>
        <p className="mt-3 font-serif text-3xl leading-tight sm:text-4xl">{review}</p>
        <p className="mt-3 text-sm text-muted">This is exactly what will be said, word for word.</p>
        <div className="mt-5 flex flex-wrap gap-3">
          <Button size="lg" variant="primary" loading={b.busy === 'confirm'} onClick={() => b.confirm({ edited_text: review })}>
            <Volume2 className="size-5" aria-hidden /> Say it
          </Button>
          <Button size="lg" onClick={() => { setEdit(review); setReview(null) }}><Pencil className="size-4" aria-hidden /> Change</Button>
        </div>
      </Panel>
    )
  }

  if (edit !== null) {
    return (
      <Panel className="p-6">
        <label htmlFor="edit-text" className="text-lg font-bold">Write it your way</label>
        <textarea
          id="edit-text"
          value={edit}
          onChange={(e) => setEdit(e.target.value)}
          maxLength={300}
          rows={3}
          autoFocus
          className="mt-3 w-full resize-y rounded-xl border border-line-strong bg-panel p-4 font-serif text-2xl leading-snug focus:border-focus focus:outline-none"
        />
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button size="lg" variant="primary" disabled={!edit.trim()} loading={b.busy === 'confirm'} onClick={() => sayExact(edit)}>
            Review <ArrowRight className="size-5" aria-hidden />
          </Button>
          <Button size="lg" variant="quiet" onClick={() => setEdit(null)}>Cancel</Button>
          <span className="ml-auto text-sm text-muted tabular">{edit.length}/300</span>
        </div>
      </Panel>
    )
  }

  return (
    <section className="grid grid-cols-1 gap-4" aria-labelledby="choose-title">
      {question && r?.clarification_required && (
        <Panel className="border-butter-ink/25 bg-butter p-5 sm:p-6" aria-live="assertive">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="min-w-0">
              <p className="text-sm font-bold text-butter-ink">Question {question.round} of {rounds}</p>
              <p className="mt-1 font-serif text-2xl leading-snug text-ink sm:text-3xl">{question.text}</p>
              <p className="mt-2 text-sm text-butter-ink">Tap an answer, or show thumbs up or down to the camera.</p>
            </div>
            <div className="flex gap-3">
              <Button size="xl" variant="yes" loading={b.busy === 'clarify'} onClick={() => b.clarify('yes')}><ThumbsUp className="size-6" aria-hidden /> Yes</Button>
              <Button size="xl" variant="no" disabled={b.busy === 'clarify'} onClick={() => b.clarify('no')}><ThumbsDown className="size-6" aria-hidden /> No</Button>
            </div>
          </div>
        </Panel>
      )}

      {cands.length > 0 && (
        <>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 id="choose-title" className="text-2xl font-bold">Is this what you mean?</h2>
              <p className="text-sm text-muted">Nothing is spoken until you choose. Highlighted words were added for grammar.</p>
            </div>
            <Button variant="danger" onClick={b.reject} loading={b.busy === 'reject'}><X className="size-4" aria-hidden /> None of these</Button>
          </div>
          <div className={cn('grid grid-cols-1 gap-4', cands.length > 1 && 'md:grid-cols-2', cands.length > 2 && '2xl:grid-cols-3')}>
            {cands.map((c, i) => (
              <CandidateCard key={c.text} c={c} i={i} unexplained={r?.unexplained_fragment_ids.length ?? 0}
                busy={b.busy === 'confirm'} onSay={() => b.confirm({ choice_index: i })} onEdit={() => setEdit(c.text)} />
            ))}
          </div>
        </>
      )}

      {cands.length === 0 && (
        <Panel className="p-6">
          <h2 id="choose-title" className="text-2xl font-bold">
            {turn.fallback ? 'Here is what I caught' : r?.clarifying_question ? 'Answer the question above' : 'I couldn’t build a sentence'}
          </h2>
          {turn.fallback ? (
            <p className="mt-3 font-serif text-3xl leading-snug">{turn.fallback.text || '…'}</p>
          ) : (
            r?.reasoning_summary && <p className="mt-2 text-muted">{r.reasoning_summary}</p>
          )}
          <p className="mt-2 text-sm text-muted">Choose, edit or repeat. Nothing is said until you confirm.</p>
          <div className="mt-5 flex flex-wrap gap-3">
            <Button size="lg" variant="primary" onClick={() => setEdit(turn.fallback?.text || (turn.cleaned_fragments ?? []).join(' '))}>
              <Pencil className="size-4" aria-hidden /> Edit and say
            </Button>
            <Button size="lg" onClick={b.reject} loading={b.busy === 'reject'}><RotateCcw className="size-4" aria-hidden /> Start again</Button>
          </div>
        </Panel>
      )}
    </section>
  )
}

function CandidateCard({ c, i, unexplained, busy, onSay, onEdit }: {
  c: Candidate; i: number; unexplained: number; busy: boolean; onSay: () => void; onEdit: () => void
}) {
  const added = new Set(c.added_words.map((w) => w.toLowerCase()))
  const parts = c.text.split(/(\s+)/)
  return (
    <motion.article
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.36, ease: EASE, delay: i * 0.06 }}
      className={cn('flex flex-col rounded-2xl border bg-panel p-5 transition-shadow hover:shadow-lift', i === 0 ? 'border-sage-ink/35 shadow-card' : 'border-line')}
    >
      <div className="flex items-center justify-between gap-2">
        <Badge tone={i === 0 ? 'sage' : 'neutral'}>{i === 0 ? 'Best match' : `Option ${i + 1}`}</Badge>
        {unexplained === 0
          ? <span className="flex items-center gap-1 text-xs text-muted"><Check className="size-3.5" aria-hidden /> uses every piece</span>
          : <span className="text-xs text-butter-ink">{unexplained} piece{unexplained > 1 ? 's' : ''} not used</span>}
      </div>
      <p className="my-5 flex-1 font-serif text-[28px] leading-[1.18] tracking-[-0.01em] text-ink">
        {parts.map((p, k) => {
          const word = p.toLowerCase().replace(/[^\p{L}\p{N}']/gu, '')
          return word && added.has(word)
            ? <mark key={k} className="rounded-md bg-blush px-1 text-blush-ink">{p}</mark>
            : <span key={k}>{p}</span>
        })}
      </p>
      {c.added_words.length > 0 && (
        <p className="mb-4 text-xs text-muted">Added: {c.added_words.join(', ')}</p>
      )}
      <div className="flex gap-2">
        <Button variant="primary" size="lg" className="flex-1" loading={busy} onClick={onSay}><Volume2 className="size-5" aria-hidden /> Say this</Button>
        <Button size="lg" onClick={onEdit} aria-label={`Edit option ${i + 1}`}><Pencil className="size-4" aria-hidden /></Button>
      </div>
    </motion.article>
  )
}

function SpokenBanner() {
  const { spoken, fallbackReason, turn, avatarSpeaking } = useBackend()
  if (!spoken || (turn.state !== 'IDLE' && turn.state !== 'SPEAKING')) return null
  const tier = spoken.tier === 'avatar_audio' || spoken.tier === 'avatar_text' ? 'Said by your avatar'
    : spoken.tier === 'local' ? 'Spoken on this device, with subtitles' : 'Getting ready to speak…'
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, ease: EASE }}>
      <Panel className="border-sage-ink/25 bg-sage p-6" aria-live="polite">
        <div className="flex flex-wrap items-center gap-2 text-sm font-bold text-sage-ink">
          {spoken.playing || avatarSpeaking ? <Volume2 className="size-4" aria-hidden /> : <Check className="size-4" aria-hidden />}
          {tier}
          <Badge tone="lavender" className="ml-auto">AI voice · synthetic</Badge>
        </div>
        <p className="mt-3 font-serif text-3xl leading-tight text-ink sm:text-4xl">{spoken.subtitles ?? spoken.text}</p>
        {fallbackReason && spoken.tier === 'local' && (
          <p className="mt-3 flex items-center gap-1.5 text-sm text-sage-ink"><MicOff className="size-4" aria-hidden /> Avatar not used: {fallbackReason}</p>
        )}
        {spoken.tier === 'local' && !spoken.playing && (
          <Button className="mt-4" size="sm" onClick={() => window.dispatchEvent(new Event('ps16:replay'))}>
            <RotateCcw className="size-4" aria-hidden /> Play again
          </Button>
        )}
      </Panel>
    </motion.div>
  )
}

function GestureHints() {
  const { link } = useBackend()
  const [lex, setLex] = useState<Record<string, string> | null>(null)
  useEffect(() => { api.lexicon().then(setLex).catch(() => setLex(null)) }, [link])
  const rows = Object.entries(lex ?? {}).sort(([, a], [, b]) => a.localeCompare(b)).slice(0, 6)
  if (!rows.length) return null
  return (
    <ul className="mt-4 grid grid-cols-1 gap-2 text-sm" aria-label="Your gesture words">
      {rows.map(([token, word]) => (
        <li key={token} className="flex items-center justify-between gap-3 border-b border-line pb-2 last:border-0">
          <span className="font-bold text-lavender-ink">{prettyToken(token)}</span>
          <span className="text-muted">{word === '__COMMIT__' ? 'finish message' : word === '__CLEAR__' ? 'clear draft' : word}</span>
        </li>
      ))}
    </ul>
  )
}
