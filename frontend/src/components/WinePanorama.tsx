import { useT } from '../i18n'
import { Card, CardHeader } from './ui/Card'

interface WineNums { targetHours?: number; thresholdHours?: number }
interface BuyStatus { deficit?: number; spent?: number; bought?: number; dryRun?: boolean; critical?: boolean }

/**
 * B6 — one-glance view of the empire's wine strategy: per-city runway against the
 * balancer's thresholds, empire totals, and what the market buyer last did. Read-only;
 * sits above the wine controls so the whole picture reads next to the knobs.
 */
export function WinePanorama({ resourcesData, wine, buyStatus }: {
  resourcesData: Record<string, any>
  wine: WineNums | null
  buyStatus: BuyStatus | null
}) {
  const t = useT()
  const target = wine?.targetHours ?? 72
  const threshold = wine?.thresholdHours ?? 24

  const cities = Object.entries(resourcesData)
    .filter(([, d]) => d && typeof d.Wine === 'number')
    .map(([name, d]) => {
      const stock = Number(d.Wine) || 0
      const cons = Number(d.wineConsumptionPerHour) || 0
      const prod = Number(d.wineProductionPerHour) || 0
      const runsOut = d.wineRunsOutIn
      const runwayH = cons > 0 && runsOut != null && runsOut > 0 ? runsOut / 3600 : null
      let status: 'crit' | 'low' | 'ok' | 'idle'
      if (cons === 0) status = 'idle'
      else if (runwayH != null && runwayH < threshold) status = 'crit'
      else if (runwayH != null && runwayH < target) status = 'low'
      else status = 'ok'
      return { name, stock, cons, prod, runwayH, status }
    })
    .sort((a, b) => {
      const ra = a.runwayH ?? Infinity, rb = b.runwayH ?? Infinity
      return ra - rb
    })

  if (cities.length === 0) return null

  const totalWine = cities.reduce((s, c) => s + c.stock, 0)
  const totalCons = cities.reduce((s, c) => s + c.cons, 0)
  const totalProd = cities.reduce((s, c) => s + c.prod, 0)
  const empireRunway = totalCons > 0 ? totalWine / totalCons : null
  const nCrit = cities.filter(c => c.status === 'crit').length
  const nLow = cities.filter(c => c.status === 'low').length

  const COLOR = { crit: '#dc2626', low: '#d97706', ok: '#059669', idle: '#94a3b8' }
  const fmtH = (h: number | null) => h == null ? '—' : h >= 1000 ? `${Math.round(h / 24)}d` : `${Math.round(h)}h`
  const nf = (n: number) => n.toLocaleString()

  return (
    <Card className="mb-4">
      <CardHeader icon="fa-wine-glass" title={t('winepanorama_title')} />
      <div className="p-4 space-y-4">
        {/* Empire tiles */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Tile label={t('winepanorama_total')} value={nf(totalWine)} sub="🍷" />
          <Tile label={t('winepanorama_cons')} value={`${nf(totalCons)}/h`}
                sub={totalProd > 0 ? `+${nf(totalProd)}/h prod` : t('winepanorama_noprod')} />
          <Tile label={t('winepanorama_runway')} value={fmtH(empireRunway)}
                sub={empireRunway != null && empireRunway < threshold ? t('winepanorama_crit') : ''} accent={empireRunway != null && empireRunway < threshold} />
          <Tile label={t('winepanorama_buyer')}
                value={buyStatus ? nf(buyStatus.spent ?? 0) : '—'}
                sub={buyStatus ? `${t('winepanorama_deficit')} ${nf(buyStatus.deficit ?? 0)}${buyStatus.dryRun ? ' · dry' : ''}` : t('winepanorama_nobuy')} />
        </div>

        {/* Legend */}
        <div className="flex items-center gap-3 text-xs text-slate-500 flex-wrap">
          <span><i className="fa-solid fa-circle" style={{ color: COLOR.crit, fontSize: 8 }} /> &lt;{threshold}h {t('winepanorama_leg_crit')}</span>
          <span><i className="fa-solid fa-circle" style={{ color: COLOR.low, fontSize: 8 }} /> &lt;{target}h {t('winepanorama_leg_low')}</span>
          <span><i className="fa-solid fa-circle" style={{ color: COLOR.ok, fontSize: 8 }} /> {t('winepanorama_leg_ok')}</span>
          <span><i className="fa-solid fa-circle" style={{ color: COLOR.idle, fontSize: 8 }} /> {t('winepanorama_leg_idle')}</span>
          {(nCrit > 0 || nLow > 0) && (
            <span className="ml-auto font-medium text-slate-600">
              {nCrit > 0 && <span className="text-red-600">{nCrit} {t('winepanorama_leg_crit')}</span>}
              {nCrit > 0 && nLow > 0 && ' · '}
              {nLow > 0 && <span className="text-amber-600">{nLow} {t('winepanorama_leg_low')}</span>}
            </span>
          )}
        </div>

        {/* Per-city runway bars */}
        <div className="grid sm:grid-cols-2 gap-x-6 gap-y-1.5">
          {cities.map(c => {
            const pct = c.runwayH == null ? 0 : Math.max(3, Math.min(100, (c.runwayH / target) * 100))
            return (
              <div key={c.name} className="flex items-center gap-3 text-sm">
                <span className="w-32 truncate text-slate-700" title={c.name}>{c.name}</span>
                <div className="flex-1 h-2 rounded-full bg-slate-100 overflow-hidden">
                  <div className="h-full rounded-full" style={{ width: `${pct}%`, background: COLOR[c.status] }} />
                </div>
                <span className="w-24 text-right tabular-nums text-xs">
                  {c.status === 'idle'
                    ? <span className="text-slate-400">{t('winepanorama_idle')}</span>
                    : <><b style={{ color: COLOR[c.status] }}>{fmtH(c.runwayH)}</b> <span className="text-slate-400">· {nf(c.stock)}</span></>}
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </Card>
  )
}

function Tile({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: boolean }) {
  return (
    <div className={`rounded-xl border p-3 ${accent ? 'border-red-200 bg-red-50' : 'border-slate-200 bg-slate-50'}`}>
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`text-xl font-bold tabular-nums mt-0.5 ${accent ? 'text-red-600' : 'text-slate-800'}`}>{value}</div>
      {sub && <div className="text-xs text-slate-400 mt-0.5 truncate">{sub}</div>}
    </div>
  )
}
