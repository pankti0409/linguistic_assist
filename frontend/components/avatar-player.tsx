'use client'

// Receive-only avatar player (R4). Joins the Tavus room with Daily's call object and NO
// devices (videoSource / audioSource false), so the browser never asks for the camera or
// microphone, then plays only the avatar's remote video and audio. Replaces embedding Tavus'
// full meeting page, which always shows a camera/mic permission prompt.

import Daily, { type DailyCall, type DailyEventObjectTrack } from '@daily-co/daily-js'
import { Loader2, Volume2, VolumeX } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Button } from './ui/kit'

type Phase = 'joining' | 'waiting' | 'live' | 'error'

export function AvatarPlayer({ url }: { url: string }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const [phase, setPhase] = useState<Phase>('joining')
  const [error, setError] = useState('')
  const [muted, setMuted] = useState(false)
  const [needsTap, setNeedsTap] = useState(false)

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

    ;(async () => {
      try {
        call = Daily.createCallObject({
          videoSource: false,
          audioSource: false,
          subscribeToTracksAutomatically: true,
        })
        call.on('track-started', attach)
        call.on('track-stopped', detach)
        call.on('error', (e) => { setError(e?.errorMsg ?? 'Avatar connection error'); setPhase('error') })
        await call.join({ url, startVideoOff: true, startAudioOff: true, userName: 'PS-16 viewer' })
        if (!cancelled) setPhase((p) => (p === 'live' ? p : 'waiting'))
      } catch (e) {
        if (!cancelled) { setError(e instanceof Error ? e.message : 'Could not join the avatar room'); setPhase('error') }
      }
    })()

    return () => {
      cancelled = true
      const c = call
      call = null
      if (c) c.leave().catch(() => undefined).finally(() => { c.destroy().catch(() => undefined) })
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
            ) : (
              <>
                <Loader2 className="size-7 animate-spin" aria-hidden />
                <p className="font-bold">{phase === 'joining' ? 'Connecting to your avatar…' : 'Waiting for the avatar to appear…'}</p>
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
