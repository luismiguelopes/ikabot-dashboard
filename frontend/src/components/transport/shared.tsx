import type { ReactNode } from 'react'
import { useT } from '../../i18n'
import { NumberField } from '../ui/NumberField'
import { Toggle } from '../ui/Toggle'
import { FIELD_CLS, LABEL_CLS } from './types'

/** Label above a full-width number field. */
export function LabeledNumber({ label, value, onCommit, min, max, step }: {
  label: string; value: number; onCommit: (v: number) => void; min?: number; max?: number; step?: number
}) {
  return (
    <label className="block">
      <span className={LABEL_CLS}>{label}</span>
      <NumberField value={value} onCommit={onCommit} min={min} max={max} step={step} size="lg" className={FIELD_CLS} />
    </label>
  )
}

/** A switch with its label to the right ("Enabled"). */
export function ToggleLabel({ on, onChange, label, onClass, offClass }: {
  on: boolean; onChange: (v: boolean) => void; label: string; onClass?: string; offClass?: string
}) {
  return (
    <div className="flex items-center gap-3">
      <Toggle on={on} onChange={onChange} label={label} onClass={onClass} offClass={offClass} />
      <span className="text-sm text-slate-700">{label}</span>
    </div>
  )
}

/** Save button + "saved" line used by every transport card. */
export function SaveRow({ onSave, saving, saved, children }: {
  onSave: () => void; saving: boolean; saved: boolean; children?: ReactNode
}) {
  const t = useT()
  return (
    <>
      {saved && <div className="rounded-lg px-3 py-2 text-sm bg-emerald-50 text-emerald-700">{t('transport_saved')}</div>}
      <div className="flex items-center gap-2">
        <button
          className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40"
          onClick={onSave} disabled={saving}
        >
          <i className={`fa-solid ${saving ? 'fa-spinner fa-spin' : 'fa-floppy-disk'}`} />
          {t('transport_save')}
        </button>
        {children}
      </div>
    </>
  )
}
