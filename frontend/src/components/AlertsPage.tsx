import { useState } from 'react'
import { useT, useLang } from '../i18n'
import { fmt, fmtDuration } from '../utils'
import { MATERIALS, ALERT_DEFAULTS } from '../constants'
import { Card } from './ui/Card'
import { PageHeader } from './ui/PageHeader'
import type { ApiData, AlertThresholds } from '../types'

function ThresholdInput({ label, value, onChange, min, max, unit }: {
  label: string; value: number; onChange: (v: number) => void; min: number; max: number; unit: string
}) {
  return (
    <div className="flex items-center gap-2">
      <label className="text-xs text-slate-500 whitespace-nowrap">{label}</label>
      <input
        type="number"
        min={min} max={max}
        value={value}
        onChange={e => onChange(Math.max(min, Math.min(max, Number(e.target.value))))}
        className="w-16 border border-slate-200 rounded-lg px-2 py-1 text-xs text-center bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400"
      />
      <span className="text-xs text-slate-400">{unit}</span>
    </div>
  )
}

export function AlertsPage({ data, thresholds, onSaveThresholds }: {
  data: ApiData
  thresholds: AlertThresholds
  onSaveThresholds: (t: AlertThresholds) => void
}) {
  const t = useT()
  const lang = useLang() as 'pt' | 'en'
  const { resourcesData, statusSummary: s } = data
  const [draft, setDraft] = useState(thresholds)
  const [settingsOpen, setSettingsOpen] = useState(false)

  const isDirty = JSON.stringify(draft) !== JSON.stringify(thresholds)

  const handleSave = () => { onSaveThresholds(draft); setSettingsOpen(false) }
  const handleReset = () => { setDraft({ ...ALERT_DEFAULTS }) }

  const alerts: Array<{ level: string; icon: string; color: string; msg: string }> = []

  Object.entries(resourcesData).forEach(([city, d]) => {
    const wine = d.wineRunsOutIn
    if (wine !== -1 && wine !== undefined) {
      if (wine < thresholds.wineCritical * 3600)
        alerts.push({ level: 'critical', icon: 'fa-wine-bottle', color: 'text-red-600 bg-red-50 border-red-200', msg: t('alert_wine_critical', { city, duration: fmtDuration(wine) }) })
      else if (wine < thresholds.wineWarning * 3600)
        alerts.push({ level: 'warning', icon: 'fa-wine-bottle', color: 'text-yellow-700 bg-yellow-50 border-yellow-200', msg: t('alert_wine_warning', { city, duration: fmtDuration(wine) }) })
    }
  })

  Object.entries(resourcesData).forEach(([city, d]) => {
    const cap = d.storageCapacity
    if (!cap) return
    MATERIALS.forEach(m => {
      const val = d[m.en as keyof typeof d] as number
      if (val != null && val / cap >= thresholds.storageWarning / 100)
        alerts.push({ level: 'warning', icon: m.icon, color: 'text-yellow-700 bg-yellow-50 border-yellow-200', msg: t('alert_storage', { city, resource: m[lang], pct: String(Math.round(val/cap*100)) }) })
    })
  })

  if (s.gold.production < 0)
    alerts.push({ level: 'critical', icon: 'fa-coins', color: 'text-red-600 bg-red-50 border-red-200', msg: t('alert_gold_neg', { val: fmt(s.gold.production) }) })

  if (s.ships.available === 0 && s.ships.total > 0)
    alerts.push({ level: 'info', icon: 'fa-ship', color: 'text-blue-600 bg-blue-50 border-blue-200', msg: t('alert_ships_busy', { n: String(s.ships.total) }) })

  const critical = alerts.filter(a => a.level === 'critical')
  const warning  = alerts.filter(a => a.level === 'warning')
  const info     = alerts.filter(a => a.level === 'info')

  return (
    <div>
      <PageHeader icon="fa-triangle-exclamation" title={`${t('nav_alerts')} (${alerts.length})`}>
        <button
          onClick={() => { setDraft(thresholds); setSettingsOpen(v => !v) }}
          className={`flex items-center gap-2 px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors ${
            settingsOpen ? 'bg-indigo-600 text-white border-indigo-600' : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
          }`}
        >
          <i className="fa-solid fa-sliders" /> {t('configure')}
        </button>
      </PageHeader>

      {settingsOpen && (
        <Card className="mb-4">
          <div className="px-5 py-4">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">{t('thresholds_title')}</p>
            <div className="flex flex-wrap gap-6 items-end">
              <div className="space-y-2">
                <p className="text-xs font-medium text-slate-600 flex items-center gap-1.5">
                  <i className="fa-solid fa-wine-bottle text-red-400" /> {t('wine_group')}
                </p>
                <ThresholdInput label={t('warning_below')}  value={draft.wineWarning}  onChange={v => setDraft(d => ({ ...d, wineWarning: v }))}  min={1} max={72} unit="h" />
                <ThresholdInput label={t('critical_below')} value={draft.wineCritical} onChange={v => setDraft(d => ({ ...d, wineCritical: v }))} min={1} max={24} unit="h" />
              </div>
              <div className="space-y-2">
                <p className="text-xs font-medium text-slate-600 flex items-center gap-1.5">
                  <i className="fa-solid fa-warehouse text-slate-400" /> {t('storage_group')}
                </p>
                <ThresholdInput label={t('warning_above')} value={draft.storageWarning} onChange={v => setDraft(d => ({ ...d, storageWarning: v }))} min={50} max={99} unit="%" />
              </div>
              <div className="flex items-center gap-2 pb-0.5">
                <button onClick={handleSave}
                  className="px-4 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-medium rounded-lg transition-colors">
                  {t('save')}
                </button>
                <button onClick={handleReset}
                  className="px-3 py-1.5 text-xs text-slate-500 hover:text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors">
                  {t('reset')}
                </button>
                {!isDirty && !settingsOpen && null}
              </div>
            </div>
            <p className="mt-3 text-[11px] text-slate-400">
              {t('thresholds_note', { ww: String(ALERT_DEFAULTS.wineWarning), wc: String(ALERT_DEFAULTS.wineCritical), sw: String(ALERT_DEFAULTS.storageWarning) })}
            </p>
          </div>
        </Card>
      )}

      {alerts.length === 0 ? (
        <Card className="p-10 text-center">
          <i className="fa-solid fa-circle-check text-4xl text-emerald-400 mb-3 block" />
          <p className="text-slate-600 font-semibold">{t('all_good')}</p>
          <p className="text-slate-400 text-sm mt-1">{t('no_alerts')}</p>
        </Card>
      ) : (
        <div className="space-y-3">
          {[...critical, ...warning, ...info].map((a, i) => (
            <div key={i} className={`flex items-center gap-3 px-4 py-3 rounded-xl border ${a.color}`}>
              <i className={`fa-solid ${a.icon} text-lg flex-shrink-0`} />
              <span className="text-sm font-medium">{a.msg}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
