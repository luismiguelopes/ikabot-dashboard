import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { useT } from '../../i18n'
import { fmt } from '../../utils'
import { Card } from '../ui/Card'
import { Td } from '../ui/TableCells'
import { ConfirmModal } from '../ui/Modal'
import { pushToast } from '../ui/Toast'
import { apiAction } from '../../api'
import { SpyModal } from './SpyModal'
import { AttackModal } from './AttackModal'
import { FarmSettings } from '../dispatch/FarmSettings'
import type { WorldScanData, WorldScanPlayer, OwnCity } from '../../types'
import type { CitySpyCounts, FarmTarget, LootStat, SpyMission } from './types'

const NAVAL_KEYWORDS = ['navio', 'ship', 'steam giant', 'galley', 'trireme', 'balloon', 'ram', 'mortar', 'catapult', 'flamethrower']

function isNavalUnit(name: string): boolean {
  const n = name.toLowerCase()
  return NAVAL_KEYWORDS.some(k => n.includes(k))
}

// ── EnrichedPlayer ────────────────────────────────────────────────────────────

interface EnrichedPlayer extends WorldScanPlayer {
  mission: SpyMission | undefined
  totalResources: number | null
  hasTroops: boolean | null   // null = no garrison data; false = clear; true = has troops
  hasShips: boolean | null
  priority: number
  cKey: string  // cityId (or fallback) — mission/dispatched lookup, unique per city
  pKey: string  // `${playerId}_${islandX}_${islandY}` — mark/ignore key (per player+island)
}

// ── MissionStatePill ──────────────────────────────────────────────────────────

function MissionStatePill({ priority, mission }: {
  priority: number
  mission: SpyMission | undefined
}) {
  const t = useT()

  if (priority === 6) return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-100 text-emerald-700">
      <i className="fa-solid fa-check text-[9px]" /> {t('pipeline_ready')}
    </span>
  )
  if (priority === 5) return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-orange-100 text-orange-700">
      <i className="fa-solid fa-ship text-[9px]" /> {t('pipeline_has_ships')}
    </span>
  )
  if (priority === 4) return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-700">
      <i className="fa-solid fa-coins text-[9px]" /> {t('pipeline_low_resources')}
    </span>
  )
  if (priority === 3) return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-600">
      <i className="fa-solid fa-warehouse text-[9px]" /> {t('pipeline_warehouse_known')}
    </span>
  )
  if (priority === 2 && mission) {
    const subLabel = mission.state === 'TRAVELING' ? t('spy_traveling')
      : mission.state === 'WAITING_AT_CITY' ? t('spy_waiting')
      : mission.state === 'WAITING_FOR_GARRISON' ? t('spy_waiting_garrison')
      : mission.state === 'EXECUTING_GARRISON' ? t('spy_executing_garrison')
      : t('spy_executing')
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-indigo-100 text-indigo-700">
        <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse inline-block" /> {subLabel}
      </span>
    )
  }
  if (priority === 0) return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-600">
      <i className="fa-solid fa-xmark text-[9px]" /> {t('pipeline_failed')}
    </span>
  )
  // priority === 1: no mission data
  return <span className="text-slate-300 text-xs">—</span>
}

// ── InactivosTab ──────────────────────────────────────────────────────────────

interface InactivosTabProps {
  scanData: WorldScanData | null
  loading: boolean
  error: string | null
  onForceRefresh: () => void
  ownCities: OwnCity[]
  spyCounts: Record<string, CitySpyCounts>
  spyOriginCityId: string
}

const RES_LABELS: Record<string, string> = {
  wood: 'Madeira', wine: 'Vinho', marble: 'Mármore', glass: 'Cristal', sulfur: 'Enxofre',
}
const RES_KEYS = ['wood', 'wine', 'marble', 'glass', 'sulfur'] as const

const _ACTIVE_SPY_STATES = new Set([
  'TRAVELING', 'WAITING_AT_CITY', 'EXECUTING', 'EXECUTING_WAREHOUSE',
  'WAITING_FOR_GARRISON', 'EXECUTING_GARRISON',
])

