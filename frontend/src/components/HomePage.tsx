import { useEffect, useState } from 'react'
import { useT, useLang } from '../i18n'
import { fmt, fmtDuration } from '../utils'
import { MATERIALS } from '../constants'
import { useLiveClock } from '../hooks/useLiveClock'
import { Card, CardHeader } from './ui/Card'
import { PageHeader } from './ui/PageHeader'
import { Th, Td } from './ui/TableCells'
import { StatBadge } from './ui/StatBadge'
import type { ApiData, AlertThresholds, BuildingQueue } from '../types'

export function HomePage({ data, thresholds }: { data: ApiData; thresholds: AlertThresholds }) {
  const t    = useT()
  const lang = useLang() as 'pt' | 'en'
  const now  = useLiveClock()
  const { statusSummary: s, empireData, resourcesData } = data
  const res = s.resources
  const totalAvail = res.available.reduce((a, b) => a + b, 0)
  const totalProd  = res.production.reduce((a, b) => a + b, 0)

  const [queue, setQueue] = useState<BuildingQueue | null>(null)
  useEffect(() => {
    fetch('/api/building-queue').then(r => r.json()).then(setQueue).catch(() => {})
  }, [data])

  const goldProd   = s.gold.production
  const goldRunway = goldProd < 0 ? s.gold.total / Math.abs(goldProd) / 24 : null

  // Active constructions from empireData (buildings marked with '+')
  const activeConstructions = Object.entries(empireData)
    .map(([city, buildings]) => {
      const busyEntry = Object.entries(buildings)
        .find(([k, v]) => k !== '_constructionEnds' && String(v).endsWith('+'))
      if (!busyEntry) return null
      const [building, levelStr] = busyEntry
      const fromLevel = parseInt(String(levelStr))
      const eta = (buildings._constructionEnds as number) || 0
      return { city, building, fromLevel, toLevel: fromLevel + 1, eta,
               timeLeft: Math.max(0, eta - now) }
    })
    .filter(Boolean)
    .sort((a, b) => a!.timeLeft - b!.timeLeft) as Array<{
      city: string; building: string; fromLevel: number; toLevel: number; eta: number; timeLeft: number
    }>

  // Cities queued but not yet in construction
  const queues     = queue?.queues      || {}
  const inProgress = queue?.inProgress  || {}
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
    </div>
  )
}
