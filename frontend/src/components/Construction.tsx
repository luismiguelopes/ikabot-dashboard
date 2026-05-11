import { useState, useEffect, useMemo } from 'react'
import { useT, useLang } from '../i18n'
import { fmt, fmtTs, fmtDuration } from '../utils'
import { useLiveClock } from '../hooks/useLiveClock'
import { MATERIALS, COST_KEYS } from '../constants'
import { Card } from './ui/Card'
import { PageHeader } from './ui/PageHeader'
import { ConstructionTemplate } from './ConstructionTemplate'
import type { ApiData, BuildingQueue, BuildingCostsData } from '../types'

interface BuildingInCity {
  name: string
  level: number
  isBusy: boolean
}

function QueueBudget({ queue, costsData, data }: { queue: BuildingQueue | null; costsData: BuildingCostsData | null; data: ApiData }) {
  const t    = useT()
  const lang = useLang() as 'pt' | 'en'

  const budget = useMemo(() => {
    if (!costsData) return null
    const total = [0, 0, 0, 0, 0]
    const empireData = data.empireData
    let itemCount = 0

    for (const [city, items] of Object.entries(queue?.queues || {})) {
      const cityBuildings = empireData[city] || {}
      const cityCosts = costsData.cities[city] || {}
      for (const item of items) {
        const currentLevel = parseInt(String(cityBuildings[item.building] || '0')) || 0
        const bCosts = cityCosts[item.building]
        if (!bCosts) continue
        for (let lv = currentLevel + 1; lv <= item.targetLevel; lv++) {
          const c = bCosts.costs[String(lv)]
          if (!c) continue
          total[0] += c.wood   || 0
          total[1] += c.wine   || 0
          total[2] += c.marble || 0
          total[3] += c.glass  || 0
          total[4] += c.sulfur || 0
        }
        itemCount++
      }
    }

    const available = [0, 0, 0, 0, 0]
    Object.values(data.resourcesData).forEach(city => {
      available[0] += city.Wood    || 0
      available[1] += city.Wine    || 0
      available[2] += city.Marble  || 0
      available[3] += city.Crystal || 0
      available[4] += city.Sulfur  || 0
    })

    const production = data.statusSummary.resources.production
    return { total, available, production, itemCount }
  }, [queue, costsData, data])

  const totalQueued = Object.values(queue?.queues || {}).reduce((s, v) => s + v.length, 0)

  if (totalQueued === 0) return null

  if (!costsData) return (
    <div className="flex items-center gap-2 text-xs text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-4 py-2.5">
      <i className="fa-solid fa-circle-info shrink-0" />
      {t('budget_no_costs')}
    </div>
  )

  if (!budget) return null

  const activeResources = MATERIALS.map((m, i) => ({
    ...m,
    needed:    budget.total[i],
    available: budget.available[i],
    missing:   Math.max(0, budget.total[i] - budget.available[i]),
    prodPerH:  budget.production[i],
  })).filter(r => r.needed > 0)

  const etaSecs = activeResources.reduce<number | null>((worst, r) => {
    if (r.missing <= 0) return worst
    if (r.prodPerH <= 0) return null
    const secs = (r.missing / r.prodPerH) * 3600
    if (worst === null) return secs
    return Math.max(worst, secs)
  }, 0)

  return (
    <Card>
      <div className="px-5 py-4">
        <div className="flex items-center justify-between mb-3">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide flex items-center gap-1.5">
            <i className="fa-solid fa-sack-dollar text-indigo-400" /> {t('budget_title')}
          </p>
          <span className="text-xs text-slate-400">{t('budget_total_items', { n: String(budget.itemCount) })}</span>
        </div>
        {activeResources.length === 0 ? (
          <p className="text-sm text-emerald-600 flex items-center gap-1.5">
            <i className="fa-solid fa-circle-check" /> {t('budget_ready')}
          </p>
        ) : (
          <div className="space-y-2">
            {activeResources.map(r => {
              const pct = Math.min(100, Math.round((r.available / r.needed) * 100))
              return (
                <div key={r.en} className="space-y-1">
                  <div className="flex items-center gap-2 text-xs">
                    <span className={`flex items-center gap-1 w-24 shrink-0 font-medium text-slate-600`}>
                      <i className={`fa-solid ${r.icon} ${r.color}`} /> {r[lang]}
                    </span>
                    <span className="text-slate-400 w-20 text-right font-mono">{fmt(r.available)}</span>
                    <span className="text-slate-300">/</span>
                    <span className="text-slate-600 font-mono w-20">{fmt(r.needed)}</span>
                    <span className={`ml-auto font-semibold font-mono w-20 text-right ${r.missing > 0 ? 'text-red-500' : 'text-emerald-600'}`}>
                      {r.missing > 0 ? `-${fmt(r.missing)}` : '✓'}
                    </span>
                  </div>
                  <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all ${pct >= 100 ? 'bg-emerald-400' : pct >= 60 ? 'bg-yellow-400' : 'bg-red-400'}`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              )
            })}
            {etaSecs !== null && etaSecs > 0 && (
              <p className="text-xs text-indigo-500 font-medium pt-1">
                <i className="fa-solid fa-hourglass-half mr-1" />
                {t('budget_eta')}: {fmtDuration(etaSecs)} {COST_KEYS.length > 0 ? `(${t('budget_available').toLowerCase()}: ${t('empire_prod_only').toLowerCase()})` : ''}
              </p>
            )}
            {etaSecs === 0 && (
              <p className="text-xs text-emerald-600 font-medium pt-1">
                <i className="fa-solid fa-circle-check mr-1" /> {t('budget_ready')}
              </p>
            )}
          </div>
        )}
      </div>
    </Card>
  )
}

export function BuildingQueueTab({ data }: { data: ApiData | null }) {
  const t    = useT()
  const lang = useLang()
  const now  = useLiveClock()
  const [activeTab, setActiveTab]       = useState<'queue' | 'template'>('queue')
  const [queue, setQueue]               = useState<BuildingQueue | null>(null)
  const [selCity, setSelCity]           = useState('')
  const [targetLevels, setTargetLevels] = useState<Record<string, number>>({})
  const [costsData, setCostsData]       = useState<BuildingCostsData | null>(null)
  const [refreshMsg, setRefreshMsg]     = useState('')

  const fetchQueue = () =>
    fetch('/api/building-queue').then(r => r.json()).then(setQueue).catch(() => {})

  useEffect(() => { fetchQueue() }, [])

  useEffect(() => {
    fetch('/api/building-costs')
      .then(r => r.ok ? r.json() : null)
      .then((d: BuildingCostsData | null) => { if (d && !(d as any).error) setCostsData(d) })
      .catch(() => {})
  }, [])

  const handleForceRefresh = () => {
    setRefreshMsg('sending')
    fetch('/api/building-costs/refresh', { method: 'POST' })
      .then(r => r.json())
      .then(() => setRefreshMsg('ok'))
      .catch(() => setRefreshMsg('error'))
  }

  const handleToggleEnabled = () => {
    const newEnabled = !(queue?.enabled ?? true)
    fetch('/api/building-queue/enabled', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: newEnabled }),
    }).then(fetchQueue)
  }

  const handleClearCity = (city: string) => {
    if (!confirm(t('queue_clear_confirm', { city }))) return
    fetch('/api/building-queue/clear', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cityName: city }),
    }).then(fetchQueue)
  }

  const handleClearAll = () => {
    if (!confirm(t('queue_clear_all_confirm'))) return
    fetch('/api/building-queue/clear', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    }).then(fetchQueue)
  }

  const empireData = data?.empireData || {}
  const cityNames  = Object.keys(empireData).sort()

  useEffect(() => {
    if (!selCity && cityNames.length > 0) setSelCity(cityNames[0])
  }, [cityNames.length])

  const buildingsInCity = useMemo((): BuildingInCity[] => {
    if (!selCity || !empireData[selCity]) return []
    return Object.entries(empireData[selCity])
      .filter(([k, v]) => k !== '_constructionEnds' && v !== '')
      .map(([k, v]) => ({ name: k, level: parseInt(String(v)) || 0, isBusy: String(v).endsWith('+') }))
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [selCity, empireData])

  useEffect(() => {
    const defaults: Record<string, number> = {}
    buildingsInCity.forEach(b => { defaults[b.name] = b.level + 1 })
    setTargetLevels(defaults)
  }, [selCity])

  const queues          = queue?.queues          || {}
  const inProgress      = queue?.inProgress      || {}
  const transportErrors = queue?.transportErrors || {}

  const cityQueue      = queues[selCity] || []
  const cityInProgress = inProgress[selCity]
  const cityError      = transportErrors[selCity]
  const queuedSet      = new Set(cityQueue.map(i => i.building))

  const totalQueued = (city: string) =>
    (queues[city]?.length || 0) + (inProgress[city] ? 1 : 0)

  const handleAdd = (buildingName: string) => {
    const targetLevel = targetLevels[buildingName]
    if (!selCity || !targetLevel) return
    fetch('/api/building-queue/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cityName: selCity, buildingName, targetLevel }),
    }).then(fetchQueue)
  }

  const handleRemove = (idx: number) => {
    fetch('/api/building-queue/remove', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cityName: selCity, index: idx }),
    }).then(fetchQueue)
  }

  const handleReorder = (fromIndex: number, toIndex: number) => {
    fetch('/api/building-queue/reorder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cityName: selCity, fromIndex, toIndex }),
    }).then(fetchQueue)
  }

  if (!data) return (
    <div>
      <PageHeader icon="fa-list-check" title={t('queue_title')} />
      <p className="text-slate-500 text-sm mt-4">{t('queue_no_data')}</p>
    </div>
  )

  return (
    <div className="space-y-4">
      <PageHeader icon="fa-list-check" title={t('queue_title')} />

      {/* Status card */}
      <Card>
        <div className="px-5 py-4 flex flex-wrap items-center gap-4">
          <div className="flex-1 min-w-0 space-y-1">
            {data?.lastUpdated && (
              <p className="text-sm text-slate-600">
                <i className="fa-regular fa-clock mr-1.5 text-slate-400" />
                {t('queue_last_cycle', { ts: data.lastUpdated })}
              </p>
            )}
            <p className="text-xs text-slate-400">
              {costsData?.lastUpdated
                ? <><i className="fa-solid fa-cube mr-1" />{t('last_extraction', { ts: fmtTs(costsData.lastUpdated, lang) })}<span className="ml-2 text-slate-300">{t('updates_3d')}</span></>
                : <span className="italic">{t('costs_unavailable')}</span>
              }
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0 flex-wrap">
            {refreshMsg === 'sending' && <span className="text-xs text-slate-400">{t('sending_request')}</span>}
            {refreshMsg === 'ok'      && <span className="text-xs text-emerald-600 font-medium">{t('scheduled_ok')}</span>}
            {refreshMsg === 'error'   && <span className="text-xs text-red-500">{t('schedule_error')}</span>}
            <button
              onClick={handleToggleEnabled}
              title={(queue?.enabled ?? true) ? t('queue_toggle_disable') : t('queue_toggle_enable')}
              className={`flex items-center gap-1.5 px-3 py-2 text-sm font-medium rounded-lg border transition-colors ${
                (queue?.enabled ?? true)
                  ? 'bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100'
                  : 'bg-orange-50 text-orange-700 border-orange-200 hover:bg-orange-100'
              }`}
            >
              <i className={`fa-solid ${(queue?.enabled ?? true) ? 'fa-play' : 'fa-pause'} text-xs`} />
              {(queue?.enabled ?? true) ? t('queue_enabled') : t('queue_disabled')}
            </button>
            <button
              onClick={handleClearAll}
              title={t('queue_clear_all')}
              className="flex items-center gap-1.5 px-3 py-2 bg-red-50 hover:bg-red-100 text-red-600 border border-red-200 text-sm font-medium rounded-lg transition-colors"
            >
              <i className="fa-solid fa-trash-can text-xs" />
              {t('queue_clear_all')}
            </button>
            <button
              onClick={handleForceRefresh}
              className="flex items-center gap-2 px-3 py-2 bg-slate-700 hover:bg-slate-600 text-white text-sm font-medium rounded-lg transition-colors"
            >
              <i className="fa-solid fa-rotate" />
              {t('force_update')}
            </button>
          </div>
        </div>
      </Card>

      {/* Sub-tab pills */}
      <div className="flex gap-2">
        {(['queue', 'template'] as const).map(key => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={`flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg border transition-colors ${
              activeTab === key
                ? 'bg-indigo-600 text-white border-indigo-600 shadow'
                : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
            }`}
          >
            <i className={`fa-solid ${key === 'queue' ? 'fa-list-check' : 'fa-layer-group'}`} />
            {key === 'queue' ? t('queue_panel') : t('template_tab')}
          </button>
        ))}
      </div>

      {activeTab === 'template' && (
        <ConstructionTemplate data={data} queue={queue} costsData={costsData} />
      )}

      {activeTab === 'queue' && <>
      {/* Queue budget */}
      <QueueBudget queue={queue} costsData={costsData} data={data} />

      {/* City tab pills */}
      <div className="flex gap-2 flex-wrap">
        {cityNames.map(city => {
          const count    = totalQueued(city)
          const hasError = !!transportErrors[city]
          return (
            <div key={city} className="flex items-center gap-0.5">
              <button
                onClick={() => setSelCity(city)}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium border-y border-l transition-colors ${count > 0 ? 'rounded-l-lg' : 'rounded-lg border-r'} ${
                  selCity === city
                    ? 'bg-indigo-600 text-white border-indigo-600 shadow'
                    : hasError
                      ? 'bg-white text-slate-600 border-orange-300 hover:bg-orange-50'
                      : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
                }`}
              >
                {hasError && <i className="fa-solid fa-triangle-exclamation text-orange-400 text-xs" />}
                {city}
                {count > 0 && (
                  <span className={`text-xs rounded-full px-1.5 py-0.5 font-semibold ${
                    selCity === city ? 'bg-white text-indigo-600' : 'bg-indigo-100 text-indigo-700'
                  }`}>{count}</span>
                )}
              </button>
              {count > 0 && (
                <button
                  onClick={() => handleClearCity(city)}
                  title={t('queue_clear_city')}
                  className={`px-1.5 py-1.5 rounded-r-lg border transition-colors ${
                    selCity === city
                      ? 'bg-indigo-700 hover:bg-red-600 text-white border-indigo-600'
                      : 'bg-white text-red-400 border-slate-200 hover:bg-red-50 hover:text-red-600 hover:border-red-200'
                  }`}
                >
                  <i className="fa-solid fa-xmark text-xs" />
                </button>
              )}
            </div>
          )
        })}
      </div>

      {selCity && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">

          {/* Buildings list */}
          <Card>
            <div className="px-5 py-4">
              <h3 className="font-semibold text-slate-700 mb-3 flex items-center gap-2">
                <i className="fa-solid fa-landmark text-indigo-400" />
                {t('queue_buildings_panel')}
              </h3>
              <div className="space-y-1.5">
                {buildingsInCity.map(b => {
                  const inQueue  = queuedSet.has(b.name) || cityInProgress?.building === b.name
                  const targetLv = targetLevels[b.name] ?? (b.level + 1)
                  const invalid  = !targetLv || targetLv <= b.level
                  return (
                    <div
                      key={b.name}
                      className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${
                        inQueue
                          ? 'bg-indigo-50 border border-indigo-100'
                          : 'bg-slate-50 hover:bg-slate-100 border border-transparent'
                      }`}
                    >
                      <div className="flex-1 min-w-0">
                        <span className="font-medium text-slate-700 text-sm truncate">{b.name}</span>
                        {b.isBusy && <span className="ml-1.5 text-xs text-blue-500 font-semibold">↑</span>}
                      </div>
                      <span className="text-xs font-mono text-slate-400 shrink-0">lv {b.level}</span>
                      <span className="text-slate-300 shrink-0">→</span>
                      <input
                        type="number"
                        min={b.level + 1}
                        value={targetLv}
                        onChange={e => setTargetLevels(prev => ({ ...prev, [b.name]: parseInt(e.target.value) || b.level + 1 }))}
                        disabled={inQueue}
                        className="w-14 border border-slate-200 rounded px-2 py-1 text-sm text-center focus:outline-none focus:ring-1 focus:ring-indigo-400 disabled:opacity-40 disabled:cursor-default"
                      />
                      {inQueue ? (
                        <span className="shrink-0 w-8 h-8 flex items-center justify-center rounded-lg bg-indigo-100 text-indigo-500">
                          <i className="fa-solid fa-check text-xs" />
                        </span>
                      ) : (
                        <button
                          onClick={() => handleAdd(b.name)}
                          disabled={invalid}
                          title={t('queue_add_btn')}
                          className="shrink-0 w-8 h-8 flex items-center justify-center rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-30 transition-colors"
                        >
                          <i className="fa-solid fa-plus text-xs" />
                        </button>
                      )}
                    </div>
                  )
                })}
                {buildingsInCity.length === 0 && (
                  <p className="text-sm text-slate-400 py-2">{t('queue_no_data')}</p>
                )}
              </div>
            </div>
          </Card>

          {/* Queue panel */}
          <Card>
            <div className="px-5 py-4">
              <h3 className="font-semibold text-slate-700 mb-3 flex items-center gap-2">
                <i className="fa-solid fa-list-check text-indigo-400" />
                {t('queue_panel')}
                {cityQueue.length > 0 && (
                  <span className="ml-1 text-xs bg-indigo-100 text-indigo-700 rounded-full px-2 py-0.5 font-semibold">
                    {cityQueue.length}
                  </span>
                )}
              </h3>

              {cityError && (
                <div className="mb-3 flex items-start gap-2 px-3 py-2.5 rounded-lg bg-orange-50 border border-orange-200 text-orange-700 text-xs">
                  <i className="fa-solid fa-triangle-exclamation mt-0.5 shrink-0" />
                  <div>
                    <span className="font-semibold">{t('transport_error')}: </span>
                    {t('transport_error_detail', {
                      resource: cityError.resource,
                      origin:   cityError.origin,
                      ts:       new Date(cityError.failedAt * 1000).toLocaleTimeString(),
                    })}
                  </div>
                </div>
              )}

              {cityQueue.length === 0 && !cityInProgress ? (
                <div className="py-6 flex flex-col items-center gap-2 text-slate-400">
                  <i className="fa-solid fa-inbox text-2xl" />
                  <p className="text-sm">{t('queue_empty')}</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {cityInProgress && (
                    <div className="flex items-center gap-3 px-3 py-3 rounded-lg bg-blue-50 border border-blue-200">
                      <span className="shrink-0 w-6 h-6 flex items-center justify-center rounded-full bg-blue-200 text-blue-700 text-xs font-bold">
                        <i className="fa-solid fa-hammer" />
                      </span>
                      <div className="flex-1 min-w-0">
                        <span className="font-semibold text-blue-800 text-sm">{cityInProgress.building}</span>
                        <span className="ml-2 text-xs text-blue-500">
                          {cityInProgress.fromLevel} → {cityInProgress.toLevel}
                        </span>
                      </div>
                      <span className="text-xs font-mono font-semibold text-blue-700 shrink-0">
                        {cityInProgress.eta
                          ? (cityInProgress.eta <= now ? t('home_constr_done') : fmtDuration(Math.max(0, cityInProgress.eta - now)))
                          : t('queue_status_building')}
                      </span>
                    </div>
                  )}

                  {cityQueue.map((item, idx) => {
                    const curLv = parseInt(String(empireData[selCity]?.[item.building] ?? '')) || 0
                    return (
                      <div
                        key={idx}
                        className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-slate-50 border border-slate-100 hover:bg-slate-100 transition-colors"
                      >
                        <span className="shrink-0 w-5 text-xs text-slate-400 text-right font-mono">{idx + 1}.</span>
                        <div className="flex-1 min-w-0">
                          <span className="font-medium text-slate-700 text-sm truncate">{item.building}</span>
                          <span className="ml-2 text-xs text-slate-400">
                            lv {curLv} → {item.targetLevel}
                          </span>
                        </div>
                        <div className="flex gap-0.5 shrink-0">
                          <button
                            onClick={() => handleReorder(idx, idx - 1)}
                            disabled={idx === 0}
                            className="p-1 rounded text-slate-400 hover:text-slate-600 hover:bg-slate-200 disabled:opacity-20 transition-colors"
                          ><i className="fa-solid fa-chevron-up text-xs" /></button>
                          <button
                            onClick={() => handleReorder(idx, idx + 1)}
                            disabled={idx === cityQueue.length - 1}
                            className="p-1 rounded text-slate-400 hover:text-slate-600 hover:bg-slate-200 disabled:opacity-20 transition-colors"
                          ><i className="fa-solid fa-chevron-down text-xs" /></button>
                          <button
                            onClick={() => handleRemove(idx)}
                            className="p-1 rounded text-red-400 hover:text-red-600 hover:bg-red-50 transition-colors"
                          ><i className="fa-solid fa-xmark text-xs" /></button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </Card>

        </div>
      )}
      </>}
    </div>
  )
}
