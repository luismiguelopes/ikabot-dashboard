import type { ReactNode } from 'react'
import { useT } from '../../i18n'
import { Toggle } from '../ui/Toggle'
import { NumberField } from '../ui/NumberField'

export const SELECT_CLS = 'w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400'

/** Small uppercase card title with an icon. */
export function CardTitle({ icon, children, right, className = 'mb-4' }: { icon: string; children: ReactNode; right?: ReactNode; className?: string }) {
  return (
    <p className={`text-xs font-semibold text-slate-500 uppercase tracking-wide flex items-center gap-1.5 ${className}`}>
      <i className={`fa-solid ${icon}`} /> {children}
      {right && <span className="ml-auto normal-case">{right}</span>}
    </p>
  )
}

/** Green "✓ saved" shown after a save the server accepted. */
export function SavedBadge({ show }: { show: boolean }) {
  const t = useT()
  if (!show) return null
  return <span className="text-sm text-emerald-600 font-medium">✓ {t('settings_telegram_saved')}</span>
}

/** A label on the left, a switch on the right. */
export function ToggleRow({ label, on, onChange, onClass, offClass }: {
  label: string; on: boolean; onChange: (v: boolean) => void; onClass?: string; offClass?: string
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-sm text-slate-600">{label}</span>
      <Toggle on={on} onChange={onChange} label={label} onClass={onClass} offClass={offClass} />
    </div>
  )
}

/** A label on the left, a number field on the right (with an optional unit). */
export function NumberRow({ label, value, onCommit, min, max, step, unit, width = 'w-28' }: {
  label: string; value: number; onCommit: (v: number) => void
  min?: number; max?: number; step?: number; unit?: string; width?: string
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-sm text-slate-600">{label}</span>
      <span className="flex items-center gap-2">
        <NumberField value={value} onCommit={onCommit} min={min} max={max} step={step} label={label} className={width} />
        {unit && <span className="text-sm text-slate-400 w-4">{unit}</span>}
      </span>
    </div>
  )
}

/** Primary save button with a spinner. */
export function SaveButton({ onClick, saving = false, disabled = false, label }: {
  onClick: () => void; saving?: boolean; disabled?: boolean; label?: string
}) {
  const t = useT()
  return (
    <button
      onClick={onClick}
      disabled={saving || disabled}
      className="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white text-sm font-medium rounded-lg transition-colors flex items-center gap-2"
    >
      {saving && <i className="fa-solid fa-spinner animate-spin text-xs" />}
      {label ?? t('save')}
    </button>
  )
}
