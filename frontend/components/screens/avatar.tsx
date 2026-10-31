'use client'

import { Bot, Lock, Power, Video } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { api, errorText } from '@/lib/api'
import { useBackend } from '@/lib/backend'
import type { AvatarSession } from '@/lib/types'

import { Badge, Button, Dot, Panel, PanelHeader, Segmented } from '../ui/kit'

export function AvatarScreen() {
  const b = useBackend()
  const [session, setSession] = useState<AvatarSession | null>(null)
  const [working, setWorking] = useState(false)
  const svc = b.health?.services.avatar

  useEffect(() => { api.avatarSession().then(setSession).catch(() => setSession(null)) }, [b.link, b.consent.avatar])

  const start = async () => {
    setWorking(true)
    try { setSession(await api.startAvatar()) } catch (e) { toast.error(errorText(e)) } finally { setWorking(false) }
  }
  const end = async () => {
    setWorking(true)
    try { await api.endAvatar(); setSession(await api.avatarSession()) } catch (e) { toast.error(errorText(e)) } finally { setWorking(false) }
  }
  const live = Boolean(session?.conversation_url)
  const voices = b.voice?.voices ?? []

  return (
    <div className="mx-auto grid grid-cols-1 max-w-[1200px] gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
      <Panel className="overflow-hidden" aria-labelledby="avatar-title">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-6 py-4">
          <div className="flex items-center gap-3">
            <h1 id="avatar-title" className="text-xl font-bold">Your AI avatar</h1>
            <Badge tone="lavender">AI avatar · synthetic</Badge>
          </div>
          {live ? (
            <Button size="sm" variant="danger" loading={working} onClick={end}><Power className="size-4" aria-hidden /> End session</Button>
          ) : (
            <Button size="sm" variant="primary" loading={working} disabled={!b.consent.avatar || svc?.status === 'unavailable'} onClick={start}>
              <Video className="size-4" aria-hidden /> Start avatar
            </Button>
          )}
        </div>
        <div className="relative aspect-video bg-[#0e1215]">
          {live ? (
            // Receive-only: no camera or microphone permission is delegated to the room (R4).
            <iframe
              title="AI avatar (receive-only)"
              src={session!.conversation_url!}
              allow="autoplay; fullscreen"
              className="size-full border-0"
            />
          ) : (
            <div className="absolute inset-0 grid grid-cols-1 place-items-center p-6 text-center text-white">
              <div className="max-w-sm">
                <span className="mx-auto grid grid-cols-1 size-14 place-items-center rounded-2xl bg-white/10"><Bot className="size-7" aria-hidden /></span>
                <p className="mt-4 text-lg font-bold">{b.consent.avatar ? 'Avatar is not running' : 'Avatar needs your permission'}</p>
                <p className="mt-2 text-sm text-white/75">
                  {svc?.status === 'unavailable'
                    ? `${svc.detail}. Your messages are still spoken on this device.`
                    : 'It speaks only messages you have confirmed. Your camera and microphone stay off in its room.'}
                </p>
                {!b.consent.avatar && (
                  <Button className="mt-5" variant="primary" loading={b.busy === 'consent:avatar'} onClick={() => b.setConsent('avatar', true)}>
                    <Lock className="size-4" aria-hidden /> Allow avatar
                  </Button>
                )}
              </div>
            </div>
          )}
          {b.avatarSpeaking && (
            <div className="absolute left-4 top-4"><Badge tone="sage"><Dot pulse /> Speaking your message</Badge></div>
          )}
        </div>
        <p className="px-6 py-4 text-sm text-muted">
          Everyone in the room sees that this is an AI avatar. It repeats your confirmed words exactly and never answers on its own.
        </p>
      </Panel>

      <div className="grid grid-cols-1 content-start gap-6">
        <Panel className="p-6" aria-labelledby="voice-title">
          <PanelHeader id="voice-title" title="Voice">Used for every spoken message. Library voices, not a clone of anyone.</PanelHeader>
          <div className="mt-5">
            <Segmented
              label="Voice"
              value={b.voice?.selected ?? 'female'}
              onChange={(g) => b.setVoice(g)}
              options={(['female', 'male'] as const).map((g) => ({
                value: g,
                label: g === 'female' ? 'Female' : 'Male',
                disabled: !voices.find((v) => v.gender === g)?.configured,
              }))}
            />
            {voices.some((v) => !v.configured) && (
              <p className="mt-3 text-sm text-muted">Set VOICE_ID_MALE and VOICE_ID_FEMALE in the backend .env to enable both.</p>
            )}
          </div>
        </Panel>

        <Panel className="p-6" aria-labelledby="ladder-title">
          <PanelHeader id="ladder-title" title="How messages are spoken">Exactly one of these runs for each message.</PanelHeader>
          <ol className="mt-5 grid grid-cols-1 gap-3">
            {[
              ['Avatar speaks with your chosen voice', 'when an avatar session is running'],
              ['Avatar speaks with its own voice', 'if the first way does not start'],
              ['This device plays the audio, with subtitles', 'always available as the safe fallback'],
            ].map(([t, d], i) => (
              <li key={t} className="flex gap-3">
                <span className="grid grid-cols-1 size-7 shrink-0 place-items-center rounded-full bg-rail text-sm font-bold tabular">{i + 1}</span>
                <span><span className="font-bold">{t}</span><br /><span className="text-sm text-muted">{d}</span></span>
              </li>
            ))}
          </ol>
          <p className="mt-4 text-sm text-muted">Mode: {b.health?.avatar_mode ?? '—'} · Status: {svc ? `${svc.status} (${svc.detail})` : '—'}</p>
        </Panel>
      </div>
    </div>
  )
}