export function InactivosTab({ scanData, loading, error, onForceRefresh, ownCities, spyCounts, spyOriginCityId }: InactivosTabProps) {
  const t = useT()
  const [expandedKey,    setExpandedKey]    = useState<string | null>(null)
  const [spyTarget,      setSpyTarget]      = useState<EnrichedPlayer | null>(null)
  const [attackTarget,   setAttackTarget]   = useState<EnrichedPlayer | null>(null)
  const [dispatchedKeys, setDispatchedKeys] = useState<Set<string>>(new Set())
  const [missions,       setMissions]       = useState<SpyMission[]>([])
  const [minLootTotal,   setMinLootTotal]   = useState(50000)
  const [ignoredKeys,    setIgnoredKeys]    = useState<Set<string>>(new Set())
  const [confirmModal,   setConfirmModal]   = useState<{ action: 'force-warehouse' | 'recall', player: EnrichedPlayer } | null>(null)

  useEffect(() => {
    if (!scanData?.players) return
    setIgnoredKeys(new Set(
      scanData.players
        .filter(p => p.mark === 'ignorar')
        .map(p => `${p.playerId}_${p.islandX}_${p.islandY}`)
    ))
  }, [scanData])

  useEffect(() => {
    const load = () => fetch('/api/espionage/missions').then(r => r.json())
      .then((d: { missions: SpyMission[] }) => { if (d.missions) setMissions(d.missions) }).catch(() => {})
    load()
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    fetch('/api/espionage/settings').then(r => r.json())
      .then(d => { if (d.minLootTotal != null) setMinLootTotal(d.minLootTotal) }).catch(() => {})
  }, [])

  // Farm membership + per-target loot brought — for the unified target row (Phase 3)
  const [farmIds,     setFarmIds]     = useState<Set<string>>(new Set())
  const [farmByCity,  setFarmByCity]  = useState<Record<string, FarmTarget>>({})
  const [lootByPlayer, setLootByPlayer] = useState<Record<string, LootStat>>({})
  const [showFarmSettings, setShowFarmSettings] = useState(false)
  const loadFarm = () => fetch('/api/farm').then(r => r.json())
    .then((d: FarmTarget[]) => {
      if (!Array.isArray(d)) return
      setFarmIds(new Set(d.map(f => String(f.target_city_id))))
      setFarmByCity(Object.fromEntries(d.map(f => [String(f.target_city_id), f])))
    }).catch(() => {})  // background poll — stays silent on failure
  useEffect(() => {
    loadFarm()
    const loadLoot = () => fetch('/api/loot-stats').then(r => r.json())
      .then((d: LootStat[]) => {
        if (Array.isArray(d)) setLootByPlayer(Object.fromEntries(d.map(s => [(s.from_player || '').toLowerCase(), s])))
      }).catch(() => {})
    loadLoot()
    const id = setInterval(() => { loadFarm(); loadLoot() }, 30000)
    return () => clearInterval(id)
  }, [])

  async function handleAddFarm(p: EnrichedPlayer, mode: 'farm' | 'loop' = 'farm') {
    if (!p.cityId) return
    const res = await apiAction('/api/farm/add', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        targetCityId: p.cityId, targetCityName: p.cityName, targetPlayer: p.playerName,
        islandId: p.islandId, islandX: p.islandX, islandY: p.islandY, mode,
      }),
    })
    if (res) {
      setFarmIds(prev => new Set([...prev, String(p.cityId)]))
      pushToast(`${t(mode === 'loop' ? 'loop_add' : 'farm_add')}: ${p.cityName}`, 'ok')
    }
    loadFarm()
  }

  async function farmAction(cityId: string, body: Record<string, unknown>, remove = false) {
    await apiAction(remove ? '/api/farm/remove' : '/api/farm/update', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ targetCityId: cityId, ...body }),
    })
    loadFarm()
  }

  const latestMissionByCityId = useMemo(() => {
    const map: Record<string, SpyMission> = {}
    for (const m of missions) {
      const key = m.targetCityId
      if (!key) continue
      if (!map[key] || m.dispatchedAt > map[key].dispatchedAt) map[key] = m
    }
    return map
  }, [missions])

  const handleForceWarehouse = useCallback((p: EnrichedPlayer) => {
    setConfirmModal({ action: 'force-warehouse', player: p })
  }, [])

  const handleRecallSpy = useCallback((p: EnrichedPlayer) => {
    setConfirmModal({ action: 'recall', player: p })
  }, [])

  const handleConfirmAction = useCallback(() => {
    if (!confirmModal) return
    const { action, player } = confirmModal
    setConfirmModal(null)
    const url = action === 'force-warehouse' ? '/api/espionage/force-warehouse' : '/api/espionage/recall-spy'
    apiAction(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cityId: player.cityId }),
    }).then(d => {
      if (d && d.ok)
        pushToast(action === 'force-warehouse' ? `Inspecção agendada — ${player.cityName}` : `Espião chamado de volta — ${player.cityName}`, 'ok')
    })
  }, [confirmModal])

  const handleIgnore = useCallback((p: EnrichedPlayer) => {
    const ignoreKey = p.cityId ? `${p.playerId}_${p.cityId}` : p.pKey
    setIgnoredKeys(prev => new Set([...prev, ignoreKey]))
    apiAction('/api/world-scan/mark', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ playerId: p.playerId, cityId: p.cityId, islandX: p.islandX, islandY: p.islandY, status: 'ignorar', note: 'Ignorado manualmente' }),
    })
  }, [])

  const ambiguousCityKeys = useMemo((): Set<string> => {
    if (!scanData?.players) return new Set()
    const counts: Record<string, number> = {}
    for (const p of scanData.players)
      counts[`${p.playerName}|${p.cityName}`] = (counts[`${p.playerName}|${p.cityName}`] || 0) + 1
    return new Set(Object.keys(counts).filter(k => counts[k] > 1))
  }, [scanData])

  // Farm queue position, mirroring farm_manager._queue_head and the Combat/Farm panel:
  // the one mid-cycle target leads, then enabled IDLE targets by loot/hour desc. Drained
  // (disabled) targets get no position. Lets the unified list show #1, #2… inline.
  const queuePos = useMemo((): Record<string, number> => {
    const DEFAULT_RT = 4 * 3600
    const roundTrip = (f: FarmTarget) => ((f.last_troop_journey ?? 0) > 0 ? (f.last_troop_journey as number) * 2 : DEFAULT_RT)
    const score = (f: FarmTarget) => (f.last_loot || 0) / Math.max(1, roundTrip(f))
    const order = Object.values(farmByCity)
      .filter(f => f.enabled)
      .sort((a, b) => {
        const aActive = a.state !== 'IDLE', bActive = b.state !== 'IDLE'
        if (aActive !== bActive) return aActive ? -1 : 1
        return score(b) - score(a)
      })
    const pos: Record<string, number> = {}
    order.forEach((f, i) => { pos[String(f.target_city_id)] = i + 1 })
    return pos
  }, [farmByCity])

  const players = useMemo((): EnrichedPlayer[] => {
    const enriched: EnrichedPlayer[] = []
    const seenCityIds = new Set<string>()

    // Turn a (real or synthesized) scan player into an enriched target row: attach its latest
    // spy mission, derive seen loot / garrison, and compute the pipeline priority.
    const enrichOne = (p: WorldScanPlayer): EnrichedPlayer => {
      const pKey = `${p.playerId}_${p.islandX}_${p.islandY}`
      const cKey = p.cityId || `${p.playerName}_${p.cityName}_${p.islandX}_${p.islandY}`
      const mission = p.cityId ? latestMissionByCityId[p.cityId] : undefined

      let totalResources: number | null = null
      let hasTroops: boolean | null = null
      let hasShips: boolean | null = null

      if (mission?.state === 'DONE' && mission.result) {
        const res = mission.result.resources
        if (res) totalResources = Object.values(res).reduce((s, v) => s + (v || 0), 0)
        if (mission.garrisonResult && !mission.garrisonResult.error) {
          hasTroops = false
          hasShips = false
          for (const [name, count] of Object.entries(mission.garrisonResult.troops || {})) {
            if ((count as number) > 0) {
              if (isNavalUnit(name)) hasShips = true
              else hasTroops = true
            }
          }
        }
      }

      let priority = 1
      if (mission) {
        if (mission.state === 'FAILED') priority = 0
        else if (_ACTIVE_SPY_STATES.has(mission.state)) priority = 2
        else if (mission.state === 'DONE') {
          const hasResources = !!(mission.result?.resources && Object.keys(mission.result.resources).length > 0)
          if (!mission.result || !hasResources) priority = 1
          else if (mission.garrisonResult && !mission.garrisonResult.error) {
            priority = (totalResources || 0) >= minLootTotal ? (hasShips ? 5 : 6) : 4
          } else {
            priority = 3
          }
        }
      }

      return { ...p, mission, totalResources, hasTroops, hasShips, priority, cKey, pKey }
    }

    // 1) Inactive players discovered by the world scan.
    for (const p of scanData?.players || []) {
      if (p.state !== 'inactive') continue
      const pKey = `${p.playerId}_${p.islandX}_${p.islandY}`
      const ignoreKey = p.cityId ? `${p.playerId}_${p.cityId}` : pKey
      if (ignoredKeys.has(ignoreKey) || ignoredKeys.has(pKey)) continue
      if (p.cityId) seenCityIds.add(String(p.cityId))
      enriched.push(enrichOne(p))
    }

    // 2) Farm targets absent from the current scan (e.g. added manually, or the scan is stale).
    //    Synthesize a row from the farm record so every target lives in one unified list
    //    instead of being split between this page and the Combat/Farm tab (Phase 3).
    for (const [cid, f] of Object.entries(farmByCity)) {
      if (seenCityIds.has(String(cid))) continue
      seenCityIds.add(String(cid))
      const synth: WorldScanPlayer = {
        playerId: `farm_${cid}`,
        cityId: String(cid),
        islandId: f.island_id != null ? String(f.island_id) : undefined,
        playerName: f.target_player || '',
        state: 'inactive',
        cityName: f.target_city_name || String(cid),
        islandName: '',
        islandX: f.island_x ?? 0,
        islandY: f.island_y ?? 0,
        nearestOwnCity: '',
        distance: Number.MAX_SAFE_INTEGER,
        mark: '',
        isNew: false,
      }
      enriched.push(enrichOne(synth))
    }

    enriched.sort((a, b) => {
      // Queued (farmed, enabled) targets lead, in queue order; discoveries follow.
      const qa = a.cityId ? queuePos[String(a.cityId)] : undefined
      const qb = b.cityId ? queuePos[String(b.cityId)] : undefined
      if (qa && qb) return qa - qb
      if (qa && !qb) return -1
      if (!qa && qb) return 1
      if (b.priority !== a.priority) return b.priority - a.priority
      if (a.totalResources !== null && b.totalResources !== null && a.totalResources !== b.totalResources)
        return b.totalResources - a.totalResources
      if (a.totalResources !== null && b.totalResources === null) return -1
      if (a.totalResources === null && b.totalResources !== null) return 1
      if (a.distance !== b.distance) return a.distance - b.distance
      return a.cKey.localeCompare(b.cKey)
    })

    return enriched
  }, [scanData, ignoredKeys, latestMissionByCityId, minLootTotal, farmByCity, queuePos])

  if (loading) return <Card className="p-8 text-center text-slate-400 text-sm">{t('loading')}</Card>
  if (error) return (
    <Card className="p-8 text-center">
      <p className="text-slate-500 text-sm mb-3">{error}</p>
      <button onClick={onForceRefresh} className="px-4 py-2 bg-orange-500 hover:bg-orange-600 text-white text-sm rounded-lg">
        {t('force_first_scan')}
      </button>
    </Card>
  )
  if (players.length === 0) return (
    <Card className="p-8 text-center text-slate-400 text-sm">{t('no_players_found')}</Card>
  )

  return (
    <div>
      <div className="mb-3">
        <button
          onClick={() => setShowFarmSettings(v => !v)}
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium bg-white border border-slate-200 text-slate-600 hover:bg-slate-50"
        >
          <i className="fa-solid fa-seedling text-emerald-600" />
          {t('farm_settings_title')}
          <i className={`fa-solid fa-chevron-${showFarmSettings ? 'up' : 'down'} text-[10px]`} />
        </button>
        {showFarmSettings && (
          <Card className="mt-2">
            <FarmSettings />
          </Card>
        )}
      </div>
      <Card>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="bg-slate-800 text-white text-xs uppercase tracking-wide">
                <th className="px-3 py-3 font-semibold text-center whitespace-nowrap" title={t('col_queue_pos')}>#</th>
                <th className="px-3 py-3 font-semibold text-left whitespace-nowrap">{t('col_state')}</th>
                <th className="px-3 py-3 font-semibold text-left whitespace-nowrap">{t('col_city')}</th>
                <th className="px-3 py-3 font-semibold text-left whitespace-nowrap">{t('col_player')}</th>
                <th className="px-3 py-3 font-semibold text-center whitespace-nowrap">{t('col_troops')}</th>
                <th className="px-3 py-3 font-semibold text-center whitespace-nowrap">{t('col_ships')}</th>
                <th className="px-3 py-3 font-semibold text-right whitespace-nowrap">{t('col_resources')}</th>
                <th className="px-3 py-3 font-semibold text-center" colSpan={3} />
              </tr>
            </thead>
            <tbody>
              {players.map((p, idx) => {
                const isExpanded  = expandedKey === p.cKey
                const hasReport   = p.mission?.state === 'DONE' && !!p.mission.result &&
                  !!(p.mission.result.resources && Object.keys(p.mission.result.resources).length > 0)
                const isActiveSpy = !!p.mission && _ACTIVE_SPY_STATES.has(p.mission.state)

                return (
                  <React.Fragment key={p.cKey}>
                    <tr className={`border-b transition-colors ${
                      isExpanded ? 'border-indigo-200 bg-indigo-50/30' : 'border-slate-100 hover:bg-slate-50'
                    } ${!isExpanded && idx % 2 ? 'bg-slate-50/40' : ''}`}>
                      <Td className="text-center px-1">
                        {(() => {
                          const q = p.cityId ? queuePos[String(p.cityId)] : undefined
                          if (!q) return <span className="text-slate-300 text-xs">—</span>
                          return (
                            <span className={`font-bold text-sm ${q === 1 ? 'text-red-600' : 'text-slate-500'}`}>#{q}</span>
                          )
                        })()}
                      </Td>
                      <Td>
                        <div className="flex flex-col gap-1 items-start">
                          <MissionStatePill priority={p.priority} mission={p.mission} />
                          {(() => {
                            const f = p.cityId ? farmByCity[String(p.cityId)] : undefined
                            if (!f || !f.enabled) return null
                            const fc = f.state === 'ATTACKING' ? 'bg-red-100 text-red-600'
                              : f.state === 'SPYING' ? 'bg-blue-100 text-blue-600' : 'bg-amber-100 text-amber-700'
                            return (
                              <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium ${fc}`}>
                                <i className="fa-solid fa-seedling text-[8px]" />
                                {t(`farm_state_${f.state}`)}
                              </span>
                            )
                          })()}
                        </div>
                      </Td>
                      <Td>
                        <div className="font-medium text-slate-700 text-sm">
                          {p.cityName}
                          {ambiguousCityKeys.has(`${p.playerName}|${p.cityName}`) && (
                            <span className="text-slate-400 text-xs font-normal ml-1">({p.cityId})</span>
                          )}
                        </div>
                        <div className="text-xs text-slate-400">{p.islandName} ({p.islandX},{p.islandY})</div>
                      </Td>
                      <Td>
                        <div className="flex items-center gap-1">
                          <span className="font-medium text-slate-800 text-sm">{p.playerName}</span>
                          <span className="text-[11px]" title={p.state}>💤</span>
                        </div>
                        {p.allyTag && (
                          <span className="px-1.5 py-0.5 bg-indigo-50 text-indigo-600 rounded text-xs font-mono">{p.allyTag}</span>
                        )}
                        {(() => {
                          const ls = lootByPlayer[(p.playerName || '').toLowerCase()]
                          if (!ls || ls.total <= 0) return null
                          return (
                            <div className="text-[10px] text-amber-600 mt-0.5" title={t('farm_loot_brought')}>
                              <i className="fa-solid fa-coins mr-1" />{fmt(ls.total)} · {ls.raids} {t('loot_raids')}
                            </div>
                          )
                        })()}
                      </Td>
                      <Td className="text-center">
                        {p.hasTroops === null
                          ? <span className="text-slate-300 text-xs">—</span>
                          : p.hasTroops
                            ? <span className="text-red-500 font-bold text-sm">✗</span>
                            : <span className="text-emerald-500 font-bold text-sm">✓</span>}
                      </Td>
                      <Td className="text-center">
                        {p.hasShips === null
                          ? <span className="text-slate-300 text-xs">—</span>
                          : p.hasShips
                            ? <span className="text-red-500 font-bold text-sm">✗</span>
                            : <span className="text-emerald-500 font-bold text-sm">✓</span>}
                      </Td>
                      <Td className="text-right font-mono">
                        {p.totalResources !== null
                          ? <span className="text-slate-700">{p.totalResources.toLocaleString()}</span>
                          : <span className="text-slate-300 text-xs">—</span>}
                      </Td>
                      {/* Spy button */}
                      <Td className="text-center px-1">
                        <button
                          onClick={() => setSpyTarget(p)}
                          title={!p.cityId || !p.islandId ? t('spy_no_city_id') : t('spy_send_btn')}
                          disabled={!p.cityId || !p.islandId}
                          className={`w-7 h-7 rounded-lg flex items-center justify-center text-xs transition-colors ${
                            !p.cityId || !p.islandId
                              ? 'bg-slate-50 text-slate-200 cursor-not-allowed'
                              : dispatchedKeys.has(p.cKey)
                                ? 'bg-amber-200 text-amber-700 hover:bg-amber-300'
                                : p.mission?.state === 'DONE'
                                  ? 'bg-emerald-100 text-emerald-700 hover:bg-emerald-200'
                                  : isActiveSpy
                                    ? 'bg-indigo-100 text-indigo-600 hover:bg-indigo-200'
                                    : p.mission?.state === 'FAILED'
                                      ? 'bg-red-100 text-red-500 hover:bg-red-200'
                                      : 'bg-slate-100 text-slate-500 hover:bg-amber-100 hover:text-amber-700'
                          }`}
                        >
                          <i className="fa-solid fa-user-secret" />
                        </button>
                      </Td>
                      {/* Action buttons: report / force-warehouse / recall / ignore */}
                      <Td className="text-center px-1">
                        <div className="flex items-center justify-center gap-0.5">
                          {hasReport ? (
                            <button
                              onClick={() => setExpandedKey(prev => prev === p.cKey ? null : p.cKey)}
                              title={t('spy_report_title')}
                              className={`w-7 h-7 rounded-lg flex items-center justify-center text-xs transition-colors ${
                                isExpanded ? 'bg-indigo-500 text-white' : 'bg-emerald-50 text-emerald-600 hover:bg-emerald-100'
                              }`}
                            >
                              <i className="fa-solid fa-file-lines" />
                            </button>
                          ) : <span className="block w-7 h-7" />}
                          {(['WAITING_AT_CITY','EXECUTING_WAREHOUSE','WAITING_FOR_GARRISON','EXECUTING_GARRISON','DONE'].includes(p.mission?.state ?? '')
                            || (p.mission?.state === 'FAILED' && p.mission?.originCityId)) ? (
                            <button
                              onClick={() => handleForceWarehouse(p)}
                              title={t('btn_force_warehouse')}
                              className="w-7 h-7 rounded-lg flex items-center justify-center text-xs text-amber-400 hover:text-amber-600 hover:bg-amber-50 transition-colors"
                            >
                              <i className="fa-solid fa-magnifying-glass" />
                            </button>
                          ) : <span className="block w-7 h-7" />}
                          {(p.mission?.originCityId && !['RECALLED'].includes(p.mission?.state ?? '')) ? (
                            <button
                              onClick={() => handleRecallSpy(p)}
                              title={t('btn_recall_spy')}
                              className="w-7 h-7 rounded-lg flex items-center justify-center text-xs text-slate-400 hover:text-blue-500 hover:bg-blue-50 transition-colors"
                            >
                              <i className="fa-solid fa-arrow-rotate-left" />
                            </button>
                          ) : <span className="block w-7 h-7" />}
                          <button
                            onClick={() => handleIgnore(p)}
                            title={t('btn_ignore_city')}
                            className="w-7 h-7 rounded-lg flex items-center justify-center text-xs text-slate-300 hover:text-red-400 hover:bg-red-50 transition-colors"
                          >
                            🚫
                          </button>
                          {p.cityId && farmByCity[String(p.cityId)] ? (
                            <button
                              onClick={() => farmAction(String(p.cityId), {}, true)}
                              title={t('btn_remove_farm')}
                              className="w-7 h-7 rounded-lg flex items-center justify-center text-xs text-slate-400 hover:text-red-600 hover:bg-red-50 transition-colors"
                            >
                              <i className="fa-solid fa-seedling" />
                              <i className="fa-solid fa-xmark text-[8px] -ml-1 -mt-2" />
                            </button>
                          ) : <span className="block w-7 h-7" />}
                        </div>
                      </Td>
                    </tr>

                    {isExpanded && p.mission?.state === 'DONE' && p.mission.result &&
                      p.mission.result.resources && Object.keys(p.mission.result.resources).length > 0 && (
                      <tr className="bg-indigo-50/40 border-b border-indigo-200">
                        <td colSpan={9} className="px-5 py-4">
                          <div className="flex flex-col gap-3 max-w-2xl">
                            {/* Warehouse */}
                            <div className="bg-white rounded-lg border border-emerald-200 px-4 py-3">
                              <p className="text-xs font-semibold text-emerald-700 mb-2 flex items-center gap-1.5">
                                <i className="fa-solid fa-warehouse" />
                                {t('spy_report_resources')} — {p.mission.result.targetCityName || p.cityName}
                              </p>
                              <p className="text-[10px] mb-2">
                                <span className={p.mission.result.success ? 'text-emerald-600' : 'text-red-500'}>
                                  {p.mission.result.success ? t('spy_report_success') : t('spy_report_failed')}
                                </span>
                                {p.mission.result.reportedAt && (
                                  <span className="ml-2 text-slate-400">{new Date(p.mission.result.reportedAt * 1000).toLocaleString()}</span>
                                )}
                              </p>
                              {p.mission.result.resources && Object.keys(p.mission.result.resources).length > 0 ? (
                                <div className="grid grid-cols-5 gap-1">
                                  {RES_KEYS.map(k => (
                                    <div key={k} className="text-center">
                                      <div className="text-[10px] text-slate-500">{RES_LABELS[k]}</div>
                                      <div className="text-xs font-semibold text-slate-700">
                                        {(p.mission!.result!.resources![k] ?? 0).toLocaleString()}
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              ) : (
                                <p className="text-xs text-slate-400 italic">{t('spy_no_resources')}</p>
                              )}
                            </div>

                            {/* Garrison */}
                            {p.mission.garrisonResult && !p.mission.garrisonResult.error && (
                              <div className="bg-white rounded-lg border border-amber-200 px-4 py-3">
                                <p className="text-xs font-semibold text-amber-700 mb-2 flex items-center gap-1.5">
                                  <i className="fa-solid fa-shield-halved" />
                                  {t('spy_garrison_title')} — {p.mission.garrisonResult.targetCityName || p.cityName}
                                </p>
                                {p.mission.garrisonResult.reportedAt && (
                                  <p className="text-[10px] text-slate-400 mb-2">
                                    {new Date(p.mission.garrisonResult.reportedAt * 1000).toLocaleString()}
                                  </p>
                                )}
                                {p.mission.garrisonResult.troops && Object.keys(p.mission.garrisonResult.troops).length > 0 ? (
                                  <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                                    {Object.entries(p.mission.garrisonResult.troops).map(([name, count]) => (
                                      <div key={name} className="flex justify-between text-xs">
                                        <span className="text-slate-600">{name}</span>
                                        <span className="font-semibold text-slate-800">{(count as number).toLocaleString()}</span>
                                      </div>
                                    ))}
                                  </div>
                                ) : (
                                  <p className="text-xs text-slate-400 italic">{t('spy_garrison_no_troops')}</p>
                                )}
                              </div>
                            )}
                            {p.mission.garrisonResult?.error && (
                              <p className="text-xs text-slate-400 italic px-1">{p.mission.garrisonResult.error}</p>
                            )}

                            {/* Real loot brought from this player (F1.b) */}
                            {(() => {
                              const ls = lootByPlayer[(p.playerName || '').toLowerCase()]
                              if (!ls || ls.total <= 0) return null
                              const vals = [ls.wood, ls.wine, ls.marble, ls.crystal, ls.sulfur]
                              const icons = ['fa-tree', 'fa-wine-bottle', 'fa-mountain', 'fa-gem', 'fa-flask']
                              const colors = ['text-green-500', 'text-red-400', 'text-slate-400', 'text-cyan-400', 'text-yellow-400']
                              return (
                                <div className="bg-white rounded-lg border border-amber-200 px-4 py-3">
                                  <p className="text-xs font-semibold text-amber-700 mb-2 flex items-center gap-1.5">
                                    <i className="fa-solid fa-coins" /> {t('farm_loot_brought')}
                                  </p>
                                  <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
                                    {vals.map((v, i) => v > 0 && (
                                      <span key={i}><i className={`fa-solid ${icons[i]} ${colors[i]} mr-1`} />{fmt(v)}</span>
                                    ))}
                                  </div>
                                  <p className="text-[10px] text-slate-400 mt-1.5">
                                    {t('loot_total')}: <span className="font-semibold text-amber-600">{fmt(ls.total)}</span>
                                    {' · '}{ls.raids} {t('loot_raids')}
                                    {' · '}{t('loot_last')} {new Date(ls.last_ts * 1000).toLocaleString()}
                                  </p>
                                </div>
                              )
                            })()}

                            {/* Farm status & controls (if this target is farmed) */}
                            {(() => {
                              const f = p.cityId ? farmByCity[String(p.cityId)] : undefined
                              if (!f) return null
                              const fc = f.state === 'ATTACKING' ? 'text-red-600'
                                : f.state === 'SPYING' ? 'text-blue-600' : 'text-amber-700'
                              return (
                                <div className={`bg-white rounded-lg border px-4 py-3 flex items-center gap-3 flex-wrap ${f.mode === 'loop' ? 'border-rose-200' : 'border-indigo-200'}`}>
                                  <span className={`text-xs font-semibold flex items-center gap-1.5 ${f.mode === 'loop' ? 'text-rose-700' : 'text-indigo-700'}`}>
                                    <i className={`fa-solid ${f.mode === 'loop' ? 'fa-repeat' : 'fa-seedling'}`} /> {f.mode === 'loop' ? t('loop_title') : t('farm_title')}
                                  </span>
                                  <span className={`text-xs font-medium ${fc}`}>{t(`farm_state_${f.state}`)}</span>
                                  <span className="text-[11px] text-slate-400">
                                    {f.mode === 'loop'
                                      ? t('farm_raids') + ': ' + f.total_raids
                                      : t('farm_interval', { n: String(f.interval_hours) }) + ' · ' + t('farm_raids') + ': ' + f.total_raids}
                                  </span>
                                  <div className="flex items-center gap-2 flex-wrap text-[11px] text-slate-400">
                                    <span className="flex items-center gap-1" title={t('farm_maxships_hint')}>
                                      {t('farm_maxships')}
                                      <input type="number" min={0} max={9999} value={f.max_enemy_ships ?? 0}
                                        onChange={e => farmAction(String(p.cityId), { maxEnemyShips: Math.max(0, Number(e.target.value)) })}
                                        className="w-14 border border-slate-200 rounded px-1 py-0.5 text-right" />
                                    </span>
                                    <span className="flex items-center gap-1">
                                      {t('farm_respy')}
                                      <input type="number" min={1} max={50} value={f.respy_every ?? 1}
                                        onChange={e => farmAction(String(p.cityId), { respyEvery: Math.max(1, Number(e.target.value)) })}
                                        className="w-12 border border-slate-200 rounded px-1 py-0.5 text-right" />
                                    </span>
                                    {f.is_fleet_target === 1 && (
                                      <>
                                        <span className="flex items-center gap-1" title={t('farm_fleetlead_hint')}>
                                          {t('farm_fleetlead')}
                                          <input type="number" min={1} max={120} value={f.fleet_lead_min ?? 5}
                                            onChange={e => farmAction(String(p.cityId), { fleetLeadMin: Math.max(1, Number(e.target.value)) })}
                                            className="w-12 border border-slate-200 rounded px-1 py-0.5 text-right" />min
                                        </span>
                                        <span className="flex items-center gap-1" title={t('farm_disperse_hint')}>
                                          {t('farm_disperse')}
                                          <input type="number" min={1} max={1440} value={f.disperse_min ?? 240}
                                            onChange={e => farmAction(String(p.cityId), { disperseMin: Math.max(1, Number(e.target.value)) })}
                                            className="w-14 border border-slate-200 rounded px-1 py-0.5 text-right" />min
                                        </span>
                                      </>
                                    )}
                                  </div>
                                  <div className="ml-auto flex items-center gap-3">
                                    <button onClick={() => farmAction(String(p.cityId), { runNow: true })}
                                            className="text-xs text-indigo-500 hover:text-indigo-700 font-medium" title={t('farm_runnow')}>
                                      <i className="fa-solid fa-bolt mr-1" />{t('farm_runnow')}
                                    </button>
                                    <button onClick={() => farmAction(String(p.cityId), { enabled: !f.enabled })}
                                            className="text-xs text-slate-500 hover:text-slate-700"
                                            title={f.enabled ? t('pause_pause') : t('pause_resume')}>
                                      <i className={`fa-solid ${f.enabled ? 'fa-pause' : 'fa-play'}`} />
                                    </button>
                                    <button onClick={() => farmAction(String(p.cityId), {}, true)}
                                            className="text-xs text-red-400 hover:text-red-600" title={t('farm_remove')}>
                                      <i className="fa-solid fa-trash" />
                                    </button>
                                  </div>
                                </div>
                              )
                            })()}

                            {/* Manual attack + add-to-farm (when spied and ready) */}
                            <div className="flex justify-end items-center gap-2 pt-1">
                              {p.priority === 6 && p.cityId && (
                                farmIds.has(String(p.cityId)) ? (
                                  <span className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-emerald-600">
                                    <i className="fa-solid fa-seedling" /> {t('farm_in')}
                                  </span>
                                ) : (
                                  <>
                                    <button
                                      onClick={() => handleAddFarm(p)}
                                      title={t('farm_add')}
                                      className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-amber-500 hover:bg-amber-600 text-white rounded-lg transition-colors"
                                    >
                                      <i className="fa-solid fa-seedling" /> {t('farm_add')}
                                    </button>
                                    <button
                                      onClick={() => handleAddFarm(p, 'loop')}
                                      title={t('loop_add_hint')}
                                      className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-rose-600 hover:bg-rose-700 text-white rounded-lg transition-colors"
                                    >
                                      <i className="fa-solid fa-repeat" /> {t('loop_add')}
                                    </button>
                                  </>
                                )
                              )}
                              <button
                                onClick={() => setAttackTarget(p)}
                                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-red-600 hover:bg-red-700 text-white rounded-lg transition-colors"
                              >
                                <i className="fa-solid fa-crosshairs" /> {t('attack_prepare')}
                              </button>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
        <div className="px-5 py-3 border-t border-slate-100 text-xs text-slate-400">
          {players.length !== 1 ? t('player_count_plural', { n: players.length }) : t('player_count_single', { n: players.length })}
        </div>
      </Card>

      {spyTarget && (
        <SpyModal
          player={spyTarget}
          ownCities={ownCities}
          spyCounts={spyCounts}
          originCityId={spyOriginCityId}
          onClose={() => setSpyTarget(null)}
          onDispatched={() => {
            setDispatchedKeys(prev => new Set([...prev, spyTarget.cKey]))
            pushToast(t('spy_queued_ok', { player: spyTarget.playerName }), 'ok')
          }}
        />
      )}

      {attackTarget && (
        <AttackModal
          player={attackTarget}
          ownCities={ownCities}
          defaultOriginCityId={spyOriginCityId}
          onClose={() => setAttackTarget(null)}
          onQueued={name => pushToast(t('attack_queued', { player: name }), 'ok')}
        />
      )}

      {/* Confirmation modal for force-warehouse and recall */}
      {confirmModal && (
        <ConfirmModal
          title={confirmModal.action === 'force-warehouse' ? t('btn_force_warehouse') : t('btn_recall_spy')}
          tone={confirmModal.action === 'recall' ? 'blue' : 'amber'}
          body={
            <>
              {confirmModal.player.cityName}
              {ambiguousCityKeys.has(`${confirmModal.player.playerName}|${confirmModal.player.cityName}`) && (
                <span className="text-slate-400 text-xs ml-1">({confirmModal.player.cityId})</span>
              )}
              {' '}— {confirmModal.player.playerName}
            </>
          }
          onCancel={() => setConfirmModal(null)}
          onConfirm={handleConfirmAction}
        />
      )}
    </div>
  )
}

// ── IgnoradasTab ──────────────────────────────────────────────────────────────

