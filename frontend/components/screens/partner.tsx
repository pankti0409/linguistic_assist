'use client'

import { Ear, Mic, Square, UserRound } from 'lucide-react'

import { useBackend } from '@/lib/backend'
import { cn } from '@/lib/utils'

import { Badge, Button, Empty, Panel, PanelHeader } from '../ui/kit'

export function PartnerScreen() {
  const b = useBackend()
  const { turn, context, speech } = b
  const active = turn.speaker === 'PARTNER' && turn.state === 'CAPTURING'
  const patientBusy = turn.state !== 'IDLE' && turn.speaker === 'PATIENT'
  const heard = speech && speech.speaker === 'PARTNER' && Date.now() - speech.at < 15000 ? speech.text : null

  return (
    <div className="mx-auto grid grid-cols-1 max-w-5xl gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <Panel className="flex flex-col p-6">
        <h1 className="text-3xl font-bold">Partner speaks</h1>
        <p className="mt-2 max-w-prose text-muted">
          Press start while your partner talks. Their words are written down as context for the next
          message. PS-16 never answers them on its own.
        </p>
        <div className={cn('mt-6 grid grid-cols-1 flex-1 place-items-center rounded-2xl border border-dashed p-8 text-center transition-colors', active ? 'border-sky-ink/40 bg-sky' : 'border-line-strong')}>
          {active ? (
            <div aria-live="polite">
              <span className="listen-ring relative mx-auto grid grid-cols-1 size-16 place-items-center rounded-full bg-panel text-sky-ink"><Ear className="size-7" aria-hidden /></span>
              <p className="mt-4 text-lg font-bold text-sky-ink">Listening to your partner</p>
              <p className="mt-2 font-serif text-xl text-ink">{heard ? `“${heard}”` : 'Words appear after each pause.'}</p>
            </div>
          ) : (
            <div>
              <span className="mx-auto grid grid-cols-1 size-16 place-items-center rounded-full bg-sky text-sky-ink"><UserRound className="size-7" aria-hidden /></span>
              <p className="mt-4 text-muted">{patientBusy ? 'Finish the current message first.' : 'Ready when your partner is.'}</p>
            </div>
          )}
        </div>
        <div className="mt-5">
          {active ? (
            <Button size="xl" variant="primary" className="w-full" loading={b.busy === 'end'} onClick={b.endTurn}>
              <Square className="size-5 fill-current" aria-hidden /> Partner finished
            </Button>
          ) : (
            <Button size="xl" variant="primary" className="w-full" disabled={patientBusy || !b.consent.microphone || b.link === 'offline'}
              loading={b.busy === 'start'} onClick={() => b.startTurn('PARTNER')}>
              <Mic className="size-6" aria-hidden /> Start partner turn
            </Button>
          )}
          {!b.consent.microphone && (
            <p className="mt-3 text-sm text-butter-ink">
              The microphone is off.{' '}
              <button className="font-bold underline" onClick={() => b.setConsent('microphone', true)}>Allow microphone</button>
            </p>
          )}
        </div>
      </Panel>

      <Panel className="p-6" aria-labelledby="ctx-title">
        <PanelHeader id="ctx-title" title="Recent conversation" aside={<Badge tone="sky">last {b.config?.context_turns ?? 6} turns</Badge>}>
          What PS-16 remembers for context. It lives in memory only and is cleared on restart.
        </PanelHeader>
        <ol className="mt-5 grid grid-cols-1 gap-3">
          {context.length === 0 && (
            <li><Empty icon={<Ear className="size-5" />} title="Nothing yet">Partner questions and your spoken messages appear here, labelled.</Empty></li>
          )}
          {[...context].reverse().map((t, i) => (
            <li key={`${t.ts_ms}-${i}`} className={cn('rounded-xl border px-4 py-3', t.speaker === 'PARTNER' ? 'border-sky-ink/15 bg-sky' : 'border-sage-ink/15 bg-sage')}>
              <p className={cn('text-xs font-bold', t.speaker === 'PARTNER' ? 'text-sky-ink' : 'text-sage-ink')}>{t.speaker === 'PARTNER' ? 'Partner' : 'You (spoken)'}</p>
              <p className="mt-0.5 font-serif text-lg text-ink">{t.text}</p>
            </li>
          ))}
        </ol>
      </Panel>
    </div>
  )
}
