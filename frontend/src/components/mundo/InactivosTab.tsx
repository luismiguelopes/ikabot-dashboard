import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { useT } from '../../i18n'
import { fmt } from '../../utils'
import { Card } from '../ui/Card'
import { Td } from '../ui/TableCells'
import { SpyModal } from './SpyModal'
import { AttackModal } from './AttackModal'
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
  const [dispatchedOk,   setDispatchedOk]   = useState<string | null>(null)
  const [attackOk,       setAttackOk]       = useState<string | null>(null)
  const [missions,       setMissions]       = useState<SpyMission[]>([])
  const [minLootTotal,   setMinLootTotal]   = useState(50000)
  const [ignoredKeys,    setIgnoredKeys]    = useState<Set<string>>(new Set())
  const [confirmModal,   setConfirmModal]   = useState<{ action: 'force-warehouse' | 'recall', player: EnrichedPlayer } | null>(null)
  const [toast,          setToast]          = useState<{ msg: string; ok: boolean } | null>(null)

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
  const loadFarm = () => fetch('/api/farm').then(r => r.json())
    .then((d: FarmTarget[]) => {
      if (!Array.isArray(d)) return
      setFarmIds(new Set(d.map(f => String(f.target_city_id))))
      setFarmByCity(Object.fromEntries(d.map(f => [String(f.target_city_id), f])))
    }).catch(() => {})
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

  async function handleAddFarm(p: EnrichedPlayer) {
    if (!p.cityId) return
    const res = await fetch('/api/farm/add', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        targetCityId: p.cityId, targetCityName: p.cityName, targetPlayer: p.playerName,
        islandId: p.islandId, islandX: p.islandX, islandY: p.islandY,
      }),
    }).catch(() => null)
    if (res && res.ok) {
      setFarmIds(prev => new Set([...prev, String(p.cityId)]))
      setToast({ msg: `${t('farm_add')}: ${p.cityName}`, ok: true })
      setTimeout(() => setToast(null), 4000)
    }
    loadFarm()
  }

  async function farmAction(cityId: string, body: Record<string, unknown>, remove = false) {
    await fetch(remove ? '/api/farm/remove' : '/api/farm/update', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ targetCityId: cityId, ...body }),
    }).catch(() => {})
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

  const showToast = useCallback((msg: string, ok: boolean) => {
    setToast({ msg, ok })
    setTimeout(() => setToast(null), 4000)
  }, [])

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
    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cityId: player.cityId }),
    })
      .then(r => r.json())
      .then(d => {
        if (d.ok) showToast(action === 'force-warehouse' ? `Inspecção agendada — ${player.cityName}` : `Espião chamado de volta — ${player.cityName}`, true)
        else showToast(d.error || 'Erro', false)
      })
      .catch(() => showToast('Erro de rede', false))
  }, [confirmModal, showToast])

  const handleIgnore = useCallback((p: EnrichedPlayer) => {
    const ignoreKey = p.cityId ? `${p.playerId}_${p.cityId}` : p.pKey
    setIgnoredKeys(prev => new Set([...prev, ignoreKey]))
    fetch('/api/world-scan/mark', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ playerId: p.playerId, cityId: p.cityId, islandX: p.islandX, islandY: p.islandY, status: 'ignorar', note: 'Ignorado manualmente' }),
    }).catch(() => {})
  }, [])

  const ambiguousCityKeys = useMemo((): Set<string> => {
    if (!scanData?.players) return new Set()
    const counts: Record<string, number> = {}
    for (const p of scanData.players)
      counts[`${p.playerName}|${p.cityName}`] = (counts[`${p.playerName}|${p.cityName}`] || 0) + 1
    return new Set(Object.keys(counts).filter(k => counts[k] > 1))
  }, [scanData])

  const players = useMemo((): EnrichedPlayer[] => {
    if (!scanData?.players) return []
    const enriched: EnrichedPlayer[] = []

    for (const p of scanData.players) {
      if (p.state !== 'inactive') continue
      const pKey = `${p.playerId}_${p.islandX}_${p.islandY}`
      const ignoreKey = p.cityId ? `${p.playerId}_${p.cityId}` : pKey
      if (ignoredKeys.has(ignoreKey) || ignoredKeys.has(pKey)) continue

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

      enriched.push({ ...p, mission, totalResources, hasTroops, hasShips, priority, cKey, pKey })
    }

    enriched.sort((a, b) => {
      if (b.priority !== a.priority) return b.priority - a.priority
      if (a.totalResources !== null && b.totalResources !== null && a.totalResources !== b.totalResources)
        return b.totalResources - a.totalResources
      if (a.totalResources !== null && b.totalResources === null) return -1
      if (a.totalResources === null && b.totalResources !== null) return 1
      if (a.distance !== b.distance) return a.distance - b.distance
      return a.cKey.localeCompare(b.cKey)
    })

    return enriched
  }, [scanData, ignoredKeys, latestMissionByCityId, minLootTotal])

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
      <Card>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="bg-slate-800 text-white text-xs uppercase tracking-wide">
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
                          {(['WAITING_AT_CITY','EXECUTING_WAREHOUSE','WAITING_FOR_GARRISON','EXECUTING_GARRISON','DONE'].includes(p.mission?.state ?? '')) ? (
                            <button
                              onClick={() => handleForceWarehouse(p)}
                              title={t('btn_force_warehouse')}
                              className="w-7 h-7 rounded-lg flex items-center justify-center text-xs text-amber-400 hover:text-amber-600 hover:bg-amber-50 transition-colors"
                            >
                              <i className="fa-solid fa-magnifying-glass" />
                            </button>
                          ) : <span className="block w-7 h-7" />}
                          {(p.mission?.originCityId && !['FAILED','RECALLED'].includes(p.mission?.state ?? '')) ? (
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
                        </div>
                      </Td>
                    </tr>

                    {isExpanded && p.mission?.state === 'DONE' && p.mission.result &&
                      p.mission.result.resources && Object.keys(p.mission.result.resources).length > 0 && (
                      <tr className="bg-indigo-50/40 border-b border-indigo-200">
                        <td colSpan={8} className="px-5 py-4">
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
                                <div className="bg-white rounded-lg border border-indigo-200 px-4 py-3 flex items-center gap-3 flex-wrap">
                                  <span className="text-xs font-semibold text-indigo-700 flex items-center gap-1.5">
                                    <i className="fa-solid fa-seedling" /> {t('farm_title')}
                                  </span>
                                  <span className={`text-xs font-medium ${fc}`}>{t(`farm_state_${f.state}`)}</span>
                                  <span className="text-[11px] text-slate-400">
                                    {t('farm_interval', { n: String(f.interval_hours) })} · {t('farm_raids')}: {f.total_raids}
                                  </span>
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
                                  <button
                                    onClick={() => handleAddFarm(p)}
                                    title={t('farm_add')}
                                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-amber-500 hover:bg-amber-600 text-white rounded-lg transition-colors"
                                  >
                                    <i className="fa-solid fa-seedling" /> {t('farm_add')}
                                  </button>
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
            setDispatchedOk(spyTarget.playerName)
            setDispatchedKeys(prev => new Set([...prev, spyTarget.cKey]))
            setTimeout(() => setDispatchedOk(null), 4000)
          }}
        />
      )}

      {dispatchedOk && (
        <div className="fixed bottom-6 right-6 z-50 px-4 py-3 bg-emerald-600 text-white text-sm font-medium rounded-xl shadow-lg flex items-center gap-2">
          <i className="fa-solid fa-check" />
          {t('spy_queued_ok', { player: dispatchedOk })}
        </div>
      )}

      {attackTarget && (
        <AttackModal
          player={attackTarget}
          ownCities={ownCities}
          defaultOriginCityId={spyOriginCityId}
          onClose={() => setAttackTarget(null)}
          onQueued={name => {
            setAttackOk(name)
            setTimeout(() => setAttackOk(null), 4000)
          }}
        />
      )}

      {attackOk && (
        <div className="fixed bottom-6 right-6 z-50 px-4 py-3 bg-red-600 text-white text-sm font-medium rounded-xl shadow-lg flex items-center gap-2">
          <i className="fa-solid fa-crosshairs" />
          {t('attack_queued', { player: attackOk })}
        </div>
      )}

      {/* Confirmation modal for force-warehouse and recall */}
      {confirmModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl p-6 max-w-sm w-full mx-4">
            <p className="text-sm font-semibold text-slate-800 mb-1">
              {confirmModal.action === 'force-warehouse' ? t('btn_force_warehouse') : t('btn_recall_spy')}
            </p>
            <p className="text-sm text-slate-500 mb-5">
              {confirmModal.player.cityName}
              {ambiguousCityKeys.has(`${confirmModal.player.playerName}|${confirmModal.player.cityName}`) && (
                <span className="text-slate-400 text-xs ml-1">({confirmModal.player.cityId})</span>
              )}
              {' '}— {confirmModal.player.playerName}
            </p>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setConfirmModal(null)}
                className="px-4 py-2 text-sm text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors"
              >
                {t('cancel')}
              </button>
              <button
                onClick={handleConfirmAction}
                className={`px-4 py-2 text-sm text-white rounded-lg transition-colors ${
                  confirmModal.action === 'recall' ? 'bg-blue-500 hover:bg-blue-600' : 'bg-amber-500 hover:bg-amber-600'
                }`}
              >
                {t('confirm')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Toast notification */}
      {toast && (
        <div className={`fixed bottom-6 right-6 z-50 flex items-center gap-2 px-4 py-3 rounded-xl shadow-lg text-sm text-white ${toast.ok ? 'bg-emerald-500' : 'bg-red-500'}`}>
          <i className={`fa-solid ${toast.ok ? 'fa-check' : 'fa-xmark'}`} />
          {toast.msg}
        </div>
      )}
    </div>
  )
}

// ── IgnoradasTab ──────────────────────────────────────────────────────────────

