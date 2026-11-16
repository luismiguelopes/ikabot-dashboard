import { useT, useLang } from '../i18n'
import { fmt, fmtDuration } from '../utils'
import { computeAlerts } from '../alerts'
import type { ExtraAlertSources } from '../alerts'
import { Card } from './ui/Card'
import { PageHeader } from './ui/PageHeader'
import type { ApiData, AlertThresholds } from '../types'

export function AlertsPage({ data, thresholds, extra }: {
  data: ApiData
  thresholds: AlertThresholds
  extra?: ExtraAlertSources
}) {
  const t = useT()
  const lang = useLang() as 'pt' | 'en'

  const COLORS = {
    critical: 'text-red-600 bg-red-50 border-red-200',
    warning:  'text-yellow-700 bg-yellow-50 border-yellow-200',
    info:     'text-blue-600 bg-blue-50 border-blue-200',
  }
  // the list itself comes from the shared definition (also used by the sidebar counter)
  const now = Math.floor(Date.now() / 1000)
  const hhmm = (ts: number) => {
    const d = new Date(ts * 1000)
    const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    return d.toDateString() === new Date().toDateString() ? time : `${d.toLocaleDateString([], { day: 'numeric', month: 'short' })} ${time}`
  }
  const alerts = computeAlerts(data, thresholds, extra).map(a => {
    const color = COLORS[a.level]
    if (a.kind === 'offline')
      return { icon: 'fa-heart-crack', color, msg: t('alert_offline', { t: fmtDuration(a.seconds!) }) }
    if (a.kind === 'incoming')
      return { icon: 'fa-skull-crossbones', color, msg: t('alert_incoming', { n: String(a.value) })
        + (a.at ? ` · ${t('alert_incoming_eta', { t: fmtDuration(Math.max(0, a.at - now)) })}` : '') }
    if (a.kind === 'subsystem')
      return { icon: 'fa-gears', color, msg: t('alert_subsystem', { name: a.name!, n: String(a.value) }), detail: a.error }
    if (a.kind === 'transport_dropped')
      return { icon: 'fa-ship', color, msg: t('alert_transport_dropped', { from: a.origin || '?', to: a.dest || '?', t: a.at ? hhmm(a.at) : '' }), detail: a.error }
    if (a.kind === 'transport_retry')
      return { icon: 'fa-rotate', color, msg: t('alert_transport_retry', { from: a.origin || '?', to: a.dest || '?', n: String(a.value) })
        + (a.at && a.at > now ? ` · ${t('alert_transport_next', { t: fmtDuration(a.at - now) })}` : ''), detail: a.error }
    if (a.kind === 'wine')
      return { icon: 'fa-wine-bottle', color, msg: t(a.level === 'critical' ? 'alert_wine_critical' : 'alert_wine_warning', { city: a.city!, duration: fmtDuration(a.seconds!) }) }
    if (a.kind === 'storage')
      return { icon: a.material!.icon, color, msg: t('alert_storage', { city: a.city!, resource: a.material![lang], pct: String(a.pct) }) }
    if (a.kind === 'gold')
      return { icon: 'fa-coins', color, msg: t('alert_gold_neg', { val: fmt(a.value!) }) }
    return { icon: 'fa-ship', color, msg: t('alert_ships_busy', { n: String(a.value) }) }
  }) as Array<{ icon: string; color: string; msg: string; detail?: string }>

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
          {alerts.map((a, i) => (
            <div key={i} className={`flex items-center gap-3 px-4 py-3 rounded-xl border ${a.color}`}>
              <i className={`fa-solid ${a.icon} text-lg flex-shrink-0`} />
              <div className="min-w-0">
                <div className="text-sm font-medium">{a.msg}</div>
                {a.detail && <div className="text-xs opacity-75 break-words">{a.detail}</div>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
