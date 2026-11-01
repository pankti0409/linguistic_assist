'use client'

// Receive-only avatar player (R4). Joins the Tavus room with Daily's call object and NO
// devices (videoSource / audioSource false), so the browser never asks for the camera or
// microphone, then plays only the avatar's remote video and audio. Replaces embedding Tavus'
// full meeting page, which always shows a camera/mic permission prompt.

import Daily, {
  type DailyCall,
  type DailyEventObjectParticipantLeft,
  type DailyEventObjectTrack,
} from '@daily-co/daily-js'
import { Loader2, Volume2, VolumeX } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Button } from './ui/kit'

type Phase = 'joining' | 'waiting' | 'live' | 'ended' | 'error'

// The backend joins the same room as a silent relay; it is not the avatar.
const RELAY_NAME = 'ps16-relay'

// Serialise call creation and destruction across mounts/Strict-Mode so Daily never throws
// "Duplicate DailyIframe instances are not allowed."
let callLock: Promise<void> = Promise.resolve()

export function AvatarPlayer({ url, onEnded }: { url: string; onEnded?: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const [phase, setPhase] = useState<Phase>('joining')
  const [error, setError] = useState('')
  const [muted, setMuted] = useState(false)
  const [needsTap, setNeedsTap] = useState(false)
  const onEndedRef = useRef(onEnded)
  onEndedRef.current = onEnded

  useEffect(() => {
    let call: DailyCall | null = null
    let cancelled = false

    const attach = (ev?: DailyEventObjectTrack) => {
      if (!ev || !ev.participant || ev.participant.local) return
      if (ev.type === 'video' && videoRef.current) {
        videoRef.current.srcObject = new MediaStream([ev.track])
        setPhase('live')
      }
      if (ev.type === 'audio' && audioRef.current) {
        audioRef.current.srcObject = new MediaStream([ev.track])
        audioRef.current.play().then(() => setNeedsTap(false)).catch(() => setNeedsTap(true))
      }
    }
    const detach = (ev?: DailyEventObjectTrack) => {
      if (!ev || ev.participant?.local) return
      if (ev.type === 'video' && videoRef.current) { videoRef.current.srcObject = null; setPhase('waiting') }
      if (ev.type === 'audio' && audioRef.current) audioRef.current.srcObject = null
    }
    // Without this a closed room keeps showing the avatar's last frame, which looks alive.
    const ended = () => {
      if (cancelled) return
      if (videoRef.current) videoRef.current.srcObject = null
      if (audioRef.current) audioRef.current.srcObject = null
      setPhase('ended')
      onEndedRef.current?.()
    }
    const onLeft = (ev?: DailyEventObjectParticipantLeft) => {
      const gone = ev?.participant.session_id
      const others = Object.values(call?.participants() ?? {}).filter(
        (p) => !p.local && p.user_name !== RELAY_NAME && p.session_id !== gone,
      )
      if (others.length === 0) ended()
    }

    callLock = callLock.then(async () => {
      if (cancelled) return
      try {
        const existing = Daily.getCallInstance()
        if (existing) {
          try { await existing.destroy() } catch { /* ignore */ }
        }
        if (cancelled) return

        call = Daily.createCallObject({
          videoSource: false,
          audioSource: false,
          subscribeToTracksAutomatically: true,
        })
        call.on('track-started', attach)
        call.on('track-stopped', detach)
        call.on('participant-left', onLeft)
        call.on('left-meeting', ended)
        call.on('error', (e) => { setError(e?.errorMsg ?? 'Avatar connection error'); setPhase('error') })
        await call.join({ url, startVideoOff: true, startAudioOff: true, userName: 'PS-16 viewer' })
        if (!cancelled) setPhase((p) => (p === 'live' ? p : 'waiting'))
      } catch (e) {
        if (!cancelled) { setError(e instanceof Error ? e.message : 'Could not join the avatar room'); setPhase('error') }
      }
    })

    return () => {
      cancelled = true
      callLock = callLock.then(async () => {
        const c = call || Daily.getCallInstance()
        call = null
        if (c) {
          try { await c.leave() } catch { /* ignore */ }
          try { await c.destroy() } catch { /* ignore */ }
        }
      })
    }
  }, [url])

  return (
    <div className="relative size-full">
      <video ref={videoRef} autoPlay playsInline muted className="size-full object-contain" />
      <audio ref={audioRef} autoPlay muted={muted} />
      {phase !== 'live' && (
        <div className="absolute inset-0 grid place-items-center p-6 text-center text-white">
          <div className="flex max-w-sm flex-col items-center gap-3">
            {phase === 'error' ? (
              <>
                <p className="font-bold">Avatar could not connect</p>
                <p className="text-sm text-white/75">{error}. Messages are still spoken on this device.</p>
              </>
            ) : phase === 'ended' ? (
              <>
                <p className="font-bold">The avatar session has ended</p>
                <p className="text-sm text-white/75">Start it again to have the avatar speak. Messages are still spoken on this device.</p>
              </>
            ) : (
              <>
                <Loader2 className="size-7 animate-spin" aria-hidden />
                <p className="font-bold">{phase === 'joining' ? 'Connecting to your avatar.' : 'Waiting for the avatar to appear.'}</p>
                <p className="text-sm text-white/75">Your camera and microphone stay off.</p>
              </>
            )}
          </div>
        </div>
      )}
      {phase === 'live' && (
        <div className="absolute bottom-3 right-3 flex gap-2">
          {needsTap && (
            <Button size="sm" variant="primary" onClick={() => audioRef.current?.play().then(() => setNeedsTap(false)).catch(() => undefined)}>
              <Volume2 className="size-4" aria-hidden /> Tap to hear the avatar
            </Button>
          )}
          <Button size="sm" variant="secondary" aria-label={muted ? 'Unmute avatar' : 'Mute avatar'} onClick={() => setMuted(!muted)}>
            {muted ? <VolumeX className="size-4" aria-hidden /> : <Volume2 className="size-4" aria-hidden />}
          </Button>
        </div>
      )}
    </div>
  )
}
