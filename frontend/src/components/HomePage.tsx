import { useEffect, useState, useMemo } from 'react'
import { useT, useLang } from '../i18n'
import { fmt, fmtDuration } from '../utils'
import { MATERIALS, COST_KEYS } from '../constants'
import { useLiveClock } from '../hooks/useLiveClock'
import { Card, CardHeader } from './ui/Card'
import { PageHeader } from './ui/PageHeader'
import { Th, Td } from './ui/TableCells'
import { StatBadge } from './ui/StatBadge'
import type { ApiData, AlertThresholds, BuildingQueue, BuildingCostsData } from '../types'

export function HomePage({ data, thresholds }: { data: ApiData; thresholds: AlertThresholds }) {
  const t    = useT()
  const lang = useLang() as 'pt' | 'en'
  const now  = useLiveClock()
  const { statusSummary: s, empireData, resourcesData } = data
  const res = s.resources
  const totalAvail = res.available.reduce((a, b) => a + b, 0)
  const totalProd  = res.production.reduce((a, b) => a + b, 0)

  const [queue, setQueue] = useState<BuildingQueue | null>(null)
  const [costsData, setCostsData] = useState<BuildingCostsData | null>(null)
  useEffect(() => {
    fetch('/api/building-queue').then(r => r.json()).then(setQueue).catch(() => {})
    fetch('/api/building-costs').then(r => r.ok ? r.json() : null).then(d => {
      if (d && !(d as any).error) setCostsData(d)
    }).catch(() => {})
  }, [data])

  const goldProd   = s.gold.production
  const goldRunway = goldProd < 0 ? s.gold.total / Math.abs(goldProd) / 24 : null

  const queues     = queue?.queues      || {}
  const inProgress = queue?.inProgress  || {}

  // Active constructions — merges empire.json (isBusy flag) with queue inProgress (accurate ETA).
  // empire._constructionEnds is 0 when construction started after the last full empire cycle,
  // so we prefer inProgress.eta when available and in the future.
  const activeConstructions = useMemo(() => {
    type Entry = { city: string; building: string; fromLevel: number; toLevel: number; eta: number; timeLeft: number }
    const result: Entry[] = []
    const added = new Set<string>()

    Object.entries(empireData).forEach(([city, buildings]) => {
      const busyEntry = Object.entries(buildings)
        .find(([k, v]) => k !== '_constructionEnds' && String(v).endsWith('+'))
      if (!busyEntry) return
      const [building, levelStr] = busyEntry
      const fromLevel = parseInt(String(levelStr))
      const queueEta  = inProgress[city]?.eta ?? 0
      const empireEta = (buildings._constructionEnds as number) || 0
      const eta = (queueEta > now) ? queueEta : empireEta
      result.push({ city, building, fromLevel, toLevel: fromLevel + 1, eta,
                    timeLeft: Math.max(0, eta - now) })
      added.add(city)
    })

    // Cities where queue has inProgress but empire.json not yet updated (stale data)
    Object.entries(inProgress).forEach(([city, ip]) => {
      if (added.has(city) || !ip.eta) return
      result.push({ city, building: ip.building, fromLevel: ip.fromLevel,
                    toLevel: ip.toLevel ?? ip.fromLevel + 1, eta: ip.eta,
                    timeLeft: Math.max(0, ip.eta - now) })
    })

    return result.sort((a, b) => a.timeLeft - b.timeLeft)
  }, [empireData, inProgress, now])
  const queuedCities = Object.entries(queues)
    .filter(([city, items]) => items.length > 0 && !inProgress[city])
    .map(([city, items]) => ({ city, building: items[0].building, targetLevel: items[0].targetLevel, extra: items.length - 1 }))

  // Wine balance
  const criticalSecs  = thresholds.wineCritical * 3600
  const warningSecs   = thresholds.wineWarning  * 3600
  const cityCount     = Object.keys(resourcesData).length

  const wineAtRisk = Object.entries(resourcesData)
    .filter(([, d]) => d.wineRunsOutIn !== -1 && d.wineRunsOutIn >= 0)
    .map(([city, d]) => ({ city, seconds: d.wineRunsOutIn,
                            prod: d.wineProductionPerHour, cons: d.wineConsumptionPerHour }))
    .sort((a, b) => a.seconds - b.seconds)

  const criticalCount = wineAtRisk.filter(w => w.seconds < criticalSecs).length
  const warningCount  = wineAtRisk.filter(w => w.seconds >= criticalSecs && w.seconds < warningSecs).length

  const wineColor = (secs: number) =>
    secs < criticalSecs ? 'text-red-600 bg-red-50 border-red-200' :
    secs < warningSecs  ? 'text-orange-600 bg-orange-50 border-orange-200' :
                          'text-yellow-700 bg-yellow-50 border-yellow-200'

  return (
    <div>
      <PageHeader icon="fa-crown" title={t('home_title')} />

      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4 gap-3 mb-6">
        <StatBadge icon="fa-anchor"       iconColor="text-blue-500"    label={t('ships_available')}  value={fmt(s.ships.available)}    />
        <StatBadge icon="fa-ship"         iconColor="text-blue-600"    label={t('ships_total')}      value={fmt(s.ships.total)}        />
        <StatBadge icon="fa-house"        iconColor="text-emerald-500" label={t('housing_space')}    value={fmt(s.housing.space)}      />
        <StatBadge icon="fa-people-group" iconColor="text-purple-500"  label={t('citizens')}         value={fmt(s.housing.citizens)}   />
        <StatBadge icon="fa-coins"        iconColor="text-yellow-500"  label={t('gold_total')}       value={fmt(s.gold.total)}         />
        <StatBadge icon="fa-chart-line"   iconColor={goldProd < 0 ? 'text-red-500' : 'text-yellow-600'} label={t('gold_production')} value={fmt(s.gold.production)} />
        <StatBadge icon="fa-wine-glass"   iconColor="text-red-400"     label={t('wine_consumption')} value={fmt(s.wine_consumption)}   />
        {goldRunway !== null && (
          <StatBadge
            icon="fa-hourglass-half"
            iconColor="text-red-500"
            label={t('gold_runway')}
            value={goldRunway < 1 ? '< 1d' : `${goldRunway.toFixed(1)}d`}
          />
        )}
      </div>

      <Card>
        <CardHeader icon="fa-boxes-stacked" title={t('resources_card')} />
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="bg-slate-800 text-white text-xs uppercase tracking-wide">
                <Th align="text-left" className="px-5">Type</Th>
                {MATERIALS.map(m => (
                  <Th key={m.en}><i className={`fa-solid ${m.icon} mr-1 ${m.color}`} /> {m[lang]}</Th>
                ))}
                <Th className="text-indigo-300">Total</Th>
              </tr>
            </thead>
            <tbody>
              {[
                { label: t('row_available'),  values: res.available,  total: totalAvail },
                { label: t('row_production'), values: res.production, total: totalProd  },
              ].map((row, ri) => (
                <tr key={ri} className={`border-b border-slate-100 hover:bg-slate-50 ${ri % 2 ? 'bg-slate-50/40' : ''}`}>
                  <Td className="px-5 font-semibold text-slate-600">{row.label}</Td>
                  {row.values.map((v, i) => (
                    <Td key={i} className="text-center font-mono text-slate-700">{fmt(v)}</Td>
                  ))}
                  <Td className="text-center font-bold font-mono text-indigo-600">{fmt(row.total)}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-4">

        {/* Construction & Queue card */}
        <Card>
          <CardHeader icon="fa-hammer" title={t('home_constr_queue_title')} />
          {activeConstructions.length === 0 && queuedCities.length === 0 ? (
            <p className="px-5 pb-4 text-sm text-slate-400">{t('home_no_active_constr')}</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {activeConstructions.map(({ city, building, fromLevel, toLevel, timeLeft }) => (
                <li key={city} className="flex items-center gap-3 px-5 py-2.5 hover:bg-slate-50">
                  <i className="fa-solid fa-hammer text-orange-400 text-xs w-3 shrink-0" />
                  <span className="font-semibold text-sm text-slate-700 w-28 shrink-0 truncate">{city}</span>
                  <span className="text-sm text-slate-600 flex-1 truncate">
                    {building}
                    <span className="ml-1.5 text-xs text-slate-400 font-mono">
                      {t('home_constr_lv')}{fromLevel}→{toLevel}
                    </span>
                  </span>
                  <span className={`text-xs font-mono shrink-0 ${timeLeft === 0 ? 'text-green-600 font-semibold' : 'text-orange-500'}`}>
                    {timeLeft === 0 ? t('home_constr_done') : fmtDuration(timeLeft)}
                  </span>
                </li>
              ))}
              {queuedCities.map(({ city, building, targetLevel, extra }) => (
                <li key={city} className="flex items-center gap-3 px-5 py-2.5 hover:bg-slate-50">
                  <i className="fa-solid fa-hourglass-half text-slate-400 text-xs w-3 shrink-0" />
                  <span className="font-semibold text-sm text-slate-500 w-28 shrink-0 truncate">{city}</span>
                  <span className="text-sm text-slate-500 flex-1 truncate">
                    {building}
                    <span className="ml-1.5 text-xs text-slate-400 font-mono">→{targetLevel}</span>
                    {extra > 0 && (
                      <span className="ml-2 text-xs text-indigo-400">{t('home_queue_items', { n: extra })}</span>
                    )}
                  </span>
                  <span className="text-xs text-slate-400 shrink-0">{t('home_queue_waiting')}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        {/* Wine balance card */}
        <Card>
          <CardHeader icon="fa-wine-bottle" title={t('home_wine_risk')}>
            {(criticalCount > 0 || warningCount > 0) && (
              <div className="flex gap-2 text-xs font-medium">
                {criticalCount > 0 && (
                  <span className="px-2 py-0.5 rounded-full bg-red-100 text-red-600">
                    {t('wine_critical_count', { n: criticalCount })}
                  </span>
                )}
                {warningCount > 0 && (
                  <span className="px-2 py-0.5 rounded-full bg-orange-100 text-orange-600">
                    {t('wine_warning_count', { n: warningCount })}
                  </span>
                )}
              </div>
            )}
          </CardHeader>
          {wineAtRisk.length === 0 ? (
            <p className="px-5 pb-4 text-sm text-slate-400">
              {t('wine_all_safe_count', { n: cityCount })}
            </p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {wineAtRisk.map(({ city, seconds, prod, cons }) => (
                <li key={city} className="flex items-center gap-3 px-5 py-2.5 hover:bg-slate-50">
                  <i className="fa-solid fa-wine-bottle text-red-400 text-xs w-3 shrink-0" />
                  <span className="font-semibold text-sm text-slate-700 w-28 shrink-0 truncate">{city}</span>
                  <span className="text-xs text-slate-400 flex-1 font-mono">
                    {fmt(prod)}/{fmt(cons)} /h
                  </span>
                  <span className={`text-xs font-mono font-semibold px-2 py-0.5 rounded border shrink-0 ${wineColor(seconds)}`}>
                    {fmtDuration(seconds)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

      </div>

      {/* Resource Balance Matrix */}
      <ResourceMatrix data={data} queue={queue} costsData={costsData} />

    </div>
  )
}

function ResourceMatrix({ data, queue, costsData }: {
  data: ApiData
  queue: BuildingQueue | null
  costsData: BuildingCostsData | null
}) {
  const t    = useT()
  const lang = useLang() as 'pt' | 'en'

  const cityNames = Object.keys(data.resourcesData).sort()

  const reserved = useMemo((): Record<string, number[]> => {
    if (!costsData || !queue) return {}
    const out: Record<string, number[]> = {}
    for (const city of cityNames) {
      const res = [0, 0, 0, 0, 0]
      const items = queue.queues?.[city] || []
      const cityBldgs = data.empireData[city] || {}
      const cityCosts = costsData.cities?.[city] || {}
      for (const item of items) {
        const curLv = parseInt(String(cityBldgs[item.building] || '0')) || 0
        const bCosts = cityCosts[item.building]
        if (!bCosts) continue
        for (let lv = curLv + 1; lv <= item.targetLevel; lv++) {
          const c = bCosts.costs?.[String(lv)]
          if (!c) continue
          COST_KEYS.forEach((k, i) => { res[i] += c[k] || 0 })
        }
      }
      out[city] = res
    }
    return out
  }, [costsData, queue, cityNames, data.empireData])

  const hasAnyReserved = Object.values(reserved).some(r => r.some(v => v > 0))
  if (!hasAnyReserved) return null

  const totalAvail  = COST_KEYS.map((_, i) => cityNames.reduce((s, c) => s + (data.resourcesData[c]?.[MATERIALS[i].en as keyof typeof data.resourcesData[string]] as number || 0), 0))
  const totalReserved = COST_KEYS.map((_, i) => cityNames.reduce((s, c) => s + (reserved[c]?.[i] || 0), 0))

  return (
    <Card className="mt-4">
      <CardHeader icon="fa-table-cells" title={t('matrix_title')} />
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-slate-800 text-white uppercase tracking-wide">
              <th className="px-4 py-2.5 text-left font-semibold whitespace-nowrap">{t('col_city')}</th>
              {MATERIALS.map(m => (
                <th key={m.en} className="px-3 py-2.5 text-center font-semibold whitespace-nowrap">
                  <i className={`fa-solid ${m.icon} ${m.color} mr-1`} /> {m[lang]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {cityNames.map((city, ri) => {
              const cityRes = data.resourcesData[city]
              const res = reserved[city] || [0, 0, 0, 0, 0]
              return (
                <tr key={city} className={`border-b border-slate-100 hover:bg-slate-50 ${ri % 2 ? 'bg-slate-50/40' : ''}`}>
                  <td className="px-4 py-2 font-semibold text-slate-700 whitespace-nowrap">{city}</td>
                  {MATERIALS.map((m, i) => {
                    const avail = (cityRes?.[m.en as keyof typeof cityRes] as number) || 0
                    const need  = res[i] || 0
                    if (need === 0) return <td key={m.en} className="px-3 py-2 text-center text-slate-300">—</td>
                    const balance = avail - need
                    const pct = need > 0 ? Math.min(100, Math.round((avail / need) * 100)) : 100
                    const cls = balance >= 0
                      ? 'bg-emerald-50 text-emerald-700'
                      : pct >= 50 ? 'bg-yellow-50 text-yellow-700' : 'bg-red-50 text-red-700'
                    return (
                      <td key={m.en} className={`px-3 py-2 text-center font-mono ${cls}`}>
                        <div>{balance >= 0 ? `+${fmt(balance)}` : fmt(balance)}</div>
                        <div className="text-[10px] opacity-60">{pct}%</div>
                      </td>
                    )
                  })}
                </tr>
              )
            })}
            <tr className="border-t-2 border-slate-300 bg-slate-100 font-semibold">
              <td className="px-4 py-2 text-slate-600 whitespace-nowrap">{t('matrix_total')}</td>
              {MATERIALS.map((m, i) => {
                const balance = totalAvail[i] - totalReserved[i]
                if (totalReserved[i] === 0) return <td key={m.en} className="px-3 py-2 text-center text-slate-300">—</td>
                const cls = balance >= 0 ? 'text-emerald-700' : 'text-red-700'
                return (
                  <td key={m.en} className={`px-3 py-2 text-center font-mono ${cls}`}>
                    {balance >= 0 ? `+${fmt(balance)}` : fmt(balance)}
                  </td>
                )
              })}
            </tr>
          </tbody>
        </table>
      </div>
    </Card>
  )
}
