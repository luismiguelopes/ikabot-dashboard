import { useState, useEffect, useCallback } from 'react'
import { useT, useLang } from '../i18n'
import { fmt, fmtDuration, fmtArrival } from '../utils'
import { useLiveClock } from '../hooks/useLiveClock'
import { Card, CardHeader } from './ui/Card'
import { PageHeader } from './ui/PageHeader'
import type { OwnCity, WorldScanPlayer } from '../types'

// ── Types ────────────────────────────────────────────────────────────────────

interface MilitaryUnit {
  name: string
  amount: number
}

interface CityMilitary {
  cityId: string
  troops: Record<string, MilitaryUnit>
  fleet:  Record<string, MilitaryUnit>
}

interface MilitaryData {
  lastUpdated: number
  byCityName:  Record<string, CityMilitary>
}

interface DispatchTarget {
  type:       'own' | 'enemy'
  cityId:     string
  cityName:   string
  playerName: string
  islandId:   string
  islandX:    number
  islandY:    number
}

interface PendingAttack {
  id:               string
  originCityId:     string
  originCityName:   string
  targetCityId:     string
  targetCityName:   string
  targetPlayerName: string
  islandX:          number
  islandY:          number
  units:            Record<string, number>
  missionType:      string
  addedAt:          number
  dispatchAfter:    number
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function selectClass(extra = '') {
  return `w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 text-slate-700 ${extra}`
}

function btnClass(variant: 'primary' | 'danger' | 'ghost', extra = '') {
  const base = 'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors '
  if (variant === 'primary') return base + 'bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40 ' + extra
  if (variant === 'danger')  return base + 'bg-red-500 text-white hover:bg-red-600 ' + extra
  return base + 'text-slate-500 hover:bg-slate-100 ' + extra
}

// ── Main component ────────────────────────────────────────────────────────────

export function DispatchTab() {
  const t    = useT()
  const lang = useLang()
  const now  = useLiveClock()

  // Data
  const [ownCities,  setOwnCities]  = useState<OwnCity[]>([])
  const [military,   setMilitary]   = useState<MilitaryData | null>(null)
  const [scanPlayers, setScanPlayers] = useState<WorldScanPlayer[]>([])
  const [pending,    setPending]    = useState<PendingAttack[]>([])

  // Form state
  const [originCityName, setOriginCityName] = useState('')
  const [missionType,    setMissionType]    = useState<'army' | 'fleet'>('army')
  const [unitQty,        setUnitQty]        = useState<Record<string, number>>({})
  const [targetMode,     setTargetMode]     = useState<'own' | 'enemy'>('enemy')
  const [targetSearch,   setTargetSearch]   = useState('')
  const [target,         setTarget]         = useState<DispatchTarget | null>(null)
  const [scheduleType,   setScheduleType]   = useState<'now' | 'delay' | 'at'>('now')
  const [delayMinutes,   setDelayMinutes]   = useState(30)
  const [atTime,         setAtTime]         = useState('')
  const [transporters,   setTransporters]   = useState(0)
  const [submitting,     setSubmitting]     = useState(false)
  const [feedback,       setFeedback]       = useState<{ ok: boolean; msg: string } | null>(null)

  // ── Fetch data ──────────────────────────────────────────────────────────────

  const loadAll = useCallback(() => {
    fetch('/api/own-cities').then(r => r.json()).then((data: OwnCity[]) => {
      setOwnCities(data)
      if (data.length > 0 && !originCityName) setOriginCityName(data[0].name)
    }).catch(() => {})

    fetch('/api/military').then(r => r.json()).then(setMilitary).catch(() => {})

    fetch('/api/world-scan').then(r => r.json()).then((data: any) => {
      setScanPlayers(data?.players ?? [])
    }).catch(() => {})

    fetch('/api/espionage/attack-queue').then(r => r.json()).then((data: any) => {
      setPending(data?.pending ?? [])
    }).catch(() => {})
  }, [originCityName])

  useEffect(() => { loadAll() }, [])

  // ── Derived: units for selected city + mission type ─────────────────────────

  const cityMilitary = military?.byCityName?.[originCityName]
  const unitPool: Record<string, MilitaryUnit> =
    missionType === 'fleet'
      ? (cityMilitary?.fleet ?? {})
      : (cityMilitary?.troops ?? {})

  const availableUnits = Object.entries(unitPool).filter(([, u]) => u.amount > 0)

  // Reset unit quantities and transporters when city or mission type changes
  useEffect(() => { setUnitQty({}); setTransporters(0) }, [originCityName, missionType])

  // ── Derived: origin city metadata ──────────────────────────────────────────

  const originCity = ownCities.find(c => c.name === originCityName)

  // ── Filtered search results ─────────────────────────────────────────────────

  const searchResults: DispatchTarget[] = (() => {
    const q = targetSearch.trim().toLowerCase()
    if (!q || q.length < 2) return []
    if (targetMode === 'own') {
      return ownCities
        .filter(c => c.name !== originCityName && c.name.toLowerCase().includes(q))
        .slice(0, 8)
        .map(c => ({
          type:       'own' as const,
          cityId:     String(c.cityId),
          cityName:   c.name,
          playerName: 'Própria',
          islandId:   '',
          islandX:    c.x,
          islandY:    c.y,
        }))
    }
    return scanPlayers
      .filter(p =>
        p.cityName?.toLowerCase().includes(q) ||
        p.playerName?.toLowerCase().includes(q)
      )
      .slice(0, 10)
      .map(p => ({
        type:       'enemy' as const,
        cityId:     p.cityId ?? '',
        cityName:   p.cityName,
        playerName: p.playerName,
        islandId:   p.islandId ?? '',
        islandX:    p.islandX,
        islandY:    p.islandY,
      }))
  })()

  // ── Schedule helpers ────────────────────────────────────────────────────────

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

  // ── Submit ──────────────────────────────────────────────────────────────────

  async function handleSubmit() {
    if (!originCity || !target) return
    const units = Object.fromEntries(
      Object.entries(unitQty).filter(([, v]) => v > 0)
    )
    if (Object.keys(units).length === 0) {
      setFeedback({ ok: false, msg: 'Selecciona pelo menos uma unidade.' })
      return
    }

    setSubmitting(true)
    setFeedback(null)

    try {
      const res = await fetch('/api/dispatch/combat', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          originCityId:     String(originCity.cityId),
          originCityName:   originCity.name,
          targetCityId:     target.cityId,
          targetCityName:   target.cityName,
          targetPlayerName: target.playerName,
          islandId:         target.islandId,
          islandX:          target.islandX,
          islandY:          target.islandY,
          missionType,
          units,
          transporters:     missionType === 'army' ? transporters : 0,
          scheduleType,
          delayMinutes,
          dispatchAfter:    computeDispatchAfter(),
        }),
      })
      const json = await res.json()
      if (!res.ok) throw new Error(json.error ?? 'Erro desconhecido')
      setFeedback({ ok: true, msg: `Agendado → ${target.cityName} (${target.playerName})` })
      setUnitQty({})
      setTarget(null)
      setTargetSearch('')
      loadAll()
    } catch (e: any) {
      setFeedback({ ok: false, msg: e.message })
    } finally {
      setSubmitting(false)
    }
  }

  // ── Cancel pending ──────────────────────────────────────────────────────────

  async function handleCancel(id: string) {
    await fetch('/api/espionage/attack-queue/cancel', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ id }),
    })
    loadAll()
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div>
      <PageHeader icon="fa-crosshairs" title={t('dispatch_title')} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">

        {/* ── Left panel: assets ─────────────────────────────────────────── */}
        <Card>
          <CardHeader icon="fa-shield-halved" title={t('dispatch_assets')} />
          <div className="p-4 space-y-4">

            {/* Origin city */}
            <div>
              <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
                {t('dispatch_origin')}
              </label>
              <select
                className={selectClass()}
                value={originCityName}
                onChange={e => setOriginCityName(e.target.value)}
              >
                {ownCities.map(c => (
                  <option key={c.cityId} value={c.name}>{c.name}</option>
                ))}
              </select>
            </div>

            {/* Mission type */}
            <div>
              <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
                {t('dispatch_mission')}
              </label>
              <div className="flex gap-2">
                {(['army', 'fleet'] as const).map(mt => (
                  <button
                    key={mt}
                    onClick={() => setMissionType(mt)}
                    className={`flex-1 py-2 rounded-lg text-sm font-medium border transition-colors ${
                      missionType === mt
                        ? 'bg-indigo-600 text-white border-indigo-600'
                        : 'bg-white text-slate-600 border-slate-200 hover:border-indigo-300'
                    }`}
                  >
                    <i className={`fa-solid ${mt === 'army' ? 'fa-person-military-rifle' : 'fa-anchor'} mr-1.5`} />
                    {t(mt === 'army' ? 'dispatch_pillage' : 'dispatch_naval')}
                  </button>
                ))}
              </div>
            </div>

            {/* Units */}
            <div>
              <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
                {t('dispatch_units')}
              </label>
              {availableUnits.length === 0 ? (
                <p className="text-slate-400 text-sm italic">
                  {military ? t('dispatch_no_units') : t('loading')}
                </p>
              ) : (
                <div className="space-y-2">
                  {availableUnits.map(([uid, unit]) => (
                    <div key={uid} className="flex items-center gap-3">
                      <span className="flex-1 text-sm text-slate-700">{unit.name}</span>
                      <span className="text-xs text-slate-400 w-16 text-right">
                        {t('attack_available')}: {fmt(unit.amount)}
                      </span>
                      <input
                        type="number"
                        min={0}
                        max={unit.amount}
                        value={unitQty[uid] ?? 0}
                        onChange={e => setUnitQty(prev => ({ ...prev, [uid]: Math.min(unit.amount, Math.max(0, Number(e.target.value))) }))}
                        className="w-24 border border-slate-200 rounded-lg px-2 py-1 text-sm text-right focus:outline-none focus:ring-2 focus:ring-indigo-400"
                      />
                      <button
                        className="text-xs text-indigo-500 hover:text-indigo-700 font-medium"
                        onClick={() => setUnitQty(prev => ({ ...prev, [uid]: unit.amount }))}
                      >
                        Max
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Transport ships — only for pillage */}
            {missionType === 'army' && (
              <div>
                <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
                  {t('dispatch_transporters')}
                </label>
                <div className="flex items-center gap-3">
                  <input
                    type="number"
                    min={0}
                    value={transporters}
                    onChange={e => setTransporters(Math.max(0, Number(e.target.value)))}
                    className="w-24 border border-slate-200 rounded-lg px-2 py-1 text-sm text-right focus:outline-none focus:ring-2 focus:ring-indigo-400"
                  />
                  <span className="text-sm text-slate-500">{t('dispatch_transporters_hint')}</span>
                </div>
              </div>
            )}
          </div>
        </Card>

        {/* ── Right panel: target + schedule ────────────────────────────── */}
        <Card>
          <CardHeader icon="fa-location-dot" title={t('dispatch_target_schedule')} />
          <div className="p-4 space-y-4">

            {/* Target mode */}
            <div>
              <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
                {t('dispatch_dest_type')}
              </label>
              <div className="flex gap-2">
                {(['enemy', 'own'] as const).map(mode => (
                  <button
                    key={mode}
                    onClick={() => { setTargetMode(mode); setTargetSearch(''); setTarget(null) }}
                    className={`flex-1 py-2 rounded-lg text-sm font-medium border transition-colors ${
                      targetMode === mode
                        ? 'bg-indigo-600 text-white border-indigo-600'
                        : 'bg-white text-slate-600 border-slate-200 hover:border-indigo-300'
                    }`}
                  >
                    <i className={`fa-solid ${mode === 'enemy' ? 'fa-skull' : 'fa-city'} mr-1.5`} />
                    {t(mode === 'enemy' ? 'dispatch_dest_enemy' : 'dispatch_dest_own')}
                  </button>
                ))}
              </div>
            </div>

            {/* Search */}
            <div className="relative">
              <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
                {t('dispatch_search')}
              </label>
              {target ? (
                <div className="flex items-center gap-2 border border-indigo-300 rounded-lg px-3 py-2 bg-indigo-50">
                  <div className="flex-1">
                    <div className="text-sm font-semibold text-indigo-800">{target.cityName}</div>
                    <div className="text-xs text-indigo-500">{target.playerName} · ({target.islandX}:{target.islandY})</div>
                  </div>
                  <button onClick={() => { setTarget(null); setTargetSearch('') }} className="text-slate-400 hover:text-red-500">
                    <i className="fa-solid fa-xmark" />
                  </button>
                </div>
              ) : (
                <>
                  <input
                    type="text"
                    placeholder={t(targetMode === 'enemy' ? 'dispatch_search_enemy_ph' : 'dispatch_search_own_ph')}
                    value={targetSearch}
                    onChange={e => setTargetSearch(e.target.value)}
                    className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                  />
                  {searchResults.length > 0 && (
                    <div className="absolute z-10 w-full mt-1 bg-white border border-slate-200 rounded-lg shadow-lg max-h-48 overflow-y-auto">
                      {searchResults.map((r, i) => (
                        <button
                          key={i}
                          className="w-full text-left px-3 py-2 text-sm hover:bg-indigo-50 border-b border-slate-100 last:border-0"
                          onClick={() => { setTarget(r); setTargetSearch('') }}
                        >
                          <span className="font-medium text-slate-800">{r.cityName}</span>
                          <span className="text-slate-400 ml-2 text-xs">{r.playerName} · ({r.islandX}:{r.islandY})</span>
                        </button>
                      ))}
                    </div>
                  )}
                </>
              )}
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
                    type="number"
                    min={1}
                    max={480}
                    value={delayMinutes}
                    onChange={e => setDelayMinutes(Math.max(1, Number(e.target.value)))}
                    className="w-24 border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                  />
                  <span className="text-sm text-slate-500">{t('dispatch_minutes')}</span>
                </div>
              )}
              {scheduleType === 'at' && (
                <input
                  type="time"
                  value={atTime}
                  onChange={e => setAtTime(e.target.value)}
                  className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                />
              )}
            </div>

            {/* Feedback */}
            {feedback && (
              <div className={`rounded-lg px-3 py-2 text-sm ${feedback.ok ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-600'}`}>
                <i className={`fa-solid ${feedback.ok ? 'fa-circle-check' : 'fa-circle-xmark'} mr-1.5`} />
                {feedback.msg}
              </div>
            )}

            {/* Submit */}
            <button
              className={btnClass('primary', 'w-full justify-center py-2.5')}
              onClick={handleSubmit}
              disabled={submitting || !target || !originCity}
            >
              {submitting
                ? <><i className="fa-solid fa-spinner fa-spin" /> {t('dispatch_sending')}</>
                : <><i className="fa-solid fa-paper-plane" /> {t('dispatch_send')}</>
              }
            </button>
          </div>
        </Card>
      </div>

      {/* ── Pending queue ─────────────────────────────────────────────────── */}
      {pending.length > 0 && (
        <Card>
          <CardHeader icon="fa-clock" title={`${t('dispatch_pending')} (${pending.length})`} />
          <div className="divide-y divide-slate-100">
            {pending.map(item => {
              const secsLeft  = Math.max(0, item.dispatchAfter - now)
              const dispatched = item.dispatchAfter <= now
              return (
                <div key={item.id} className="px-5 py-3 flex items-center gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-slate-700">
                      <span className="text-indigo-600">{item.originCityName}</span>
                      <span className="mx-1.5 text-slate-400">→</span>
                      <span className="text-red-600">{item.targetCityName}</span>
                      <span className="text-slate-400 text-xs ml-1">({item.targetPlayerName})</span>
                    </div>
                    <div className="text-xs text-slate-400 mt-0.5 flex items-center gap-2">
                      <span>
                        <i className={`fa-solid ${item.missionType === 'fleet' ? 'fa-anchor' : 'fa-person-military-rifle'} mr-1`} />
                        {t(item.missionType === 'fleet' ? 'dispatch_naval' : 'dispatch_pillage')}
                      </span>
                      <span>·</span>
                      <span>{Object.entries(item.units).map(([, v]) => fmt(v)).join(' + ')} unidades</span>
                      {item.missionType !== 'fleet' && (item as any).transporters > 0 && (
                        <>
                          <span>·</span>
                          <span><i className="fa-solid fa-ship mr-1" />{fmt((item as any).transporters)} {t('dispatch_transporters')}</span>
                        </>
                      )}
                    </div>
                  </div>
                  <div className="text-right flex-shrink-0">
                    {dispatched ? (
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
                    className={btnClass('danger')}
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
