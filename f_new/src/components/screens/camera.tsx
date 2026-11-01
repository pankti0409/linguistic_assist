'use client'

import { Hand, Save, Target, Undo2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'

import { api, ApiError, errorText } from '@/lib/api'
import { useBackend } from '@/lib/backend'
import { cn } from '@/lib/utils'

import { CameraView, prettyToken } from '../camera-view'
import { Badge, Button, Empty, Panel, PanelHeader, inputClass } from '../ui/kit'

const LABELS = ['Thumb_Up', 'Thumb_Down', 'Open_Palm', 'Closed_Fist', 'Pointing_Up', 'Victory', 'ILoveYou'] as const
const HANDS = [['*', 'Either hand'], ['Left', 'Left hand'], ['Right', 'Right hand']] as const
const RESERVED: Record<string, string> = { __COMMIT__: 'Finish message', __CLEAR__: 'Clear draft' }

export function CameraScreen() {
  const b = useBackend()
  const feed = useMemo(
    () => b.events.filter((e) => e.type === 'gesture.word' || e.type === 'gesture.token').slice(0, 10),
    [b.events],
  )
  return (
    <div className="mx-auto grid grid-cols-1 max-w-[1320px] gap-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Camera & gestures</h1>
        <p className="mt-2 max-w-prose text-muted">
          Hold a gesture steadily for about half a second to make a word. Frames are never saved; the
          picture you see is streamed from memory on this computer only.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Panel className="p-4">
          <CameraView size="lg" />
          <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Stat label="Face" value={b.mouth ? (b.mouth.face_present ? 'Found' : 'Not found') : '—'} />
            <Stat label="Head turn" value={b.mouth?.yaw_deg !== null && b.mouth?.yaw_deg !== undefined ? `${Math.abs(b.mouth.yaw_deg).toFixed(0)}°` : '—'} />
            <Stat label="Tracking delay" value={b.mouth ? `${b.mouth.lag_ms} ms` : '—'} />
          </div>
        </Panel>
        <Panel className="p-5" aria-labelledby="feed-title">
          <PanelHeader id="feed-title" title="Seen just now" aside={<Badge tone="lavender">live</Badge>}>
            Gestures the camera recognised, newest first.
          </PanelHeader>
          <ol className="mt-4 grid grid-cols-1 gap-2" aria-live="polite">
            {feed.length === 0 && <li><Empty icon={<Hand className="size-5" />} title="No gestures yet">{b.consent.camera ? 'Hold a thumbs up steadily in front of the camera.' : 'Turn on the camera, then hold a thumbs up.'}</Empty></li>}
            {feed.map((e, i) => {
              const d = e.data as { token: string; word?: string; score: number }
              return (
                <li key={`${e.ts_ms}-${i}`} className="flex items-center justify-between gap-3 rounded-xl border border-line px-3.5 py-2.5">
                  <span className="min-w-0 truncate">
                    <span className="font-bold">{e.type === 'gesture.word' ? `“${d.word}”` : prettyToken(d.token)}</span>
                    {e.type === 'gesture.word' && <span className="ml-2 text-sm text-muted">{prettyToken(d.token)}</span>}
                  </span>
                  <span className="text-sm text-muted tabular">{Math.round(d.score * 100)}%</span>
                </li>
              )
            })}
          </ol>
        </Panel>
      </div>
      <LexiconEditor />
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-rail px-4 py-3">
      <p className="text-xs font-bold text-muted">{label}</p>
      <p className="mt-0.5 text-lg font-bold tabular">{value}</p>
    </div>
  )
}

function LexiconEditor() {
  const b = useBackend()
  const [saved, setSaved] = useState<Record<string, string> | null>(null)
  const [map, setMap] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [calWord, setCalWord] = useState('')
  const [calibrating, setCalibrating] = useState<number | null>(null)

  useEffect(() => {
    api.lexicon().then((m) => { setSaved(m); setMap(m) }).catch(() => setSaved({}))
  }, [b.link])
  useEffect(() => {
    if (calibrating === null) return
    const id = window.setInterval(() => setCalibrating((c) => (c === null ? null : Math.max(0, c - 1))), 1000)
    return () => window.clearInterval(id)
  }, [calibrating !== null]) // eslint-disable-line react-hooks/exhaustive-deps

  const dirty = saved !== null && JSON.stringify(saved) !== JSON.stringify(map)
  const set = (token: string, word: string) => setMap((m) => {
    const next = { ...m }
    if (word.trim()) next[token] = word
    else delete next[token]
    return next
  })
  const save = async () => {
    setSaving(true)
    try {
      const clean = Object.fromEntries(Object.entries(map).map(([k, v]) => [k, v.trim()]).filter(([, v]) => v))
      const m = await api.setLexicon(clean)
      setSaved(m); setMap(m); toast.success('Gesture words saved')
    } catch (e) { toast.error(errorText(e)) } finally { setSaving(false) }
  }
  const calibrate = async () => {
    const word = calWord.trim()
    if (!word) return
    setCalibrating(b.config?.calibrate_timeout_s ?? 10)
    try {
      const r = await api.calibrate(word)
      toast.success(`“${word}” is now ${prettyToken(r.token)}`)
      const m = await api.lexicon(); setSaved(m); setMap(m); setCalWord('')
    } catch (e) {
      toast.error(e instanceof ApiError && e.code === 'calibration_timeout' ? 'No steady gesture seen. Hold it still for a moment and try again.' : errorText(e))
    } finally { setCalibrating(null) }
  }

  return (
    <Panel className="p-6" aria-labelledby="lex-title">
      <PanelHeader id="lex-title" title="My gesture words" aside={
        <div className="flex gap-2">
          <Button size="sm" variant="quiet" disabled={!dirty} onClick={() => saved && setMap(saved)}><Undo2 className="size-4" aria-hidden /> Undo</Button>
          <Button size="sm" variant="primary" disabled={!dirty} loading={saving} onClick={save}><Save className="size-4" aria-hidden /> Save</Button>
        </div>
      }>
        Gestures without a word are ignored, never guessed. “Either hand” applies unless a hand has its own word.
      </PanelHeader>

      <div className="mt-5 flex flex-wrap items-end gap-3 rounded-2xl bg-lavender p-4">
        <label className="grid grid-cols-1 min-w-56 flex-1 gap-1.5">
          <span className="text-sm font-bold text-lavender-ink">Teach a new gesture</span>
          <input className={inputClass} value={calWord} onChange={(e) => setCalWord(e.target.value)} placeholder="Word, e.g. water" maxLength={40}
            disabled={calibrating !== null} />
        </label>
        <Button variant="primary" size="md" disabled={!calWord.trim() || !b.consent.camera || calibrating !== null} onClick={calibrate}>
          <Target className="size-4" aria-hidden />
          {calibrating !== null ? `Show your gesture… ${calibrating}s` : 'Bind next gesture'}
        </Button>
        {!b.consent.camera && <p className="w-full text-sm text-lavender-ink">Turn on the camera to teach gestures.</p>}
      </div>

      <div className="mt-5 grid grid-cols-1">
        <div className="hidden grid-cols-[150px_repeat(3,minmax(0,1fr))] gap-3 pb-2 text-sm font-bold text-muted md:grid">
          <span>Gesture</span>
          {HANDS.map(([, label]) => <span key={label}>{label}</span>)}
        </div>
        {LABELS.map((label) => (
          <div key={label} className="grid grid-cols-1 gap-2 border-t border-line py-3 md:grid-cols-[150px_repeat(3,minmax(0,1fr))] md:items-center md:gap-3">
            <span className="font-bold">{label.replace(/_/g, ' ')}</span>
            {HANDS.map(([hand, handLabel]) => {
              const token = `${label}|${hand}`
              const v = map[token] ?? ''
              const reserved = v in RESERVED
              return (
                <div key={hand} className="grid grid-cols-[92px_minmax(0,1fr)] items-center gap-2 md:grid-cols-1">
                  <span className="text-xs font-bold text-muted md:hidden">{handLabel}</span>
                  <div className="flex min-w-0 gap-1.5">
                    <input
                      aria-label={`Word for ${label.replace(/_/g, ' ')}, ${hand === '*' ? 'either hand' : `${hand.toLowerCase()} hand`}`}
                      className={cn(inputClass, 'h-10 min-w-0', reserved && 'bg-sky font-bold text-sky-ink', v !== (saved?.[token] ?? '') && 'border-focus')}
                      value={reserved ? RESERVED[v] : v}
                      readOnly={reserved}
                      onChange={(e) => set(token, e.target.value)}
                      placeholder="—"
                      maxLength={40}
                    />
                    <select
                      aria-label={`Action for ${label.replace(/_/g, ' ')}, ${handLabel.toLowerCase()}`}
                      className="h-10 shrink-0 rounded-xl border border-line-strong bg-panel px-2 text-sm text-ink-soft"
                      value={reserved ? v : ''}
                      onChange={(e) => set(token, e.target.value)}
                    >
                      <option value="">word</option>
                      <option value="__COMMIT__">finish</option>
                      <option value="__CLEAR__">clear</option>
                    </select>
                  </div>
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </Panel>
  )
}
