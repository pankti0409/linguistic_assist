'use client'

// The laptop webcam, as the backend sees it. The backend owns the device (R1), so the browser
// never calls getUserMedia: the picture is the backend's in-memory MJPEG self-view, and the
// overlays are its live face / mouth / gesture / lip results.

import { AnimatePresence, motion } from 'motion/react'
import { Camera, CameraOff, Hand, RefreshCw, ScanFace, Waves } from 'lucide-react'
import { useEffect, useState } from 'react'

import { previewUrl } from '@/lib/api'
import { useBackend } from '@/lib/backend'
import { cn } from '@/lib/utils'

import { Badge, Button, Dot } from './ui/kit'

const ACTIVE_LEVEL = 0.035 // backend MOUTH_ON_STD default; the meter marks it
const GESTURE_TTL_MS = 2600

export function CameraView({ size = 'md', className }: { size?: 'md' | 'lg'; className?: string }) {
  const { consent, config, camera, mouth, gesture, lip, setConsent, busy, link } = useBackend()
  const [nonce, setNonce] = useState(0)
  const [broken, setBroken] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  const on = consent.camera
  const preview = Boolean(config?.debug_preview)

  useEffect(() => { setBroken(false); setNonce((n) => n + 1) }, [on, preview, camera?.ok])
  useEffect(() => {
    if (!gesture) return
    const id = window.setInterval(() => setNow(Date.now()), 400)
    return () => window.clearInterval(id)
  }, [gesture])

  const freshGesture = gesture && now - gesture.at < GESTURE_TTL_MS ? gesture : null
  const face = mouth?.face_present
  const level = Math.min(1, (mouth?.level ?? 0) / (ACTIVE_LEVEL * 2.5))

  return (
    <div className={cn('relative overflow-hidden rounded-2xl border border-line bg-[#0e1215]', size === 'lg' ? 'aspect-video' : 'aspect-[4/3]', className)}>
      {!on ? (
        <Overlay icon={<CameraOff className="size-6" />} title="Camera is off" body="Gestures and mouth tracking need the laptop webcam.">
          <Button variant="primary" size="sm" loading={busy === 'consent:camera'} onClick={() => setConsent('camera', true)} disabled={link === 'offline'}>
            <Camera className="size-4" /> Turn on camera
          </Button>
        </Overlay>
      ) : camera && !camera.ok && camera.detail !== 'stopped' ? (
        <Overlay icon={<CameraOff className="size-6" />} title="Camera busy or missing" body={`${camera.detail}. Close other apps using the webcam; PS-16 keeps retrying.`} />
      ) : !preview ? (
        <Overlay icon={<ScanFace className="size-6" />} title="Tracking without a picture" body="The webcam is running and tracking your face, but the self-view is off. Set DEBUG_PREVIEW=1 in the backend .env to see yourself." />
      ) : broken ? (
        <Overlay icon={<RefreshCw className="size-6" />} title="Picture paused" body="The preview stream stopped.">
          <Button size="sm" onClick={() => { setBroken(false); setNonce((n) => n + 1) }}><RefreshCw className="size-4" /> Reconnect</Button>
        </Overlay>
      ) : (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          key={nonce}
          src={previewUrl(nonce)}
          alt="Your webcam, mirrored, as the backend sees it"
          onError={() => setBroken(true)}
          className="size-full -scale-x-100 object-cover"
        />
      )}

      {on && (
        <>
          <div className="pointer-events-none absolute inset-x-3 top-3 flex flex-wrap items-center gap-2">
            <Badge tone={face ? 'sage' : 'butter'} className="backdrop-blur-sm">
              <Dot tone={face ? 'sage' : 'butter'} pulse={!face} />
              {mouth ? (face ? 'Face found' : 'Looking for your face') : 'Starting tracking'}
            </Badge>
            {face && mouth?.yaw_deg !== null && mouth?.yaw_deg !== undefined && Math.abs(mouth.yaw_deg) > 25 && (
              <Badge tone="butter">Turn toward the camera</Badge>
            )}
            {lip && (
              <Badge tone={lip.status === 'ok' ? 'butter' : 'neutral'} className="max-w-full truncate">
                Lips: {lip.status === 'ok' ? `“${lip.text}” (weak hint)` : lip.status === 'unavailable' ? 'not installed' : 'unclear'}
              </Badge>
            )}
          </div>

          <AnimatePresence>
            {freshGesture && (
              <motion.div
                key={freshGesture.at}
                initial={{ opacity: 0, y: 8, filter: 'blur(4px)' }}
                animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
                exit={{ opacity: 0, transition: { duration: 0.15 } }}
                transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
                className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2"
                role="status"
              >
                <div className="flex items-center gap-2 rounded-2xl bg-lavender px-4 py-3 text-lavender-ink shadow-lift">
                  <Hand className="size-5" aria-hidden />
                  <span className="text-lg font-bold">{freshGesture.word ?? prettyToken(freshGesture.token)}</span>
                  {!freshGesture.word && <span className="text-xs font-bold opacity-80">not in your lexicon</span>}
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          <div className="absolute inset-x-3 bottom-3 flex items-center gap-3 rounded-xl bg-black/55 px-3 py-2 text-white backdrop-blur-sm">
            <Waves className="size-4 shrink-0" aria-hidden />
            <span className="text-xs font-bold">{mouth?.active ? 'Mouth moving' : 'Mouth still'}</span>
            <div className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-white/20" aria-hidden>
              <div className="absolute inset-y-0 left-0 rounded-full bg-[#a8d5b6] transition-[width] duration-200" style={{ width: `${level * 100}%` }} />
              <div className="absolute inset-y-0 w-px bg-white/70" style={{ left: `${(1 / 2.5) * 100}%` }} />
            </div>
            <span className="sr-only" aria-live="polite">{mouth?.active ? 'Mouth movement detected' : ''}</span>
          </div>
        </>
      )}
    </div>
  )
}

function Overlay({ icon, title, body, children }: { icon: React.ReactNode; title: string; body: string; children?: React.ReactNode }) {
  return (
    <div className="absolute inset-0 grid grid-cols-1 place-items-center bg-[radial-gradient(120%_90%_at_50%_0%,#26313a_0%,#0e1215_70%)] p-6 text-center text-white">
      <div className="flex max-w-xs flex-col items-center gap-3">
        <span className="grid grid-cols-1 size-12 place-items-center rounded-2xl bg-white/10">{icon}</span>
        <p className="text-base font-bold">{title}</p>
        <p className="text-sm text-white/75">{body}</p>
        {children}
      </div>
    </div>
  )
}

export function prettyToken(token: string): string {
  const [label, hand] = token.split('|')
  return `${label.replace(/_/g, ' ')}${hand && hand !== '*' ? ` · ${hand.toLowerCase()} hand` : ''}`
}
