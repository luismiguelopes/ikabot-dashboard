import { useCallback, useEffect, useRef, useState } from 'react'
import { apiAction } from '../api'

export interface SettingsState<T> {
  /** null until the first load answers. */
  data: T | null
  /** Change the local draft (nothing is sent). */
  set: (patch: Partial<T>) => void
  /** POST the draft (or `next`, which also becomes the draft). True only on a 2xx.
   *  On failure the draft is kept; with `next` the stored values are reloaded instead. */
  save: (next?: T) => Promise<boolean>
  /** Change and save in one go — for toggles and fields that save themselves. */
  saveNow: (patch: Partial<T>) => Promise<boolean>
  reload: () => void
  saving: boolean
  /** True for a few seconds after a save the server accepted. */
  saved: boolean
}

// Every settings card did the same thing by hand: read a JSON, edit it, POST the whole object,
// say "saved" (P13.53). One hook: "saved" only on a 2xx, the values the server stored (it clamps)
// replace the draft, and a failed save reloads so the card shows what is really stored.
// The server's answer is expected as `{ settings: {...} }`; keys it does not return (e.g.
// `lastRun` on the consolidation) are kept.
export function useSettings<T extends object>(url: string, postUrl: string = url): SettingsState<T> {
  const [data, setData] = useState<T | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const dataRef = useRef<T | null>(null)
  dataRef.current = data
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const reload = useCallback(() => {
    fetch(url).then(r => (r.ok ? r.json() : null)).then(d => { if (d && typeof d === 'object') setData(d as T) }).catch(() => {})
  }, [url])

  useEffect(() => { reload() }, [reload])
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])

  const set = useCallback((patch: Partial<T>) => {
    setData(prev => (prev ? { ...prev, ...patch } : prev))
    setSaved(false)
  }, [])

  const save = useCallback(async (next?: T) => {
    const body = next ?? dataRef.current
    if (!body) return false
    if (next) setData(next)
    setSaving(true); setSaved(false)
    const r = await apiAction(postUrl, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    })
    setSaving(false)
    // A field that saves itself reloads on failure, so it shows what is really stored; a card
    // with a Save button keeps the draft, so the user can fix it and try again.
    if (!r) { if (next) reload(); return false }
    const stored = r.settings as Partial<T> | undefined
    if (stored && typeof stored === 'object') setData(prev => ({ ...(prev ?? body), ...stored } as T))
    setSaved(true)
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => setSaved(false), 3000)
    return true
  }, [postUrl, reload])

  const saveNow = useCallback((patch: Partial<T>) => {
    const cur = dataRef.current
    if (!cur) return Promise.resolve(false)
    return save({ ...cur, ...patch })
  }, [save])

  return { data, set, save, saveNow, reload, saving, saved }
}
