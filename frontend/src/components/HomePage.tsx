import { useT, useLang } from '../i18n'
import { fmt, fmtDuration } from '../utils'
import { MATERIALS } from '../constants'
import { Card, CardHeader } from './ui/Card'
import { PageHeader } from './ui/PageHeader'
import { Th, Td } from './ui/TableCells'
import { StatBadge } from './ui/StatBadge'
import type { ApiData } from '../types'

export function HomePage({ data }: { data: ApiData }) {
  const t = useT()
  const lang = useLang() as 'pt' | 'en'
  const { statusSummary: s, empireData, resourcesData } = data
  const res = s.resources
  const totalAvail = res.available.reduce((a, b) => a + b, 0)
  const totalProd  = res.production.reduce((a, b) => a + b, 0)
  const now = Math.floor(Date.now() / 1000)

  const goldProd = s.gold.production
  const goldRunway = goldProd < 0
    ? (s.gold.total / Math.abs(goldProd) / 24)
    : null

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
    .sort((a, b) => a!.timeLeft - b!.timeLeft) as Array<{ city: string; building: string; fromLevel: number; toLevel: number; eta: number; timeLeft: number }>

  const wineAtRisk = Object.entries(resourcesData)
    .filter(([, d]) => d.wineRunsOutIn !== -1 && d.wineRunsOutIn > 0)
    .map(([city, d]) => ({ city, seconds: d.wineRunsOutIn,
                            prod: d.wineProductionPerHour, cons: d.wineConsumptionPerHour }))
    .sort((a, b) => a.seconds - b.seconds)
    .slice(0, 3)

  const wineColor = (secs: number) =>
    secs < 2 * 3600  ? 'text-red-600 bg-red-50 border-red-200' :
    secs < 8 * 3600  ? 'text-orange-600 bg-orange-50 border-orange-200' :
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
                  <Th key={m.en}>
                    <i className={`fa-solid ${m.icon} mr-1 ${m.color}`} /> {m[lang]}
                  </Th>
                ))}
                <Th className="text-indigo-300">Total</Th>
              </tr>
            </thead>
            <tbody>
              {[
                { label: t('row_available'), values: res.available,  total: totalAvail },
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
        <Card>
          <CardHeader icon="fa-hammer" title={t('home_active_constr')} />
          {activeConstructions.length === 0 ? (
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
            </ul>
          )}
        </Card>

        <Card>
          <CardHeader icon="fa-wine-bottle" title={t('home_wine_risk')} />
          {wineAtRisk.length === 0 ? (
            <p className="px-5 pb-4 text-sm text-slate-400">{t('home_no_wine_risk')}</p>
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
