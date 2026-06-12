import { useState, useEffect, useCallback } from 'react'
import { useT, useLang } from '../i18n'
import { fmt, fmtDuration, fmtArrival } from '../utils'
import { useLiveClock } from '../hooks/useLiveClock'
import { MATERIALS } from '../constants'
import { Card, CardHeader } from './ui/Card'
import { PageHeader } from './ui/PageHeader'
import type { OwnCity } from '../types'

interface PendingTransport {
  id:             string
  originCityId:   string
  originCityName: string
  destCityId:     string
  destCityName:   string
  resources:      number[]
  ships:          number
  shipType:       string
  dispatchAfter:  number
}

interface ConsolidateSettings {
  enabled:       boolean
  destCityId:    string
  destCityName:  string
  intervalHours: number
  minSendTotal:  number
  lastRun?:      number
  lastSent?:     Record<string, number>
}

function selectClass() {
  return 'w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 text-slate-700'
}

export function TransportTab() {
  const t    = useT()
  const lang = useLang() as 'pt' | 'en'
  const now  = useLiveClock()

  // Data
  const [ownCities,     setOwnCities]     = useState<OwnCity[]>([])
  const [resourcesData, setResourcesData] = useState<Record<string, any>>({})
  const [pending,       setPending]       = useState<PendingTransport[]>([])
  const [consolidate,   setConsolidate]   = useState<ConsolidateSettings | null>(null)

  // Manual form state
  const [originName,   setOriginName]   = useState('')
  const [destName,     setDestName]     = useState('')
  const [amounts,      setAmounts]      = useState<number[]>([0, 0, 0, 0, 0])
  const [ships,        setShips]        = useState(0)
  const [shipType,     setShipType]     = useState<'transporters' | 'freighters'>('transporters')
  const [scheduleType, setScheduleType] = useState<'now' | 'delay' | 'at'>('now')
  const [delayMinutes, setDelayMinutes] = useState(30)
  const [atTime,       setAtTime]       = useState('')
  const [submitting,   setSubmitting]   = useState(false)
  const [feedback,     setFeedback]     = useState<{ ok: boolean; msg: string } | null>(null)

  // Consolidation form state
  const [consSaving,   setConsSaving]   = useState(false)
  const [consFeedback, setConsFeedback] = useState<string | null>(null)

  const loadAll = useCallback(() => {
    fetch('/api/own-cities').then(r => r.json()).then((data: OwnCity[]) => {
      setOwnCities(data)
      if (data.length > 0) {
        setOriginName(prev => prev || data[0].name)
        setDestName(prev => prev || (data[1]?.name ?? data[0].name))
      }
    }).catch(() => {})

    fetch('/api/data').then(r => r.json()).then((data: any) => {
      setResourcesData(data?.resourcesData ?? {})
    }).catch(() => {})

    fetch('/api/transport/queue').then(r => r.json()).then((data: any) => {
      setPending(data?.pending ?? [])
    }).catch(() => {})

    fetch('/api/transport/consolidate').then(r => r.json()).then(setConsolidate).catch(() => {})
  }, [])

  useEffect(() => { loadAll() }, [])

  const origin = ownCities.find(c => c.name === originName)
  const dest   = ownCities.find(c => c.name === destName)
  const originRes = resourcesData[originName] ?? {}

  function computeDispatchAfter(): number {
    const base = Math.floor(Date.now() / 1000)
    if (scheduleType === 'delay') return base + delayMinutes * 60
    if (scheduleType === 'at' && atTime) {
      const [h, m] = atTime.split(':').map(Number)
      const d = new Date()
      d.setHours(h, m, 0, 0)
      if (d.getTime() / 1000 <= base) d.setDate(d.getDate() + 1)
      return Math.floor(d.getTime() / 1000)
    }
    return base + 10
  }

  async function handleSubmit() {
    if (!origin || !dest) return
    if (amounts.every(a => a <= 0)) {
      setFeedback({ ok: false, msg: t('transport_select_resource') })
      return
    }
    setSubmitting(true)
    setFeedback(null)
    try {
      const res = await fetch('/api/transport/queue/add', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          originCityId:   String(origin.cityId),
          originCityName: origin.name,
          destCityId:     String(dest.cityId),
          destCityName:   dest.name,
          islandId:       String(dest.islandId ?? ''),
          resources:      amounts,
          ships,
          shipType,
          scheduleType,
          delayMinutes,
          dispatchAfter:  computeDispatchAfter(),
        }),
      })
      const json = await res.json()
      if (!res.ok) throw new Error(json.error ?? 'Erro desconhecido')
      setFeedback({ ok: true, msg: `${origin.name} → ${dest.name}` })
      setAmounts([0, 0, 0, 0, 0])
      loadAll()
    } catch (e: any) {
      setFeedback({ ok: false, msg: e.message })
    } finally {
      setSubmitting(false)
    }
  }

  async function handleCancel(id: string) {
    await fetch('/api/transport/queue/cancel', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ id }),
    }).catch(() => {})
    loadAll()
  }

  async function handleSaveConsolidate() {
    if (!consolidate) return
    setConsSaving(true)
    setConsFeedback(null)
    try {
      const res = await fetch('/api/transport/consolidate', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(consolidate),
      })
      const json = await res.json()
      if (!res.ok) throw new Error(json.error ?? 'Erro')
      setConsFeedback(t('transport_saved'))
    } catch (e: any) {
      setConsFeedback(e.message)
    } finally {
      setConsSaving(false)
    }
  }

  return (
    <div>
      <PageHeader icon="fa-boxes-stacked" title={t('transport_title')} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">

        {/* ── Manual scheduled transport ──────────────────────────────────── */}
        <Card>
          <CardHeader icon="fa-ship" title={t('transport_manual')} />
          <div className="p-4 space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
                  {t('transport_origin')}
                </label>
                <select className={selectClass()} value={originName} onChange={e => setOriginName(e.target.value)}>
                  {ownCities.map(c => <option key={c.cityId} value={c.name}>{c.name}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
                  {t('transport_dest')}
                </label>
                <select className={selectClass()} value={destName} onChange={e => setDestName(e.target.value)}>
                  {ownCities.filter(c => c.name !== originName).map(c => (
                    <option key={c.cityId} value={c.name}>{c.name}</option>
                  ))}
                </select>
              </div>
            </div>

            {/* Resources */}
            <div>
              <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
                {t('transport_resources')}
              </label>
              <div className="space-y-2">
                {MATERIALS.map((m, i) => {
                  const avail = Number(originRes[m.en] ?? 0)
                  return (
                    <div key={m.en} className="flex items-center gap-3">
                      <span className={`w-5 text-center ${m.color}`}><i className={`fa-solid ${m.icon}`} /></span>
                      <span className="flex-1 text-sm text-slate-700">{m[lang]}</span>
                      <span className="text-xs text-slate-400 w-20 text-right">{fmt(avail)}</span>
                      <input
                        type="number"
                        min={0}
                        value={amounts[i]}
                        onChange={e => {
                          const v = Math.max(0, Number(e.target.value))
                          setAmounts(prev => prev.map((p, j) => j === i ? v : p))
                        }}
                        className="w-28 border border-slate-200 rounded-lg px-2 py-1 text-sm text-right focus:outline-none focus:ring-2 focus:ring-indigo-400"
                      />
                      <button
                        className="text-xs text-indigo-500 hover:text-indigo-700 font-medium"
                        onClick={() => setAmounts(prev => prev.map((p, j) => j === i ? avail : p))}
                      >
                        Max
                      </button>
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Ships + type */}
            <div className="flex items-end gap-3">
              <div>
                <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
                  {t('transport_ships')}
                </label>
                <input
                  type="number"
                  min={0}
                  value={ships}
                  onChange={e => setShips(Math.max(0, Number(e.target.value)))}
                  className="w-24 border border-slate-200 rounded-lg px-2 py-1.5 text-sm text-right focus:outline-none focus:ring-2 focus:ring-indigo-400"
                />
              </div>
              <div className="flex gap-2 flex-1">
                {(['transporters', 'freighters'] as const).map(st => (
                  <button
                    key={st}
                    onClick={() => setShipType(st)}
                    className={`flex-1 py-2 rounded-lg text-xs font-medium border transition-colors ${
                      shipType === st
                        ? 'bg-indigo-600 text-white border-indigo-600'
                        : 'bg-white text-slate-600 border-slate-200 hover:border-indigo-300'
                    }`}
                  >
                    <i className={`fa-solid ${st === 'transporters' ? 'fa-sailboat' : 'fa-ferry'} mr-1`} />
                    {t(st === 'transporters' ? 'transport_ship_type_transporters' : 'transport_ship_type_freighters')}
                  </button>
                ))}
              </div>
            </div>

            {/* Schedule */}
            <div>
              <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
                {t('dispatch_schedule')}
              </label>
              <div className="flex gap-2 mb-2">
                {(['now', 'delay', 'at'] as const).map(st => (
                  <button
                    key={st}
                    onClick={() => setScheduleType(st)}
                    className={`flex-1 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                      scheduleType === st
                        ? 'bg-indigo-600 text-white border-indigo-600'
                        : 'bg-white text-slate-600 border-slate-200 hover:border-indigo-300'
                    }`}
                  >
                    {t(st === 'now' ? 'dispatch_sched_now' : st === 'delay' ? 'dispatch_sched_delay' : 'dispatch_sched_at')}
                  </button>
                ))}
              </div>
              {scheduleType === 'delay' && (
                <div className="flex items-center gap-2">
                  <input
                    type="number" min={1} max={480} value={delayMinutes}
                    onChange={e => setDelayMinutes(Math.max(1, Number(e.target.value)))}
                    className="w-24 border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                  />
                  <span className="text-sm text-slate-500">{t('dispatch_minutes')}</span>
                </div>
              )}
              {scheduleType === 'at' && (
                <input
                  type="time" value={atTime} onChange={e => setAtTime(e.target.value)}
                  className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                />
              )}
            </div>

            {feedback && (
              <div className={`rounded-lg px-3 py-2 text-sm ${feedback.ok ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-600'}`}>
                <i className={`fa-solid ${feedback.ok ? 'fa-circle-check' : 'fa-circle-xmark'} mr-1.5`} />
                {feedback.msg}
              </div>
            )}

            <button
              className="inline-flex items-center gap-1.5 px-3 py-2.5 rounded-lg text-sm font-medium bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40 w-full justify-center"
              onClick={handleSubmit}
              disabled={submitting || !origin || !dest || ships <= 0}
            >
              {submitting
                ? <><i className="fa-solid fa-spinner fa-spin" /> {t('dispatch_sending')}</>
                : <><i className="fa-solid fa-paper-plane" /> {t('transport_send')}</>}
            </button>
          </div>
        </Card>

        {/* ── Consolidation ───────────────────────────────────────────────── */}
        <Card>
          <CardHeader icon="fa-warehouse" title={t('transport_consolidate')} />
          <div className="p-4 space-y-4">
            <p className="text-xs text-slate-500">{t('transport_consolidate_hint')}</p>
            {consolidate && (
              <>
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => setConsolidate({ ...consolidate, enabled: !consolidate.enabled })}
                    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                      consolidate.enabled ? 'bg-indigo-600' : 'bg-slate-300'
                    }`}
                  >
                    <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                      consolidate.enabled ? 'translate-x-6' : 'translate-x-1'
                    }`} />
                  </button>
                  <span className="text-sm text-slate-700">{t('transport_enabled')}</span>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
                    {t('transport_dest')}
                  </label>
                  <select
                    className={selectClass()}
                    value={consolidate.destCityId}
                    onChange={e => {
                      const c = ownCities.find(x => String(x.cityId) === e.target.value)
                      setConsolidate({ ...consolidate, destCityId: e.target.value, destCityName: c?.name ?? '' })
                    }}
                  >
                    <option value="">—</option>
                    {ownCities.map(c => (
                      <option key={c.cityId} value={String(c.cityId)}>{c.name}</option>
                    ))}
                  </select>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
                      {t('transport_interval')}
                    </label>
                    <input
                      type="number" min={1} max={48}
                      value={consolidate.intervalHours}
                      onChange={e => setConsolidate({ ...consolidate, intervalHours: Math.max(1, Number(e.target.value)) })}
                      className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
                      {t('transport_min_send')}
                    </label>
                    <input
                      type="number" min={0} step={500}
                      value={consolidate.minSendTotal}
                      onChange={e => setConsolidate({ ...consolidate, minSendTotal: Math.max(0, Number(e.target.value)) })}
                      className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                    />
                  </div>
                </div>

                <div className="text-xs text-slate-400">
                  {t('transport_last_run')}: {consolidate.lastRun ? fmtArrival(consolidate.lastRun, lang) : t('transport_never')}
                  {consolidate.lastSent && Object.keys(consolidate.lastSent).length > 0 && (
                    <span className="ml-2">
                      ({Object.entries(consolidate.lastSent).map(([c, v]) => `${c}: ${fmt(v)}`).join(', ')})
                    </span>
                  )}
                </div>

                {consFeedback && (
                  <div className="rounded-lg px-3 py-2 text-sm bg-emerald-50 text-emerald-700">{consFeedback}</div>
                )}

                <button
                  className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40"
                  onClick={handleSaveConsolidate}
                  disabled={consSaving}
                >
                  <i className={`fa-solid ${consSaving ? 'fa-spinner fa-spin' : 'fa-floppy-disk'}`} />
                  {t('transport_save')}
                </button>
              </>
            )}
          </div>
        </Card>
      </div>

      {/* ── Pending transports ─────────────────────────────────────────────── */}
      {pending.length > 0 && (
        <Card>
          <CardHeader icon="fa-clock" title={`${t('transport_pending')} (${pending.length})`} />
          <div className="divide-y divide-slate-100">
            {pending.map(item => {
              const secsLeft   = Math.max(0, item.dispatchAfter - now)
              const dispatching = item.dispatchAfter <= now
              return (
                <div key={item.id} className="px-5 py-3 flex items-center gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-slate-700">
                      <span className="text-indigo-600">{item.originCityName}</span>
                      <span className="mx-1.5 text-slate-400">→</span>
                      <span className="text-emerald-600">{item.destCityName}</span>
                    </div>
                    <div className="text-xs text-slate-400 mt-0.5 flex items-center gap-2 flex-wrap">
                      {MATERIALS.map((m, i) => (item.resources?.[i] ?? 0) > 0 && (
                        <span key={m.en}>
                          <i className={`fa-solid ${m.icon} mr-1 ${m.color}`} />{fmt(item.resources[i])}
                        </span>
                      ))}
                      <span>·</span>
                      <span>
                        <i className={`fa-solid ${item.shipType === 'freighters' ? 'fa-ferry' : 'fa-sailboat'} mr-1`} />
                        {fmt(item.ships)} {t(item.shipType === 'freighters' ? 'transport_ship_type_freighters' : 'transport_ship_type_transporters')}
                      </span>
                    </div>
                  </div>
                  <div className="text-right flex-shrink-0">
                    {dispatching ? (
                      <div className="text-xs text-emerald-600 font-semibold">
                        <i className="fa-solid fa-check mr-1" />{t('dispatch_dispatching')}
                      </div>
                    ) : (
                      <>
                        <div className="text-sm font-mono font-semibold text-slate-700">{fmtDuration(secsLeft)}</div>
                        <div className="text-xs text-slate-400">{fmtArrival(item.dispatchAfter, lang)}</div>
                      </>
                    )}
                  </div>
                  <button
                    onClick={() => handleCancel(item.id)}
                    className="inline-flex items-center px-3 py-1.5 rounded-lg text-sm font-medium bg-red-500 text-white hover:bg-red-600"
                    title={t('cancel')}
                  >
                    <i className="fa-solid fa-xmark" />
                  </button>
                </div>
              )
            })}
          </div>
        </Card>
      )}
    </div>
  )
}
