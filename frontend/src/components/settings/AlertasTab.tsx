import { useState } from 'react'
import { useT } from '../../i18n'
import { ALERT_DEFAULTS } from '../../constants'
import { Card } from '../ui/Card'
import { CardTitle, NumberRow } from './shared'
import type { AlertThresholds } from '../../types'

export function AlertasTab({ thresholds, onSaveThresholds }: {
  thresholds: AlertThresholds
  onSaveThresholds: (t: AlertThresholds) => void
}) {
  const t = useT()
  const [draft, setDraft] = useState(thresholds)
  const set = (k: keyof AlertThresholds) => (v: number) => setDraft(d => ({ ...d, [k]: v }))

  return (
    <div className="grid gap-4 max-w-lg">
      <Card>
        <div className="px-5 py-4 space-y-3">
          <CardTitle icon="fa-wine-bottle text-red-400" className="mb-1">{t('wine_group')}</CardTitle>
          <NumberRow label={t('warning_below')}  value={draft.wineWarning}  onCommit={set('wineWarning')}  min={1} max={72} unit="h" width="w-20" />
          <NumberRow label={t('critical_below')} value={draft.wineCritical} onCommit={set('wineCritical')} min={1} max={24} unit="h" width="w-20" />
        </div>
      </Card>

      <Card>
        <div className="px-5 py-4 space-y-3">
          <CardTitle icon="fa-warehouse text-slate-400" className="mb-1">{t('storage_group')}</CardTitle>
          <NumberRow label={t('warning_above')} value={draft.storageWarning} onCommit={set('storageWarning')} min={50} max={99} unit="%" width="w-20" />
        </div>
      </Card>

      <div className="flex gap-2">
        <button
          // not disabled while unchanged: a value typed in a field only counts once the field is
          // left, and a click on a disabled button would be lost
          onClick={() => onSaveThresholds(draft)}
          className="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white text-sm font-medium rounded-lg transition-colors"
        >
          {t('save')}
        </button>
        <button
          onClick={() => setDraft({ ...ALERT_DEFAULTS })}
          className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700 bg-white hover:bg-slate-50 border border-slate-200 rounded-lg transition-colors"
        >
          {t('reset')}
        </button>
      </div>
      <p className="text-xs text-slate-400">
        {t('thresholds_note', { ww: String(ALERT_DEFAULTS.wineWarning), wc: String(ALERT_DEFAULTS.wineCritical), sw: String(ALERT_DEFAULTS.storageWarning) })}
      </p>
    </div>
  )
}
