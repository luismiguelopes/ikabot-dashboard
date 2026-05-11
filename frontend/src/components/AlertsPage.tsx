import { useT, useLang } from '../i18n'
import { fmt, fmtDuration } from '../utils'
import { MATERIALS } from '../constants'
import { Card } from './ui/Card'
import { PageHeader } from './ui/PageHeader'
import type { ApiData, AlertThresholds } from '../types'

export function AlertsPage({ data, thresholds }: {
  data: ApiData
  thresholds: AlertThresholds
}) {
  const t = useT()
  const lang = useLang() as 'pt' | 'en'
  const { resourcesData, statusSummary: s } = data

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
      <PageHeader icon="fa-triangle-exclamation" title={`${t('nav_alerts')} (${alerts.length})`} />

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
