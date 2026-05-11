import { useState, useEffect, useMemo } from 'react'
import { useT } from '../i18n'
import { fmtDuration } from '../utils'
import { Card } from './ui/Card'
import { PageHeader } from './ui/PageHeader'
import { Td } from './ui/TableCells'
import { CitySelect } from './ui/CitySelect'
import { RefreshButton } from './ui/RefreshButton'
import { useEmpireRefresh } from '../hooks/useEmpireRefresh'
import type { ApiData, BuildingQueue } from '../types'

export function BuildingsPage({ data, onRefresh }: { data: ApiData; onRefresh?: () => void }) {
  const t = useT()
  const { trigger: forceUpdate, state: refreshState, status: refreshStatus } = useEmpireRefresh(onRefresh)
  const { empireData } = data
  const cities = Object.keys(empireData)
  const [filter, setFilter] = useState('all')
  const visible = filter === 'all' ? cities : cities.filter(c => c === filter)
  const [queue, setQueue] = useState<BuildingQueue | null>(null)

  const fetchQueue = () =>
    fetch('/api/building-queue').then(r => r.json()).then(setQueue).catch(() => {})

  useEffect(() => { fetchQueue() }, [])

  const buildingNames = useMemo(() => {
    const names = new Set<string>()
    cities.forEach(c => Object.keys(empireData[c]).forEach(k => { if (!k.startsWith('_')) names.add(k) }))
    return [...names]
  }, [empireData])

  const averages = useMemo(() => {
    const avgs: Record<string, number> = {}
    buildingNames.forEach(b => {
      const vals = cities.map(c => parseFloat(String(empireData[c][b]))).filter(v => !isNaN(v))
      avgs[b] = vals.length > 0 ? vals.reduce((a, v) => a + v, 0) / vals.length : 0
    })
    return avgs
  }, [empireData])

  const queuedSet = useMemo(() => {
    const s = new Set<string>()
    if (queue?.queues) {
      Object.entries(queue.queues).forEach(([city, items]) =>
        items.forEach(item => s.add(`${city}::${item.building}`))
      )
    }
    if (queue?.inProgress) {
      Object.entries(queue.inProgress).forEach(([city, ip]) =>
        s.add(`${city}::${ip.building}`)
      )
    }
    return s
  }, [queue])

  const handleQuickAdd = (cityName: string, buildingName: string, currentLevel: number) => {
    fetch('/api/building-queue/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cityName, buildingName, targetLevel: currentLevel + 1 }),
    }).then(fetchQueue)
  }

  const now = Math.floor(Date.now() / 1000)

  return (
    <div>
      <PageHeader icon="fa-landmark" title={t('buildings_title')}>
        <div className="flex items-center gap-2 flex-wrap">
          {onRefresh && <RefreshButton onRefresh={onRefresh} />}
          <button
            onClick={forceUpdate}
            disabled={refreshState === 'running'}
            className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg transition-colors ${
              refreshState === 'running' ? 'bg-indigo-100 text-indigo-600 border border-indigo-300 cursor-wait' :
              refreshState === 'done'    ? 'bg-emerald-50 text-emerald-700 border border-emerald-300' :
              'bg-indigo-600 hover:bg-indigo-700 text-white'
            }`}
          >
            <i className={`fa-solid ${refreshState === 'running' ? 'fa-spinner fa-spin' : refreshState === 'done' ? 'fa-check' : 'fa-arrows-rotate'}`} />
            {refreshState === 'running'
              ? t('empire_refresh_running', { progress: refreshStatus?.progress ?? 0, total: refreshStatus?.total ?? 0 })
              : refreshState === 'done' ? t('empire_refresh_done')
              : t('empire_refresh_btn')}
          </button>
          <CitySelect cities={cities} value={filter} onChange={setFilter} />
        </div>
      </PageHeader>

      <Card>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="bg-slate-800 text-white text-xs uppercase tracking-wide">
                <th className="px-5 py-3 font-semibold text-left whitespace-nowrap sticky left-0 z-20 bg-slate-800 border-r border-slate-700">
                  {t('col_city')}
                </th>
                {buildingNames.map(b => (
                  <th key={b} className="px-3 py-3 font-semibold text-center whitespace-nowrap text-xs">{b}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((city, i) => {
                const cityData = empireData[city]
                const hasConstruction = Object.entries(cityData).some(([k, v]) => !k.startsWith('_') && String(v).includes('+'))
                const constrEnds = (cityData['_constructionEnds'] as number) || 0
                const constrLeft = constrEnds > now ? constrEnds - now : 0
                const rowBg = i % 2 === 0 ? 'bg-white' : 'bg-slate-50'
                return (
                  <tr key={city} className={`border-b border-slate-100 hover:bg-indigo-50 transition-colors group ${rowBg}`}>
                    <td className={`px-5 py-2.5 text-sm font-semibold whitespace-nowrap sticky left-0 z-10 border-r border-slate-200 ${rowBg} group-hover:bg-indigo-50 ${hasConstruction ? 'text-orange-500' : 'text-slate-700'}`}>
                      {hasConstruction && <i className="fa-solid fa-hammer mr-1.5 text-orange-400 text-xs" />}
                      {city}
                      {constrLeft > 0 && (
                        <div className="text-[10px] text-orange-400 font-normal mt-0.5">
                          {fmtDuration(constrLeft)}
                        </div>
                      )}
                    </td>
                    {buildingNames.map(b => {
                      const val = cityData[b]
                      const numVal = parseFloat(String(val))
                      const isUnderConstruction = String(val).includes('+')
                      const isBelowAvg = !isUnderConstruction && !isNaN(numVal) && numVal < averages[b]
                      const isQueued = !!val && !isUnderConstruction && queuedSet.has(`${city}::${b}`)
                      return (
                        <Td key={b} className={`text-center font-mono px-2
                          ${isUnderConstruction ? 'text-orange-500 font-semibold' : ''}
                          ${isBelowAvg ? 'text-red-500 font-bold' : ''}
                          ${!isUnderConstruction && !isBelowAvg ? 'text-slate-600' : ''}
                        `}>
                          {val ? (
                            <span className="inline-flex items-center justify-center gap-0.5">
                              <span>{val}</span>
                              {!isUnderConstruction && (
                                <button
                                  onClick={() => handleQuickAdd(city, b, parseInt(String(val)))}
                                  disabled={isQueued}
                                  title={isQueued ? 'Já na fila' : 'Adicionar à fila'}
                                  className={`opacity-0 group-hover:opacity-100 transition-opacity text-[10px] leading-none w-3.5 h-3.5 flex items-center justify-center rounded
                                    ${isQueued ? 'text-green-500 cursor-default' : 'text-slate-400 hover:text-indigo-500 cursor-pointer'}`}
                                >
                                  <i className={`fa-solid ${isQueued ? 'fa-check' : 'fa-plus'}`} />
                                </button>
                              )}
                            </span>
                          ) : '—'}
                        </Td>
                      )
                    })}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="flex gap-5 mt-4 text-xs text-slate-500">
        <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-red-500 inline-block" />{t('legend_below_avg')}</span>
        <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-orange-400 inline-block" />{t('legend_construction')}</span>
      </div>
    </div>
  )
}
