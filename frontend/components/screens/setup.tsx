'use client'

import { Camera, KeyRound, Mic, Moon, ShieldCheck, Sparkles, Sun, UserRoundCog, Video } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { getToken, setToken } from '@/lib/api'
import { useBackend } from '@/lib/backend'
import type { Purpose } from '@/lib/types'
import { cn } from '@/lib/utils'

import { Badge, Button, Dot, Panel, PanelHeader, Segmented, Switch, inputClass } from '../ui/kit'

const PURPOSES: { id: Purpose; title: string; body: string; icon: typeof Mic }[] = [
  { id: 'microphone', title: 'Microphone', body: 'Hear your speech and your partner. Audio is sent to ElevenLabs Scribe for text and never saved.', icon: Mic },
  { id: 'camera', title: 'Camera', body: 'See gestures and mouth movement with the laptop webcam. Frames stay in memory on this computer.', icon: Camera },
  { id: 'avatar', title: 'AI avatar', body: 'Let a Tavus avatar say your confirmed messages. Your camera and mic stay off in its room.', icon: Video },
  { id: 'personalization', title: 'Personal words', body: 'Remember your words and past sentences on this computer to make better suggestions.', icon: UserRoundCog },
  { id: 'voice_clone', title: 'Voice clone', body: 'Use a cloned voice. Not used today: the voices are library voices, not a copy of anyone.', icon: Sparkles },
]

const SERVICE_NAMES: Record<string, string> = {
  camera: 'Webcam', face: 'Face tracking', gesture: 'Gestures', lip: 'Lip hints', scribe: 'Speech to text', tts: 'Spoken voice', avatar: 'Avatar',
}

export function SetupScreen({ theme, setTheme }: { theme: 'light' | 'dark'; setTheme: (t: 'light' | 'dark') => void }) {
  const b = useBackend()
  const [token, setTok] = useState('')
  useEffect(() => { setTok(getToken()) }, [])

  return (
    <div className="mx-auto grid grid-cols-1 max-w-5xl gap-6">
      <div>
        <h1 className="text-3xl font-bold">Setup & permissions</h1>
        <p className="mt-2 max-w-prose text-muted">
          Nothing starts until you allow it, and you can switch anything off at any time. Permissions
          reset when the backend restarts.
        </p>
      </div>

      <Panel className="divide-y divide-line" aria-label="Permissions">
        {PURPOSES.map(({ id, title, body, icon: Icon }) => (
          <div key={id} className="flex items-center gap-4 p-5">
            <span className={cn('grid grid-cols-1 size-11 shrink-0 place-items-center rounded-xl', b.consent[id] ? 'bg-sage text-sage-ink' : 'bg-rail text-muted')}>
              <Icon className="size-5" aria-hidden />
            </span>
            <div className="min-w-0 flex-1">
              <p className="font-bold">{title}</p>
              <p className="text-sm text-muted">{body}</p>
            </div>
            <Switch label={title} checked={b.consent[id]} busy={b.busy === `consent:${id}`} disabled={b.link === 'offline'}
              onChange={(v) => b.setConsent(id, v)} />
          </div>
        ))}
      </Panel>

      <Panel className="p-6" aria-labelledby="svc-title">
        <PanelHeader id="svc-title" title="What is running" aside={b.health?.simulate ? <Badge tone="butter">Simulation mode</Badge> : undefined}>
          Live status from the backend. “Test stand-in” means a simulated service, not the real one.
        </PanelHeader>
        <ul className="mt-5 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {b.health ? Object.entries(b.health.services).map(([name, s]) => (
            <li key={name} className="flex items-start gap-3 rounded-xl border border-line px-4 py-3">
              <span className="mt-1.5"><Dot tone={s.status === 'ok' ? 'sage' : s.status === 'degraded' ? 'butter' : 'muted'} /></span>
              <span className="min-w-0">
                <span className="flex flex-wrap items-center gap-2 font-bold">
                  {SERVICE_NAMES[name] ?? name}
                  {s.backend === 'fake' && <Badge tone="butter">test stand-in</Badge>}
                </span>
                <span className="block text-sm text-muted">{s.status === 'ok' ? 'Working' : s.status === 'degraded' ? 'Ready, not in use' : 'Off'} · {s.detail}</span>
              </span>
            </li>
          )) : [0, 1, 2, 3].map((i) => <li key={i} className="skeleton h-16" />)}
        </ul>
        {b.health?.limits && (
          <details className="mt-5 rounded-xl bg-rail px-4 py-3">
            <summary className="cursor-pointer font-bold">Known limits</summary>
            <ul className="mt-3 grid grid-cols-1 gap-1.5 text-sm text-ink-soft">
              {Object.entries(b.health.limits).flatMap(([k, items]) => items.map((t) => <li key={k + t}>• <span className="font-bold capitalize">{k}:</span> {t}</li>))}
            </ul>
          </details>
        )}
      </Panel>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <Panel className="p-6" aria-labelledby="look-title">
          <PanelHeader id="look-title" title="Appearance">Dark is easier on the eyes at night.</PanelHeader>
          <div className="mt-5">
            <Segmented label="Theme" value={theme} onChange={setTheme}
              options={[{ value: 'light', label: <><Sun className="size-4" aria-hidden /> Light</> }, { value: 'dark', label: <><Moon className="size-4" aria-hidden /> Dark</> }]} />
          </div>
        </Panel>
        <Panel className="p-6" aria-labelledby="token-title">
          <PanelHeader id="token-title" title="Access token" aside={b.config?.token_required || b.link === 'locked' ? <Badge tone="butter">required</Badge> : undefined}>
            Only if the backend sets ACCESS_TOKEN. Stored in this browser.
          </PanelHeader>
          <form className="mt-5 flex gap-2" onSubmit={(e) => {
            e.preventDefault(); setToken(token.trim()); window.dispatchEvent(new Event('ps16:token')); b.refresh(); toast.success('Token saved')
          }}>
            <input className={inputClass} type="password" autoComplete="off" value={token} onChange={(e) => setTok(e.target.value)} placeholder="Paste token" aria-label="Access token" />
            <Button type="submit"><KeyRound className="size-4" aria-hidden /> Save</Button>
          </form>
        </Panel>
      </div>

      <p className="flex items-center gap-2 text-sm text-muted">
        <ShieldCheck className="size-4 text-sage-ink" aria-hidden />
        Assistive proof of concept. Not a diagnostic tool and not clinically validated.
      </p>
    </div>
  )
}
