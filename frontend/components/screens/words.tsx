'use client'

import { BookOpen, Lock, Plus, Trash2, X } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'

import { api, errorText } from '@/lib/api'
import { useBackend } from '@/lib/backend'
import type { PhraseEntry } from '@/lib/types'

import { Badge, Button, Empty, Panel, PanelHeader, inputClass } from '../ui/kit'

export function WordsScreen() {
  const b = useBackend()
  const allowed = b.consent.personalization
  const [terms, setTerms] = useState<string[] | null>(null)
  const [entries, setEntries] = useState<PhraseEntry[] | null>(null)
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const [confirmWipe, setConfirmWipe] = useState(false)

  const load = useCallback(async () => {
    if (!allowed) { setTerms(null); setEntries(null); return }
    try {
      const [t, p] = await Promise.all([api.terms(), api.phrasebook()])
      setTerms(t); setEntries(p)
    } catch (e) { toast.error(errorText(e)) }
  }, [allowed])
  useEffect(() => { load() }, [load])

  const save = async (next: string[]) => {
    setSaving(true)
    try { setTerms(await api.setTerms(next)) } catch (e) { toast.error(errorText(e)) } finally { setSaving(false) }
  }
  const add = () => {
    const parts = draft.split(',').map((s) => s.trim()).filter(Boolean)
    if (!parts.length || !terms) return
    setDraft('')
    save([...terms, ...parts.filter((p) => !terms.includes(p))])
  }
  const wipe = async () => {
    try {
      const r = await api.wipePhrasebook()
      toast.success(`Deleted ${r.deleted} saved sentence${r.deleted === 1 ? '' : 's'}`)
      setEntries([]); setConfirmWipe(false)
    } catch (e) { toast.error(errorText(e)) }
  }

  return (
    <div className="mx-auto grid grid-cols-1 max-w-5xl gap-6">
      <div>
        <h1 className="text-3xl font-bold">My words</h1>
        <p className="mt-2 max-w-prose text-muted">
          Names, places and phrases that are yours. PS-16 may only use a word in a suggestion if you
          said it, your partner said it, or it is listed here.
        </p>
      </div>

      {!allowed && (
        <Panel className="flex flex-wrap items-center gap-4 border-lavender-ink/20 bg-lavender p-5">
          <Lock className="size-5 text-lavender-ink" aria-hidden />
          <p className="min-w-0 flex-1 text-lavender-ink">
            Personal words are switched off. With permission, they are stored only on this computer.
          </p>
          <Button variant="primary" loading={b.busy === 'consent:personalization'} onClick={() => b.setConsent('personalization', true)}>
            Allow personal words
          </Button>
        </Panel>
      )}

      <Panel className="p-6" aria-labelledby="terms-title">
        <PanelHeader id="terms-title" title="Names, places and things" aside={terms && <Badge>{terms.length} / 200</Badge>}>
          Added by you or a caregiver. Used as clues, never invented.
        </PanelHeader>
        <form className="mt-5 flex gap-2" onSubmit={(e) => { e.preventDefault(); add() }}>
          <input
            className={inputClass}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={allowed ? 'e.g. Meera, Apollo Hospital, blanket' : 'Allow personal words first'}
            disabled={!allowed}
            maxLength={300}
            aria-label="New words, separated by commas"
          />
          <Button type="submit" variant="primary" disabled={!allowed || !draft.trim()} loading={saving}><Plus className="size-4" aria-hidden /> Add</Button>
        </form>
        <ul className="mt-4 flex flex-wrap gap-2">
          {allowed && terms === null && [0, 1, 2].map((i) => <li key={i} className="skeleton h-9 w-28" />)}
          {terms?.length === 0 && <li className="text-sm text-muted">No words yet. Start with the people and places you talk about most.</li>}
          {terms?.map((t) => (
            <li key={t} className="inline-flex h-9 items-center gap-1 rounded-full border border-line bg-rail pl-3.5 pr-1 font-bold">
              {t}
              <button aria-label={`Remove ${t}`} className="grid grid-cols-1 size-7 place-items-center rounded-full text-muted hover:bg-panel hover:text-blush-ink"
                onClick={() => save(terms.filter((x) => x !== t))}>
                <X className="size-4" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      </Panel>

      <Panel className="p-6" aria-labelledby="pb-title">
        <PanelHeader id="pb-title" title="Sentences I have said" aside={
          confirmWipe ? (
            <div className="flex items-center gap-2">
              <span className="text-sm text-blush-ink">Delete all?</span>
              <Button size="sm" variant="danger" onClick={wipe}>Delete</Button>
              <Button size="sm" variant="quiet" onClick={() => setConfirmWipe(false)}>Keep</Button>
            </div>
          ) : (
            <Button size="sm" variant="quiet" onClick={() => setConfirmWipe(true)} disabled={entries?.length === 0}>
              <Trash2 className="size-4" aria-hidden /> Delete all
            </Button>
          )
        }>
          Confirmed messages help future suggestions sound like you. Edited ones count double. Rejected ones are never kept.
        </PanelHeader>
        <div className="mt-5">
          {!allowed ? (
            <p className="text-sm text-muted">Hidden while personal words are off. You can still delete them all.</p>
          ) : entries === null ? (
            <div className="grid grid-cols-1 gap-2">{[0, 1].map((i) => <div key={i} className="skeleton h-14" />)}</div>
          ) : entries.length === 0 ? (
            <Empty icon={<BookOpen className="size-5" />} title="No sentences yet">Each message you confirm is added here.</Empty>
          ) : (
            <ul className="divide-y divide-line">
              {[...entries].sort((a, c) => c.uses - a.uses).map((e) => (
                <li key={e.text} className="flex items-center justify-between gap-4 py-3">
                  <span className="font-serif text-lg">{e.text}</span>
                  <Badge tone="sage" className="tabular">{e.uses}×</Badge>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Panel>
    </div>
  )
}
