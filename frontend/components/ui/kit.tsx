'use client'

// One component vocabulary for every screen: same button shapes, same panel, same switch.

import { Loader2 } from 'lucide-react'
import { forwardRef } from 'react'

import { cn } from '@/lib/utils'

type ButtonVariant = 'primary' | 'secondary' | 'quiet' | 'danger' | 'yes' | 'no'
type ButtonSize = 'sm' | 'md' | 'lg' | 'xl'

const variants: Record<ButtonVariant, string> = {
  primary: 'bg-sage-solid text-panel hover:bg-sage-solid-hover dark:text-paper',
  secondary: 'bg-panel text-ink border border-line-strong hover:bg-rail',
  quiet: 'bg-transparent text-ink-soft hover:bg-rail hover:text-ink',
  danger: 'bg-blush text-blush-ink border border-blush-ink/20 hover:border-blush-ink/50',
  yes: 'bg-sage text-sage-ink border border-sage-ink/25 hover:border-sage-ink/60',
  no: 'bg-blush text-blush-ink border border-blush-ink/25 hover:border-blush-ink/60',
}
const sizes: Record<ButtonSize, string> = {
  sm: 'min-h-11 min-w-11 px-3 text-sm gap-1.5 rounded-lg',
  md: 'h-11 px-4 text-[15px] gap-2 rounded-xl',
  lg: 'h-14 px-6 text-base gap-2.5 rounded-xl',
  xl: 'h-20 px-8 text-lg gap-3 rounded-2xl',
}

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', loading, disabled, className, children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        'relative inline-flex select-none items-center justify-center font-bold whitespace-nowrap',
        'transition-[background-color,border-color,color,transform,opacity] duration-150 ease-out',
        'active:scale-[0.98] active:duration-0 disabled:opacity-55 disabled:active:scale-100',
        variants[variant], sizes[size], className,
      )}
      {...rest}
    >
      {loading && <Loader2 className="size-[1.1em] animate-spin" aria-hidden />}
      {children}
    </button>
  )
})

export function Panel({ className, children, as: As = 'section', ...rest }:
  React.HTMLAttributes<HTMLElement> & { as?: 'section' | 'div' | 'article' | 'aside' }) {
  return (
    <As className={cn('rounded-2xl border border-line bg-panel', className)} {...rest}>
      {children}
    </As>
  )
}

export function PanelHeader({ title, aside, id, children }: { title: React.ReactNode; aside?: React.ReactNode; id?: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
      <div className="min-w-[min(100%,14rem)] flex-1">
        <h2 id={id} className="text-lg font-bold leading-tight text-ink">{title}</h2>
        {children && <p className="mt-1 text-sm text-muted">{children}</p>}
      </div>
      {aside && <div className="shrink-0">{aside}</div>}
    </div>
  )
}

export function Switch({ checked, onChange, label, disabled, busy }: {
  checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean; busy?: boolean
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled || busy}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative inline-flex h-11 w-[68px] shrink-0 items-center rounded-full border transition-colors duration-200',
        checked ? 'border-sage-solid bg-sage-solid' : 'border-line-strong bg-rail',
        'disabled:opacity-55',
      )}
    >
      <span
        className={cn(
          'grid grid-cols-1 size-8 place-items-center rounded-full bg-panel shadow-card transition-transform duration-200 ease-out',
          checked ? 'translate-x-8' : 'translate-x-1',
        )}
      >
        {busy && <Loader2 className="size-3.5 animate-spin text-muted" aria-hidden />}
      </span>
    </button>
  )
}

export function Segmented<T extends string>({ value, options, onChange, label, size = 'md' }: {
  value: T; options: { value: T; label: React.ReactNode; disabled?: boolean }[]; onChange: (v: T) => void; label: string; size?: 'sm' | 'md'
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex max-w-full flex-wrap rounded-xl border border-line bg-rail p-1">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          tabIndex={value === o.value || (!options.some((item) => item.value === value && !item.disabled) && options.find((item) => !item.disabled)?.value === o.value) ? 0 : -1}
          disabled={o.disabled}
          onClick={() => onChange(o.value)}
          onKeyDown={(event) => {
            if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return
            event.preventDefault()
            const enabled = options.filter((item) => !item.disabled)
            const index = enabled.findIndex((item) => item.value === o.value)
            const next = event.key === 'Home' ? 0 : event.key === 'End' ? enabled.length - 1
              : (index + (event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 1) + enabled.length) % enabled.length
            onChange(enabled[next].value)
            const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')
            buttons?.[next]?.focus()
          }}
          className={cn(
            'inline-flex items-center gap-1.5 rounded-lg font-bold transition-colors duration-150',
            size === 'sm' ? 'min-h-11 px-2.5 text-[13px]' : 'min-h-11 px-3.5 text-sm',
            value === o.value ? 'bg-panel text-ink shadow-card' : 'text-muted hover:text-ink',
            'disabled:opacity-45',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export type Tone = 'sage' | 'lavender' | 'butter' | 'blush' | 'sky' | 'neutral'
const tones: Record<Tone, string> = {
  sage: 'bg-sage text-sage-ink',
  lavender: 'bg-lavender text-lavender-ink',
  butter: 'bg-butter text-butter-ink',
  blush: 'bg-blush text-blush-ink',
  sky: 'bg-sky text-sky-ink',
  neutral: 'bg-rail text-ink-soft',
}

export function Badge({ tone = 'neutral', className, children }: { tone?: Tone; className?: string; children: React.ReactNode }) {
  return (
    <span className={cn('inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold', tones[tone], className)}>
      {children}
    </span>
  )
}

export function Dot({ tone = 'sage', pulse }: { tone?: 'sage' | 'butter' | 'blush' | 'muted' | 'lavender'; pulse?: boolean }) {
  const color = {
    sage: 'bg-sage-solid', butter: 'bg-butter-ink', blush: 'bg-blush-ink', muted: 'bg-muted', lavender: 'bg-lavender-ink',
  }[tone]
  return (
    <span className="relative inline-flex size-2.5 shrink-0" aria-hidden>
      {pulse && <span className={cn('absolute inline-flex size-full animate-ping rounded-full opacity-60', color)} />}
      <span className={cn('relative inline-flex size-2.5 rounded-full', color)} />
    </span>
  )
}

export function Empty({ icon, title, children, action }: { icon: React.ReactNode; title: string; children?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-xl border border-dashed border-line-strong px-5 py-6">
      <span className="grid grid-cols-1 size-10 place-items-center rounded-xl bg-rail text-ink-soft">{icon}</span>
      <div>
        <p className="font-bold text-ink">{title}</p>
        {children && <p className="mt-1 max-w-prose text-sm text-muted">{children}</p>}
      </div>
      {action}
    </div>
  )
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="grid grid-cols-1 gap-1.5">
      <span className="text-sm font-bold text-ink">{label}</span>
      {children}
      {hint && <span className="text-xs text-muted">{hint}</span>}
    </label>
  )
}

export const inputClass =
  'h-11 w-full rounded-xl border border-line-strong bg-panel px-3.5 text-[15px] text-ink placeholder:text-muted/80 ' +
  'transition-colors focus:border-focus focus:outline-none focus-visible:outline-3 focus-visible:outline-focus/40'

export function ms(v: number | null | undefined): string {
  if (v === null || v === undefined) return 'n/a'
  return v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`
}
