'use client'

// The live avatar with its own start / end controls, beside the message composer so you can
// speak and watch the avatar on one screen.

import { Bot, Lock, Power, Video } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'

import { api, errorText } from '@/lib/api'
import { useBackend } from '@/lib/backend'
import type { AvatarSession } from '@/lib/types'

import { AvatarPlayer } from './avatar-player'
import { Badge, Button, Dot, Panel } from './ui/kit'

export function AvatarPanel() {
  const b = useBackend()
  const [session, setSession] = useState<AvatarSession | null>(null)
  const [working, setWorking] = useState(false)
  const svc = b.health?.services.avatar

  const refresh = useCallback(() => {
    api.avatarSession().then(setSession).catch(() => setSession(null))
  }, [])
  // svc.detail changes whenever the backend starts or ends a session, so re-ask then too
  useEffect(refresh, [refresh, b.link, b.consent.avatar, svc?.detail])

  const start = async () => {
    setWorking(true)
    try {
      if (!b.consent.avatar && !(await b.setConsent('avatar', true))) return
      setSession(await api.startAvatar())
    } catch (e) { toast.error(errorText(e)) } finally { setWorking(false) }
  }
  const end = async () => {
    setWorking(true)
    try { await api.endAvatar(); setSession(await api.avatarSession()) } catch (e) { toast.error(errorText(e)) } finally { setWorking(false) }
  }
  const live = Boolean(session?.conversation_url)

  return (
    <Panel className="overflow-hidden" aria-labelledby="avatar-title">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div className="flex items-center gap-3">
          <h2 id="avatar-title" className="font-bold">Your AI avatar</h2>
          <Badge tone="lavender">AI avatar · synthetic</Badge>
        </div>
        {live ? (
          <Button size="sm" variant="danger" loading={working} onClick={end}><Power className="size-4" aria-hidden /> End</Button>
        ) : (
          <Button size="sm" variant="primary" loading={working} disabled={svc?.status === 'unavailable'} onClick={start}>
            <Video className="size-4" aria-hidden /> Start avatar
          </Button>
        )}
      </div>
      <div className="relative aspect-video bg-[#0e1215]">
        {live ? (
          // Receive-only: joins with no devices, so no camera/mic prompt ever appears (R4).
          <AvatarPlayer url={session!.conversation_url!} onEnded={refresh} />
        ) : (
          <div className="absolute inset-0 grid grid-cols-1 place-items-center p-6 text-center text-white">
            <div className="max-w-sm">
              <span className="mx-auto grid grid-cols-1 size-12 place-items-center rounded-2xl bg-white/10"><Bot className="size-6" aria-hidden /></span>
              <p className="mt-3 font-bold">{b.consent.avatar ? 'Avatar is not running' : 'Avatar needs your permission'}</p>
              <p className="mt-1 text-sm text-white/75">
                {svc?.status === 'unavailable'
                  ? `${svc.detail}. Your messages are still spoken on this device.`
                  : 'Start it to have your confirmed messages said by the avatar.'}
              </p>
              {!b.consent.avatar && svc?.status !== 'unavailable' && (
                <p className="mt-2 flex items-center justify-center gap-1.5 text-xs text-white/60"><Lock className="size-3.5" aria-hidden /> Starting it records your permission.</p>
              )}
            </div>
          </div>
        )}
        {b.avatarSpeaking && (
          <div className="absolute left-3 top-3"><Badge tone="sage"><Dot pulse /> Speaking your message</Badge></div>
        )}
      </div>
      <p className="px-4 py-3 text-xs text-muted">
        Everyone in the room sees this is an AI avatar. It says only messages you confirm, word for word, and does not listen or answer.
      </p>
    </Panel>
  )
}
