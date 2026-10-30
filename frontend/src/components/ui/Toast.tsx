import { useEffect, useState } from 'react'

// Global toast system. Unlike the old per-component toast state, this one has a
// module-level emitter so plain functions (e.g. the apiAction helper in src/api.ts)
// can surface failures without threading a setter through every call site.
export type ToastKind = 'ok' | 'error' | 'info'

export interface ToastItem {
  id: number
  msg: string
  kind: ToastKind
}

type Listener = (t: ToastItem) => void
const listeners = new Set<Listener>()
let seq = 0

export function pushToast(msg: string, kind: ToastKind = 'info') {
  const item: ToastItem = { id: ++seq, msg, kind }
  listeners.forEach(l => l(item))
}

const ICON: Record<ToastKind, string> = {
  ok: 'fa-check',
  error: 'fa-xmark',
  info: 'fa-circle-info',
}
const BG: Record<ToastKind, string> = {
  ok: 'bg-emerald-500',
  error: 'bg-red-500',
  info: 'bg-slate-700',
}

// Mounted once at the app root. Subscribes to the module emitter and renders a
// bottom-right stack, auto-dismissing each toast after a few seconds.
export function ToastHost() {
  const [items, setItems] = useState<ToastItem[]>([])

  useEffect(() => {
    const l: Listener = t => {
      setItems(prev => [...prev, t])
      setTimeout(() => setItems(prev => prev.filter(x => x.id !== t.id)), t.kind === 'error' ? 6000 : 4000)
    }
    listeners.add(l)
    return () => { listeners.delete(l) }
  }, [])

  if (items.length === 0) return null
  return (
    <div className="fixed bottom-6 right-6 z-[60] flex flex-col gap-2 items-end" role="status" aria-live="polite">
      {items.map(t => (
        <div
          key={t.id}
          onClick={() => setItems(prev => prev.filter(x => x.id !== t.id))}
          className={`flex items-center gap-2 px-4 py-3 rounded-xl shadow-lg text-sm text-white cursor-pointer max-w-sm ${BG[t.kind]}`}
        >
          <i className={`fa-solid ${ICON[t.kind]} shrink-0`} />
          <span className="break-words">{t.msg}</span>
        </div>
      ))}
    </div>
  )
}
