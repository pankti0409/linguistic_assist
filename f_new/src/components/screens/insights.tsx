'use client'

import { BarChart3, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import { api } from '@/lib/api'
import { useBackend } from '@/lib/backend'
import type { Metrics } from '@/lib/types'

import { Badge, Button, Empty, Panel, PanelHeader, ms } from '../ui/kit'

const STAGES: Record<string, string> = {
  scribe_ms: 'Speech to text', lip_ms: 'Lip read', fusion_ms: 'Sentence suggestions', tts_ms: 'Voice',
  avatar_ms: 'Avatar start', e2e_ms: 'End of speaking → audio', confirm_wait_ms: 'Time to choose',
}

export function InsightsScreen() {
  const b = useBackend()
  const [m, setM] = useState<Metrics | null>(null)
  const [loading, setLoading] = useState(false)
  const load = useCallback(async () => {
    setLoading(true)
    try { setM(await api.metrics()) } catch { setM(null) } finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load, b.turn.state === 'IDLE']) // eslint-disable-line react-hooks/exhaustive-deps

  const rows = Object.entries(m?.summary ?? {})
  const turns = [...(m?.turns ?? [])].reverse()
  const msgs = turns.filter((t) => t.speaker === 'PATIENT')
  const effort = msgs.length ? msgs.reduce((s, t) => s + t.taps + t.edits, 0) / msgs.length : null

  return (
    <div className="mx-auto grid grid-cols-1 max-w-5xl gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Insights</h1>
          <p className="mt-2 max-w-prose text-muted">Measured on this computer for the last 100 turns. A missing number means it was not measured.</p>
        </div>
        <Button size="sm" loading={loading} onClick={load}><RefreshCw className="size-4" aria-hidden /> Refresh</Button>
      </div>

      <Panel className="p-6" aria-labelledby="lat-title">
        <PanelHeader id="lat-title" title="How long each step takes" aside={<Badge>median · 95th percentile</Badge>} />
        {rows.length === 0 ? (
          <div className="mt-5"><Empty icon={<BarChart3 className="size-5" />} title="No measured turns yet">Speak a message and the timings appear here.</Empty></div>
        ) : (
          <table className="mt-5 w-full text-left">
            <thead><tr className="text-sm text-muted"><th className="pb-2 font-bold">Step</th><th className="pb-2 text-right font-bold">Median</th><th className="pb-2 text-right font-bold">95th</th><th className="pb-2 text-right font-bold">Turns</th></tr></thead>
            <tbody className="tabular">
              {rows.map(([k, v]) => (
                <tr key={k} className="border-t border-line">
                  <td className="py-2.5 font-bold">{STAGES[k] ?? k}</td>
                  <td className="py-2.5 text-right">{ms(v.p50)}</td>
                  <td className="py-2.5 text-right">{ms(v.p95)}</td>
                  <td className="py-2.5 text-right text-muted">{v.n}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        <Panel className="p-5"><p className="text-sm font-bold text-muted">Messages spoken</p><p className="mt-1 text-3xl font-semibold tracking-tight tabular">{m?.counters.messages_spoken ?? 0}</p></Panel>
        <Panel className="p-5"><p className="text-sm font-bold text-muted">Turns rejected</p><p className="mt-1 text-3xl font-semibold tracking-tight tabular">{m?.counters.turns_rejected ?? 0}</p></Panel>
        <Panel className="p-5"><p className="text-sm font-bold text-muted">Taps + edits per message</p><p className="mt-1 text-3xl font-semibold tracking-tight tabular">{effort === null ? 'n/a' : effort.toFixed(1)}</p></Panel>
      </div>

      <Panel className="p-6" aria-labelledby="turns-title">
        <PanelHeader id="turns-title" title="Recent turns" />
        {turns.length === 0 ? <p className="mt-4 text-sm text-muted">None yet.</p> : (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[560px] text-left text-sm">
              <thead><tr className="text-muted"><th className="pb-2 font-bold">Who</th><th className="pb-2 font-bold">Spoken by</th><th className="pb-2 text-right font-bold">End → audio</th><th className="pb-2 text-right font-bold">Taps</th><th className="pb-2 text-right font-bold">Edits</th><th className="pb-2 text-right font-bold">Questions</th></tr></thead>
              <tbody className="tabular">
                {turns.slice(0, 20).map((t) => (
                  <tr key={t.turn_id} className="border-t border-line">
                    <td className="py-2">{t.speaker === 'PATIENT' ? 'You' : 'Partner'}</td>
                    <td className="py-2">{t.tier ?? '—'}</td>
                    <td className="py-2 text-right">{ms(t.stages.e2e_ms)}</td>
                    <td className="py-2 text-right">{t.taps}</td>
                    <td className="py-2 text-right">{t.edits}</td>
                    <td className="py-2 text-right">{t.clarify_rounds}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  )
}
