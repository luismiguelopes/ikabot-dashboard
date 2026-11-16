import { useEffect, useState } from 'react'

// Clamp and round a typed number; an empty or invalid entry keeps the previous value.
export function clampNumber(raw: string, previous: number, min?: number, max?: number, integer = true): number {
  const s = raw.trim()
  let v = s === '' ? NaN : Number(s)
  if (!Number.isFinite(v)) return previous
  if (integer) v = Math.round(v)
  if (min != null && v < min) v = min
  if (max != null && v > max) v = max
  return v
}

const BASE_CLS = 'border border-slate-200 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400'
const SIZE_CLS = {
  sm: 'rounded px-1.5 py-0.5 text-xs',
  md: 'rounded-lg px-2 py-1.5 text-sm',
  lg: 'rounded-lg px-3 py-2 text-sm',
} as const

// A number input that lets you type freely and only limits and reports the value when you leave
// the field (or press Enter) — and only if it changed (P13.52). Limiting on every key made "95"
// with a minimum of 50 come out as 9 → 50 → 505 → 99, and saving on every blur sent one POST per
// field just for tabbing through a card.
export function NumberField({ value, onCommit, min, max, step, integer = true, className = 'w-24', size = 'md', align = 'right', label, id, disabled }: {
  value: number
  onCommit: (v: number) => void
  min?: number
  max?: number
  step?: number
  /** Round to whole numbers (default). */
  integer?: boolean
  /** Width and any extra classes (not padding/size/alignment — use `size` and `align`). */
  className?: string
  size?: keyof typeof SIZE_CLS
  align?: 'right' | 'center'
  /** Accessible name when there is no <label htmlFor>. */
  label?: string
  id?: string
  disabled?: boolean
}) {
  const [draft, setDraft] = useState(String(value))
  const [editing, setEditing] = useState(false)

  // Follow the value from outside (load, server-clamped save) — but never while typing.
  useEffect(() => { if (!editing) setDraft(String(value)) }, [value, editing])

  const commit = () => {
    setEditing(false)
    const v = clampNumber(draft, value, min, max, integer)
    setDraft(String(v))
    if (v !== value) onCommit(v)
  }

  return (
    <input
      type="number"
      inputMode={integer ? 'numeric' : 'decimal'}
      id={id}
      aria-label={label}
      min={min} max={max} step={step}
      value={draft}
      disabled={disabled}
      onFocus={() => setEditing(true)}
      onChange={e => { setEditing(true); setDraft(e.target.value) }}
      onBlur={commit}
      onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
      className={`${BASE_CLS} ${SIZE_CLS[size]} ${align === 'center' ? 'text-center' : 'text-right'} ${className}`}
    />
  )
}
