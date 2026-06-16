import { useState, useEffect, useCallback } from 'react'
import { useT, useLang } from '../i18n'
import { fmt, fmtDuration, fmtArrival } from '../utils'
import { useLiveClock } from '../hooks/useLiveClock'
import { MATERIALS } from '../constants'
import { Card, CardHeader } from './ui/Card'
import { PageHeader } from './ui/PageHeader'
import type { OwnCity, WorldScanPlayer } from '../types'

interface FarmTarget {
  target_city_id:   string
  target_city_name: string
  target_player:    string
  enabled:          boolean
  interval_hours:   number
  min_loot:         number
  max_enemy_ships:  number
  respy_every:      number
  state:            string
  next_run_at:      number
  last_loot:        number
  total_raids:      number
  total_loot:       number
}

interface LootStat {
  from_player: string
  raids:       number
  last_ts:     number
  wood:        number
  wine:        number
  marble:      number
  crystal:     number
  sulfur:      number
  total:       number
}

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
  state?:     string
}

interface AttackLogEntry {
  id:            number
  ts:            number
  origin_city:   string
  target_city:   string
  target_player: string
  mission_type:  string
  target_type:   string
  source:        string
  units:         Record<string, number>
  transporters:  number
  success:       boolean
  error:         string | null
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

// Mirror of the bot's _calc_travel_secs model: same island ≈ 10 min; otherwise
// 1200s × distance for warships/transports, troops on transports ≈ 2/3 of that.
function travelSecs(ox: number, oy: number, tx: number, ty: number, mission: 'army' | 'fleet'): number {
  if (ox === tx && oy === ty) return 600
  const dist = Math.sqrt((ox - tx) ** 2 + (oy - ty) ** 2)
  const fleet = Math.ceil(1200 * dist)
  return mission === 'army' ? Math.round(fleet * 2 / 3) : fleet
}

// ── Main component ────────────────────────────────────────────────────────────

export function DispatchTab() {
  const t    = useT()
  const lang = useLang()
  const now  = useLiveClock()

  // Data
  const [ownCities,      setOwnCities]      = useState<OwnCity[]>([])
  const [military,       setMilitary]       = useState<MilitaryData | null>(null)
  const [scanPlayers,    setScanPlayers]    = useState<WorldScanPlayer[]>([])
  const [pending,        setPending]        = useState<PendingAttack[]>([])
  const [availableShips, setAvailableShips] = useState<number | null>(null)
  const [attackLog,      setAttackLog]      = useState<AttackLogEntry[]>([])
  const [lootStats,      setLootStats]      = useState<LootStat[]>([])
  const [farmTargets,    setFarmTargets]    = useState<FarmTarget[]>([])
  const [farmArmy,       setFarmArmy]       = useState<Record<string, number>>({})
  const [farmSpyAgents,  setFarmSpyAgents]  = useState(1)
  const [farmArmySaved,  setFarmArmySaved]  = useState(false)
  const [logFilter,      setLogFilter]      = useState('')
  const [totalShips,     setTotalShips]     = useState<number | null>(null)
  const [shipCapacity,   setShipCapacity]   = useState<number | null>(null)
  const [lootByCity,     setLootByCity]     = useState<Record<string, number>>({})

  // Form state
  const [originCityName, setOriginCityName] = useState('')
  const [missionType,    setMissionType]    = useState<'army' | 'fleet'>('army')
  const [unitQty,        setUnitQty]        = useState<Record<string, number>>({})
  const [targetMode,     setTargetMode]     = useState<'own' | 'enemy'>('enemy')
  const [targetSearch,   setTargetSearch]   = useState('')
  const [target,         setTarget]         = useState<DispatchTarget | null>(null)
  const [scheduleType,   setScheduleType]   = useState<'now' | 'delay' | 'at' | 'arrive'>('now')
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

    fetch('/api/data').then(r => r.json()).then((data: any) => {
      setAvailableShips(data?.statusSummary?.ships?.available ?? null)
      setTotalShips(data?.statusSummary?.ships?.total ?? null)
      setShipCapacity(data?.statusSummary?.shipCapacity ?? null)
    }).catch(() => {})

    // Known warehouse loot per target city, from the latest DONE spy report (F3)
    fetch('/api/espionage/missions').then(r => r.json()).then((d: any) => {
      const map: Record<string, { ts: number; loot: number }> = {}
      for (const m of d?.missions ?? []) {
        if (m.state !== 'DONE' || !m.targetCityId || !m.result?.resources) continue
        const loot = Object.values(m.result.resources as Record<string, number>).reduce((a, b) => a + b, 0)
        const ts = m.result.reportedAt ?? m.executedAt ?? 0
        const cur = map[String(m.targetCityId)]
        if (!cur || ts >= cur.ts) map[String(m.targetCityId)] = { ts, loot }
      }
      setLootByCity(Object.fromEntries(Object.entries(map).map(([k, v]) => [k, v.loot])))
    }).catch(() => {})

    fetch('/api/attack-log?limit=100').then(r => r.json()).then((data: any) => {
      if (Array.isArray(data)) setAttackLog(data)
    }).catch(() => {})

    fetch('/api/loot-stats').then(r => r.json()).then((data: any) => {
      if (Array.isArray(data)) setLootStats(data)
    }).catch(() => {})

    fetch('/api/farm').then(r => r.json()).then((data: any) => {
      if (Array.isArray(data)) setFarmTargets(data)
    }).catch(() => {})

    fetch('/api/farm/army').then(r => r.json()).then((data: any) => {
      setFarmArmy(data?.army ?? {})
      setFarmSpyAgents(data?.spyAgents ?? 1)
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
          islandId:   String(c.islandId ?? ''),
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
        state:      p.state,
      }))
  })()

  // ── Derived: travel time + arrival estimate (F2) ───────────────────────────

  const travel = originCity && target
    ? travelSecs(originCity.x, originCity.y, target.islandX, target.islandY, missionType)
    : null

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
    if (scheduleType === 'arrive' && atTime) {
      // Work backwards: launch = desired arrival − travel time
      const [h, m] = atTime.split(':').map(Number)
      const d = new Date()
      d.setHours(h, m, 0, 0)
      let arrival = Math.floor(d.getTime() / 1000)
      const tv = travel ?? 0
      while (arrival - tv <= base) arrival += 86400
      return arrival - tv
    }
    return base + 10
  }

  const previewDispatchAt = computeDispatchAfter()
  const previewArrivalAt  = travel !== null ? previewDispatchAt + travel : null

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
    if (target.type === 'own' && !target.islandId) {
      setFeedback({ ok: false, msg: 'Cidade própria ainda sem islandId — força uma actualização do império (Home → Atualizar) e tenta de novo.' })
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
          targetType:       target.type,
          units,
          transporters:     missionType === 'army' ? transporters : 0,
          // 'arrive' is a client-side mode: the launch time is pre-computed, so the
          // backend sees a plain 'at' schedule
          scheduleType:     scheduleType === 'arrive' ? 'at' : scheduleType,
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

  // ── Farm (F4) ────────────────────────────────────────────────────────────────

  async function handleAddFarm() {
    if (!target || target.type !== 'enemy') return
    await fetch('/api/farm/add', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        targetCityId:   target.cityId,
        targetCityName: target.cityName,
        targetPlayer:   target.playerName,
        islandId:       target.islandId,
        islandX:        target.islandX,
        islandY:        target.islandY,
      }),
    }).catch(() => {})
    setFeedback({ ok: true, msg: `${t('farm_add')}: ${target.cityName}` })
    loadAll()
  }

  async function farmUpdate(targetCityId: string, body: Record<string, unknown>) {
    await fetch('/api/farm/update', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ targetCityId, ...body }),
    }).catch(() => {})
    loadAll()
  }

  async function farmRemove(targetCityId: string) {
    await fetch('/api/farm/remove', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ targetCityId }),
    }).catch(() => {})
    loadAll()
  }

  async function saveFarmArmy(next: Record<string, number>, spyAgents = farmSpyAgents) {
    setFarmArmy(next)
    setFarmArmySaved(false)
    await fetch('/api/farm/army', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ army: next, spyAgents }),
    }).catch(() => {})
    setFarmArmySaved(true)
  }

  const farmIds = new Set(farmTargets.map(f => f.target_city_id))

  // Union of troop unit types across all cities (for the farm loadout editor)
  const troopTypes: Record<string, string> = {}
  Object.values(military?.byCityName ?? {}).forEach(c => {
    Object.entries(c.troops ?? {}).forEach(([uid, u]) => { troopTypes[uid] = u.name })
  })

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
                  {availableShips !== null && (
                    <span className="ml-2 normal-case font-normal text-slate-400">
                      ({t('attack_available')}: {fmt(availableShips)}
                      {totalShips !== null && ` / ${fmt(totalShips)} ${t('dispatch_ships_total')}`})
                    </span>
                  )}
                </label>
                <div className="flex items-center gap-3">
                  {/* Scheduling cap is the FLEET TOTAL, not currently-free ships: busy
                      ships may be back by dispatch time; the bot caps to the live free
                      count at launch. */}
                  <input
                    type="number"
                    min={0}
                    max={totalShips ?? undefined}
                    value={transporters}
                    onChange={e => setTransporters(Math.max(0, Math.min(totalShips ?? Infinity, Number(e.target.value))))}
                    className="w-24 border border-slate-200 rounded-lg px-2 py-1 text-sm text-right focus:outline-none focus:ring-2 focus:ring-indigo-400"
                  />
                  {(totalShips ?? availableShips) !== null && (
                    <button
                      className="text-xs text-indigo-500 hover:text-indigo-700 font-medium"
                      onClick={() => setTransporters((totalShips ?? availableShips)!)}
                    >
                      Max
                    </button>
                  )}
                  <span className="text-sm text-slate-500">{t('dispatch_transporters_hint')}</span>
                </div>
                {availableShips !== null && transporters > availableShips && (
                  <div className="mt-1.5 flex items-center gap-1.5 text-xs text-yellow-700 bg-yellow-50 border border-yellow-200 rounded-lg px-2 py-1.5">
                    <i className="fa-solid fa-circle-info" />
                    {t('dispatch_ships_over')}
                  </div>
                )}
                {/* F3: capacity vs the target's known warehouse loot */}
                {(() => {
                  if (!target || target.type !== 'enemy' || !shipCapacity) return null
                  const loot = lootByCity[target.cityId] ?? 0
                  if (loot <= 0) return null
                  const capacity = transporters * shipCapacity
                  const needed = Math.ceil(loot / shipCapacity)
                  const ok = capacity >= loot
                  return (
                    <div className={`mt-1.5 flex items-center gap-2 text-xs rounded-lg px-2 py-1.5 ${ok ? 'text-emerald-700 bg-emerald-50 border border-emerald-200' : 'text-orange-700 bg-orange-50 border border-orange-200'}`}>
                      <i className={`fa-solid ${ok ? 'fa-circle-check' : 'fa-triangle-exclamation'}`} />
                      <span className="flex-1">
                        {t('dispatch_cap_loot', { cap: fmt(capacity), loot: fmt(loot) })}
                        {!ok && ` · ${t('dispatch_cap_need', { n: String(needed) })}`}
                      </span>
                      {!ok && (
                        <button
                          className="text-indigo-600 hover:text-indigo-800 font-medium whitespace-nowrap"
                          onClick={() => setTransporters(Math.min(totalShips ?? needed, needed))}
                        >
                          {t('dispatch_cap_fill')}
                        </button>
                      )}
                    </div>
                  )
                })()}
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
                <div>
                  <div className={`flex items-center gap-2 border rounded-lg px-3 py-2 ${target.state === 'inactive' ? 'border-yellow-300 bg-yellow-50' : 'border-indigo-300 bg-indigo-50'}`}>
                    <div className="flex-1">
                      <div className={`text-sm font-semibold ${target.state === 'inactive' ? 'text-yellow-800' : 'text-indigo-800'}`}>{target.cityName}</div>
                      <div className={`text-xs ${target.state === 'inactive' ? 'text-yellow-600' : 'text-indigo-500'}`}>{target.playerName} · ({target.islandX}:{target.islandY})</div>
                    </div>
                    {target.type === 'enemy' && target.cityId && !farmIds.has(target.cityId) && (
                      <button
                        onClick={handleAddFarm}
                        title={t('farm_add')}
                        className="text-xs text-amber-600 hover:text-amber-700 font-medium whitespace-nowrap"
                      >
                        <i className="fa-solid fa-seedling mr-1" />{t('farm_add')}
                      </button>
                    )}
                    <button onClick={() => { setTarget(null); setTargetSearch('') }} className="text-slate-400 hover:text-red-500">
                      <i className="fa-solid fa-xmark" />
                    </button>
                  </div>
                  {target.state === 'inactive' && (
                    <div className="mt-1.5 flex items-center gap-1.5 text-xs text-yellow-700 bg-yellow-50 border border-yellow-200 rounded-lg px-2 py-1.5">
                      <i className="fa-solid fa-circle-info" />
                      Jogador inactivo — atacável; confirma que ainda tem recursos antes de enviar
                    </div>
                  )}
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
                {(['now', 'delay', 'at', 'arrive'] as const).map(st => (
                  <button
                    key={st}
                    onClick={() => setScheduleType(st)}
                    className={`flex-1 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                      scheduleType === st
                        ? 'bg-indigo-600 text-white border-indigo-600'
                        : 'bg-white text-slate-600 border-slate-200 hover:border-indigo-300'
                    }`}
                  >
                    {t(st === 'now' ? 'dispatch_sched_now'
                       : st === 'delay' ? 'dispatch_sched_delay'
                       : st === 'at' ? 'dispatch_sched_at'
                       : 'dispatch_sched_arrive')}
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
              {(scheduleType === 'at' || scheduleType === 'arrive') && (
                <input
                  type="time"
                  value={atTime}
                  onChange={e => setAtTime(e.target.value)}
                  className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                />
              )}
            </div>

            {/* ETA preview (F2) — travel model mirrors the bot's _calc_travel_secs */}
            {target && travel !== null && (
              <div className="rounded-lg bg-slate-50 border border-slate-200 px-3 py-2 text-xs text-slate-600 flex items-center gap-x-4 gap-y-1 flex-wrap">
                <span>
                  <i className="fa-solid fa-route mr-1 text-slate-400" />
                  {t('dispatch_travel')}: ~{fmtDuration(travel)}
                </span>
                {scheduleType === 'arrive' && (
                  <span>
                    <i className="fa-solid fa-paper-plane mr-1 text-slate-400" />
                    {t('dispatch_launch_at')} {fmtArrival(previewDispatchAt, lang)}
                  </span>
                )}
                {previewArrivalAt !== null && (
                  <span>
                    <i className="fa-solid fa-flag-checkered mr-1 text-slate-400" />
                    {t('dispatch_arrival')}: ~{fmtArrival(previewArrivalAt, lang)}
                  </span>
                )}
              </div>
            )}

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

      {/* ── Dispatch history (attack_log) ─────────────────────────────────── */}
      <Card>
        <CardHeader icon="fa-clock-rotate-left" title={t('dispatch_history')} />
        <div className="px-5 py-3 border-b border-slate-100">
          <input
            type="text"
            placeholder={t('dispatch_history_filter')}
            value={logFilter}
            onChange={e => setLogFilter(e.target.value)}
            className="w-full sm:w-72 border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
          />
        </div>
        {(() => {
          const q = logFilter.trim().toLowerCase()
          const rows = attackLog.filter(e =>
            !q ||
            e.target_city?.toLowerCase().includes(q) ||
            e.target_player?.toLowerCase().includes(q)
          )
          if (rows.length === 0) {
            return <p className="px-5 py-4 text-sm text-slate-400 italic">{t('dispatch_history_empty')}</p>
          }
          return (
            <div className="divide-y divide-slate-100 max-h-96 overflow-y-auto">
              {rows.map(e => {
                const unitsTotal = Object.values(e.units || {}).reduce((a, b) => a + b, 0)
                return (
                  <div key={e.id} className="px-5 py-2.5 flex items-center gap-3">
                    <i className={`fa-solid ${e.success ? 'fa-circle-check text-emerald-500' : 'fa-circle-xmark text-red-500'}`} />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-slate-700 truncate">
                        <span className="text-indigo-600 font-medium">{e.origin_city}</span>
                        <span className="mx-1.5 text-slate-400">→</span>
                        <span className={e.target_type === 'own' ? 'text-indigo-600' : 'text-red-600'}>
                          {e.target_city || '?'}
                        </span>
                        {e.target_player && (
                          <span className="text-slate-400 text-xs ml-1">({e.target_player})</span>
                        )}
                      </div>
                      <div className="text-xs text-slate-400 mt-0.5 flex items-center gap-2 flex-wrap">
                        <span>
                          <i className={`fa-solid ${e.mission_type === 'fleet' ? 'fa-anchor' : 'fa-person-military-rifle'} mr-1`} />
                          {fmt(unitsTotal)} {t('dispatch_units_label')}
                        </span>
                        {e.mission_type !== 'fleet' && e.transporters > 0 && (
                          <span><i className="fa-solid fa-ship mr-1" />{fmt(e.transporters)}</span>
                        )}
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                          e.source === 'auto' ? 'bg-purple-100 text-purple-600' : 'bg-slate-100 text-slate-500'
                        }`}>
                          {t(e.source === 'auto' ? 'dispatch_source_auto' : 'dispatch_source_manual')}
                        </span>
                        {!e.success && e.error && (
                          <span className="text-red-400 truncate max-w-xs" title={e.error}>{e.error}</span>
                        )}
                      </div>
                    </div>
                    <div className="text-xs text-slate-400 flex-shrink-0">
                      {fmtArrival(e.ts, lang)}
                    </div>
                  </div>
                )
              })}
            </div>
          )
        })()}
      </Card>

      {/* ── Loot by target (F1.b) ─────────────────────────────────────────── */}
      <Card className="mt-4">
        <CardHeader icon="fa-coins" title={t('loot_title')} />
        <p className="px-5 pt-2 text-xs text-slate-400">{t('loot_note')}</p>
        {lootStats.length === 0 ? (
          <p className="px-5 py-4 text-sm text-slate-400 italic">{t('loot_empty')}</p>
        ) : (
          <div className="divide-y divide-slate-100">
            {lootStats.map(s => (
              <div key={s.from_player || '?'} className="px-5 py-2.5 flex items-center gap-3">
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold text-slate-700 truncate">
                    {s.from_player || '?'}
                    <span className="text-slate-400 text-xs ml-2 font-normal">
                      {s.raids} {t('loot_raids')} · {t('loot_last')} {fmtArrival(s.last_ts, lang)}
                    </span>
                  </div>
                  <div className="text-xs text-slate-400 mt-0.5 flex items-center gap-2 flex-wrap">
                    {MATERIALS.map((m, i) => {
                      const v = [s.wood, s.wine, s.marble, s.crystal, s.sulfur][i]
                      return v > 0 && (
                        <span key={m.en}><i className={`fa-solid ${m.icon} mr-1 ${m.color}`} />{fmt(v)}</span>
                      )
                    })}
                  </div>
                </div>
                <div className="text-right flex-shrink-0">
                  <div className="text-sm font-mono font-semibold text-amber-600">{fmt(s.total)}</div>
                  <div className="text-[10px] text-slate-400 uppercase">{t('loot_total')}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* ── Target farm (F4) ──────────────────────────────────────────────── */}
      <Card className="mt-4">
        <CardHeader icon="fa-seedling" title={t('farm_title')} />
        <p className="px-5 pt-2 text-xs text-slate-400">{t('farm_note')}</p>

        {/* Minimal army loadout — sent per raid instead of all troops */}
        <div className="px-5 py-3 border-b border-slate-100">
          <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
              {t('farm_army')}
            </span>
            <span className="flex items-center gap-1.5 text-xs text-slate-500">
              {t('farm_spies')}
              <input
                type="number" min={1} max={99} value={farmSpyAgents}
                onChange={e => setFarmSpyAgents(Math.max(1, Number(e.target.value)))}
                onBlur={() => saveFarmArmy(farmArmy, farmSpyAgents)}
                className="w-14 border border-slate-200 rounded px-1.5 py-0.5 text-xs text-right"
              />
              {farmArmySaved && <span className="text-emerald-600 ml-1">{t('transport_saved')}</span>}
            </span>
          </div>
          {Object.keys(troopTypes).length === 0 ? (
            <p className="text-xs text-slate-400 italic">{t('dispatch_no_units')}</p>
          ) : (
            <>
              <p className="text-xs text-slate-400 mb-2">{t('farm_army_hint')}</p>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {Object.entries(troopTypes).map(([uid, uname]) => (
                  <div key={uid} className="flex items-center gap-2">
                    <span className="flex-1 text-xs text-slate-600 truncate" title={uname}>{uname}</span>
                    <input
                      type="number" min={0}
                      value={farmArmy[uid] ?? 0}
                      onChange={e => {
                        const v = Math.max(0, Number(e.target.value))
                        setFarmArmy(prev => ({ ...prev, [uid]: v }))
                        setFarmArmySaved(false)
                      }}
                      className="w-16 border border-slate-200 rounded px-2 py-1 text-xs text-right focus:outline-none focus:ring-2 focus:ring-indigo-400"
                    />
                  </div>
                ))}
              </div>
              <button
                onClick={() => saveFarmArmy(Object.fromEntries(Object.entries(farmArmy).filter(([, v]) => v > 0)))}
                className="mt-2 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-indigo-600 text-white hover:bg-indigo-700"
              >
                <i className="fa-solid fa-floppy-disk" /> {t('transport_save')}
              </button>
            </>
          )}
        </div>

        {farmTargets.length === 0 ? (
          <p className="px-5 py-4 text-sm text-slate-400 italic">{t('farm_empty')}</p>
        ) : (
          <div className="divide-y divide-slate-100">
            {farmTargets.map(f => {
              const stateColor = f.state === 'ATTACKING' ? 'bg-red-100 text-red-600'
                : f.state === 'SPYING' ? 'bg-blue-100 text-blue-600' : 'bg-slate-100 text-slate-500'
              return (
                <div key={f.target_city_id} className="px-5 py-3 flex items-center gap-3 flex-wrap">
                  <button
                    onClick={() => farmUpdate(f.target_city_id, { enabled: !f.enabled })}
                    className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors shrink-0 ${f.enabled ? 'bg-indigo-600' : 'bg-slate-300'}`}
                    title={t('transport_enabled')}
                  >
                    <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${f.enabled ? 'translate-x-5' : 'translate-x-1'}`} />
                  </button>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-slate-700 truncate">
                      {f.target_city_name}
                      <span className="text-slate-400 text-xs ml-1 font-normal">({f.target_player})</span>
                      <span className={`ml-2 px-1.5 py-0.5 rounded text-[10px] font-medium ${stateColor}`}>
                        {t(`farm_state_${f.state}`)}
                      </span>
                    </div>
                    <div className="text-xs text-slate-400 mt-0.5 flex items-center gap-1.5 flex-wrap">
                      <span>{t('farm_minloot')} {fmt(f.min_loot)}</span>
                      <span>·</span>
                      <span className="flex items-center gap-1">
                        {t('farm_respy')}
                        <input
                          type="number" min={1} max={50} value={f.respy_every}
                          onChange={e => farmUpdate(f.target_city_id, { respyEvery: Math.max(1, Number(e.target.value)) })}
                          className="w-12 border border-slate-200 rounded px-1 py-0.5 text-xs text-right"
                        />
                      </span>
                      <span>·</span>
                      <span>{t('farm_raids')}: {f.total_raids}</span>
                      {f.last_loot > 0 && <><span>·</span><span>{t('farm_lastloot')} {fmt(f.last_loot)}</span></>}
                    </div>
                  </div>
                  <button onClick={() => farmUpdate(f.target_city_id, { runNow: true })}
                          className="text-xs text-indigo-500 hover:text-indigo-700 font-medium" title={t('farm_runnow')}>
                    <i className="fa-solid fa-bolt mr-1" />{t('farm_runnow')}
                  </button>
                  <button onClick={() => farmRemove(f.target_city_id)}
                          className="text-xs text-red-400 hover:text-red-600 font-medium" title={t('farm_remove')}>
                    <i className="fa-solid fa-trash" />
                  </button>
                </div>
              )
            })}
          </div>
        )}
      </Card>
    </div>
  )
}
