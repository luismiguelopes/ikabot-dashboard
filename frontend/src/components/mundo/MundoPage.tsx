import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { useT, useLang, getLocale } from '../../i18n'
import { exportCsv } from '../../utils'
import { RESOURCE_ICONS, RESOURCE_COLORS } from '../../constants'
import { Card } from '../ui/Card'
import { PageHeader } from '../ui/PageHeader'
import { Td } from '../ui/TableCells'
import { loadSpyDefaults, saveSpyDefaults } from '../SettingsPage'
import type { WorldScanData, WorldScanPlayer, WorldScanIsland, ScanStatus, OwnCity } from '../../types'

interface CitySpyCounts { available: number | null; inDefense: number | null; inTraining: number | null; deployed: number | null }

interface SpyMissionResult { success: boolean; targetCityName: string | null; resources: Record<string, number> | null; troops?: Record<string, number> | null; reportedAt: number }
interface SpyGarrisonResult { success?: boolean; targetCityName?: string | null; troops: Record<string, number> | null; reportedAt?: number; error?: string }
interface SpyMission {
  originCityId: string; targetCityId: string; targetPlayerName: string; targetCityName: string
  islandX: number; islandY: number; numAgents: number
  state: 'TRAVELING' | 'WAITING_AT_CITY' | 'EXECUTING' | 'EXECUTING_WAREHOUSE' | 'WAITING_FOR_GARRISON' | 'EXECUTING_GARRISON' | 'DONE' | 'FAILED'
  dispatchedAt: number; arrivedAt: number | null; executedAt: number | null
  garrisonExecuteAfter: number | null; garrisonExecutedAt: number | null
  missionType: string | null; result: SpyMissionResult | null; garrisonResult: SpyGarrisonResult | null; error?: string
}

interface SpyModalProps {
  player: WorldScanPlayer
  ownCities: OwnCity[]
  spyCounts: Record<string, CitySpyCounts>
  originCityId: string
  onClose: () => void
  onDispatched: () => void
}

function SpyModal({ player, ownCities, spyCounts, originCityId: defaultOriginCityId, onClose, onDispatched }: SpyModalProps) {
  const t = useT()
  const [originCityId, setOriginCityId] = useState<string>(
    defaultOriginCityId || (ownCities.length > 0 ? String(ownCities[0].cityId) : '')
  )
  const [numAgents, setNumAgents] = useState(loadSpyDefaults().numAgents)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const hasIslandId = !!player.cityId && !!player.islandId

  async function handleSend() {
    if (!originCityId || !hasIslandId) return
    setSending(true)
    setError(null)
    try {
      const res = await fetch('/api/espionage/dispatch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          originCityId,
          targetCityId: player.cityId,
          islandId: player.islandId,
          targetPlayerName: player.playerName,
          targetCityName: player.cityName,
          islandX: player.islandX,
          islandY: player.islandY,
          numAgents,
          numDecoys: 0,
        }),
      })
      const data = await res.json()
      if (!res.ok) { setError(data.error || 'Erro desconhecido'); return }
      onDispatched()
      onClose()
    } catch (e) {
      setError(String(e))
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-sm mx-4" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold text-slate-800">
            {t('spy_modal_title')} — <span className="text-indigo-600">{player.playerName}</span>
          </h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 text-lg leading-none">✕</button>
        </div>

        <div className="text-xs text-slate-500 mb-4 space-y-0.5">
          <div><span className="font-medium text-slate-700">{t('col_island')}:</span> {player.islandName} ({player.islandX},{player.islandY})</div>
          <div><span className="font-medium text-slate-700">{t('col_city')}:</span> {player.cityName}</div>
        </div>

        {!hasIslandId && (
          <div className="mb-4 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-700">
            {t('spy_no_city_id')}
          </div>
        )}

        <div className="space-y-3 mb-5">
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">{t('spy_origin_city')}</label>
            <select
              value={originCityId}
              onChange={e => setOriginCityId(e.target.value)}
              disabled={!hasIslandId}
              className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-400 disabled:opacity-50"
            >
              {ownCities.map(c => {
                const id = String(c.cityId)
                const sc = spyCounts[id]
                let label = c.name
                if (sc) {
                  if (sc.inDefense != null)
                    label = `${c.name} (${sc.inDefense} disponíveis)`
                  else if (sc.deployed != null && sc.deployed > 0)
                    label = `${c.name} (${sc.deployed} em campo)`
                }
                return <option key={c.cityId} value={id}>{label}</option>
              })}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">{t('spy_num_agents')}</label>
            <input
              type="number"
              min={1}
              max={99}
              value={numAgents}
              onChange={e => setNumAgents(Math.max(1, parseInt(e.target.value) || 1))}
              disabled={!hasIslandId}
              className="w-24 text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-400 disabled:opacity-50"
            />
          </div>
        </div>

        {error && (
          <div className="mb-3 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700">{error}</div>
        )}

        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm text-slate-600 hover:text-slate-800 rounded-lg border border-slate-200 hover:bg-slate-50 transition-colors">
            {t('cancel')}
          </button>
          <button
            onClick={handleSend}
            disabled={sending || !hasIslandId || !originCityId}
            className="px-4 py-2 text-sm font-medium bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white rounded-lg transition-colors"
          >
            {sending ? t('spy_sending') : t('spy_send_btn')}
          </button>
        </div>
      </div>
    </div>
  )
}

interface MilitaryUnit { name: string; amount: number }
interface CityMilitary { cityId: string; troops: Record<string, MilitaryUnit>; fleet: Record<string, MilitaryUnit> }
interface MilitaryData { lastUpdated: number; byCityName: Record<string, CityMilitary> }

interface AttackWavePlan {
  waveNum: number; originCityId: string; originCityName: string
  fleetUnits: Record<string, number>; troopUnits: Record<string, number>
  transporters: number; fleetDispatchAfter: number | null; armyDispatchAfter: number
  fleetDispatchedAt: number | null; armyDispatchedAt: number | null
  estimatedReturnAt: number; status: string
}
interface AttackWaveEntry {
  id: string; sourceMissionKey: string; targetPlayerName: string
  targetCityId: string; targetIslandId: string; islandX: number; islandY: number
  state: string; tier: number | null; wavePlans: AttackWavePlan[]
  createdAt: number; skippedReason: string | null
}
interface AttackWaves { waves: AttackWaveEntry[] }

interface AttackModalProps {
  player: WorldScanPlayer
  ownCities: OwnCity[]
  defaultOriginCityId: string
  onClose: () => void
  onQueued: (playerName: string) => void
}

function AttackModal({ player, ownCities, defaultOriginCityId, onClose, onQueued }: AttackModalProps) {
  const t = useT()
  const [originCityId, setOriginCityId] = useState(
    defaultOriginCityId || (ownCities.length > 0 ? String(ownCities[0].cityId) : '')
  )
  const [military, setMilitary] = useState<MilitaryData | null>(null)
  const [unitInputs, setUnitInputs] = useState<Record<string, number>>({})
  const [transporters, setTransporters] = useState(0)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/military').then(r => r.json()).then((d: MilitaryData) => setMilitary(d)).catch(() => {})
  }, [])

  const originCityName = ownCities.find(c => String(c.cityId) === originCityId)?.name || ''
  const units = military?.byCityName[originCityName]?.troops || {}
  const hasUnits = Object.values(unitInputs).some(v => v > 0)

  async function handleConfirm() {
    if (!hasUnits) { setError(t('attack_no_units')); return }
    if (!player.cityId || !player.islandId) { setError(t('spy_no_city_id')); return }
    setSending(true)
    setError(null)
    try {
      const res = await fetch('/api/espionage/attack-queue/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          originCityId,
          originCityName,
          targetCityId: player.cityId,
          targetCityName: player.cityName,
          targetPlayerName: player.playerName,
          islandX: player.islandX,
          islandY: player.islandY,
          islandId: player.islandId,
          units: unitInputs,
          transporters,
        }),
      })
      const data = await res.json()
      if (!res.ok) { setError(data.error || 'Erro desconhecido'); return }
      onQueued(player.playerName)
      onClose()
    } catch (e) {
      setError(String(e))
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-md mx-4 max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold text-slate-800 flex items-center gap-2">
            <i className="fa-solid fa-crosshairs text-red-500" />
            {t('attack_modal_title')} — <span className="text-red-600">{player.playerName}</span>
          </h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 text-lg leading-none">✕</button>
        </div>

        <div className="text-xs text-slate-500 mb-4 space-y-0.5">
          <div><span className="font-medium text-slate-700">{t('col_island')}:</span> {player.islandName} ({player.islandX},{player.islandY})</div>
          <div><span className="font-medium text-slate-700">{t('col_city')}:</span> {player.cityName}</div>
        </div>

        <div className="mb-4">
          <label className="block text-xs font-medium text-slate-600 mb-1">{t('attack_origin_city')}</label>
          <select
            value={originCityId}
            onChange={e => { setOriginCityId(e.target.value); setUnitInputs({}) }}
            className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-red-400"
          >
            {ownCities.map(c => (
              <option key={c.cityId} value={String(c.cityId)}>{c.name}</option>
            ))}
          </select>
        </div>

        <div className="mb-4">
          <p className="text-xs font-medium text-slate-600 mb-2">{t('attack_troops_table')}</p>
          {!military || Object.keys(units).length === 0 ? (
            <p className="text-xs text-slate-400 italic">{t('attack_no_military')}</p>
          ) : (
            <div className="border border-slate-200 rounded-lg overflow-hidden">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-slate-50 border-b border-slate-200">
                    <th className="text-left px-3 py-2 font-medium text-slate-600">Unidade</th>
                    <th className="text-center px-3 py-2 font-medium text-slate-600">{t('attack_available')}</th>
                    <th className="text-center px-3 py-2 font-medium text-slate-600">{t('attack_send_count')}</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(units).map(([uid, unit]) => (
                    <tr key={uid} className="border-b border-slate-100 last:border-0">
                      <td className="px-3 py-2 text-slate-700">{unit.name}</td>
                      <td className="px-3 py-2 text-center text-slate-500 font-mono">{unit.amount.toLocaleString()}</td>
                      <td className="px-3 py-2 text-center">
                        <input
                          type="number" min={0} max={unit.amount}
                          value={unitInputs[uid] ?? 0}
                          onChange={e => {
                            const n = Math.max(0, Math.min(unit.amount, parseInt(e.target.value) || 0))
                            setUnitInputs(prev => ({ ...prev, [uid]: n }))
                          }}
                          className="w-20 text-xs border border-slate-200 rounded px-2 py-1 text-center focus:outline-none focus:ring-1 focus:ring-red-400"
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="mb-5">
          <label className="block text-xs font-medium text-slate-600 mb-1">{t('attack_ships')}</label>
          <input
            type="number" min={0} value={transporters}
            onChange={e => setTransporters(Math.max(0, parseInt(e.target.value) || 0))}
            className="w-24 text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-red-400"
          />
        </div>

        {error && (
          <div className="mb-3 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700">{error}</div>
        )}

        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm text-slate-600 hover:text-slate-800 rounded-lg border border-slate-200 hover:bg-slate-50 transition-colors">
            {t('cancel')}
          </button>
          <button
            onClick={handleConfirm}
            disabled={sending || !hasUnits || !player.cityId || !player.islandId}
            className="px-4 py-2 text-sm font-medium bg-red-600 hover:bg-red-700 disabled:opacity-40 text-white rounded-lg transition-colors flex items-center gap-2"
          >
            {sending
              ? <><i className="fa-solid fa-spinner fa-spin" /> {t('spy_sending')}</>
              : <><i className="fa-solid fa-crosshairs" /> {t('attack_confirm')}</>
            }
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Naval unit detection ──────────────────────────────────────────────────────

const NAVAL_KEYWORDS = ['navio', 'ship', 'steam giant', 'galley', 'trireme', 'balloon', 'ram', 'mortar', 'catapult', 'flamethrower']

function isNavalUnit(name: string): boolean {
  const n = name.toLowerCase()
  return NAVAL_KEYWORDS.some(k => n.includes(k))
}

// ── EnrichedPlayer ────────────────────────────────────────────────────────────

interface EnrichedPlayer extends WorldScanPlayer {
  mission: SpyMission | undefined
  wave: AttackWaveEntry | undefined
  totalResources: number | null
  hasTroops: boolean | null   // null = no garrison data; false = clear; true = has troops
  hasShips: boolean | null
  priority: number
  cKey: string  // cityId (or fallback) — mission/dispatched lookup, unique per city
  pKey: string  // `${playerId}_${islandX}_${islandY}` — mark/ignore key (per player+island)
}

// ── MissionStatePill ──────────────────────────────────────────────────────────

function MissionStatePill({ priority, mission, wave }: {
  priority: number
  mission: SpyMission | undefined
  wave: AttackWaveEntry | undefined
}) {
  const t = useT()

  if (wave && wave.state === 'IN_PROGRESS') return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700">
      <i className="fa-solid fa-crosshairs text-[9px]" /> {t('pipeline_attacking')}
    </span>
  )
  if (wave && wave.state === 'PENDING') return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-700">
      <i className="fa-solid fa-clock text-[9px]" /> {t('pipeline_attack_pending')}
    </span>
  )
  if (wave && (wave.state === 'DONE' || wave.state === 'AUTO_SKIPPED' || wave.state === 'FAILED')) return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-slate-50 text-slate-400">
      {wave.state === 'DONE' ? t('pipeline_attack_done') : t('pipeline_skipped')}
    </span>
  )

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

function InactivosTab({ scanData, loading, error, onForceRefresh, ownCities, spyCounts, spyOriginCityId }: InactivosTabProps) {
  const t = useT()
  const [expandedKey,    setExpandedKey]    = useState<string | null>(null)
  const [spyTarget,      setSpyTarget]      = useState<EnrichedPlayer | null>(null)
  const [attackTarget,   setAttackTarget]   = useState<EnrichedPlayer | null>(null)
  const [dispatchedKeys, setDispatchedKeys] = useState<Set<string>>(new Set())
  const [dispatchedOk,   setDispatchedOk]   = useState<string | null>(null)
  const [attackOk,       setAttackOk]       = useState<string | null>(null)
  const [missions,       setMissions]       = useState<SpyMission[]>([])
  const [attackWaves,    setAttackWaves]    = useState<AttackWaveEntry[]>([])
  const [minLootTotal,   setMinLootTotal]   = useState(50000)
  const [ignoredKeys,    setIgnoredKeys]    = useState<Set<string>>(new Set())

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
    const load = () => fetch('/api/espionage/attack-waves').then(r => r.json())
      .then((d: AttackWaves) => { if (d.waves) setAttackWaves(d.waves) }).catch(() => {})
    load()
    const id = setInterval(load, 60000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    fetch('/api/espionage/auto-attack-settings').then(r => r.json())
      .then(d => { if (d.minLootTotal != null) setMinLootTotal(d.minLootTotal) }).catch(() => {})
  }, [])

  const latestMissionByCityId = useMemo(() => {
    const map: Record<string, SpyMission> = {}
    for (const m of missions) {
      const key = m.targetCityId
      if (!key) continue
      if (!map[key] || m.dispatchedAt > map[key].dispatchedAt) map[key] = m
    }
    return map
  }, [missions])

  const latestWaveByWKey = useMemo(() => {
    const map: Record<string, AttackWaveEntry> = {}
    for (const w of attackWaves) {
      // sourceMissionKey = `${targetCityId}_${islandX}_${islandY}`
      const key = w.sourceMissionKey
      if (!map[key] || w.createdAt > map[key].createdAt) map[key] = w
    }
    return map
  }, [attackWaves])

  const handleIgnore = useCallback((p: EnrichedPlayer) => {
    setIgnoredKeys(prev => new Set([...prev, p.pKey]))
    fetch('/api/world-scan/mark', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ playerId: p.playerId, islandX: p.islandX, islandY: p.islandY, status: 'ignorar' }),
    }).catch(() => {})
  }, [])

  const players = useMemo((): EnrichedPlayer[] => {
    if (!scanData?.players) return []
    const enriched: EnrichedPlayer[] = []

    for (const p of scanData.players) {
      if (p.state !== 'inactive') continue
      const pKey = `${p.playerId}_${p.islandX}_${p.islandY}`
      if (ignoredKeys.has(pKey)) continue

      const cKey = p.cityId || `${p.playerName}_${p.cityName}_${p.islandX}_${p.islandY}`
      const wKey = `${p.cityId}_${p.islandX}_${p.islandY}`
      const mission = p.cityId ? latestMissionByCityId[p.cityId] : undefined
      const wave = latestWaveByWKey[wKey]

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
      if (wave) {
        if (wave.state === 'IN_PROGRESS') priority = 8
        else if (wave.state === 'PENDING') priority = 7
        else priority = -1
      } else if (mission) {
        if (mission.state === 'FAILED') priority = 0
        else if (_ACTIVE_SPY_STATES.has(mission.state)) priority = 2
        else if (mission.state === 'DONE') {
          if (!mission.result) priority = 1
          else if (mission.garrisonResult && !mission.garrisonResult.error) {
            priority = (totalResources || 0) >= minLootTotal ? (hasShips ? 5 : 6) : 4
          } else {
            priority = 3
          }
        }
      }

      enriched.push({ ...p, mission, wave, totalResources, hasTroops, hasShips, priority, cKey, pKey })
    }

    enriched.sort((a, b) => {
      if (b.priority !== a.priority) return b.priority - a.priority
      if (a.totalResources !== null && b.totalResources !== null && a.totalResources !== b.totalResources)
        return b.totalResources - a.totalResources
      if (a.totalResources !== null && b.totalResources === null) return -1
      if (a.totalResources === null && b.totalResources !== null) return 1
      return a.distance - b.distance
    })

    return enriched
  }, [scanData, ignoredKeys, latestMissionByCityId, latestWaveByWKey, minLootTotal])

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
                const isExpanded  = expandedKey === p.pKey
                const hasReport   = p.mission?.state === 'DONE' && !!p.mission.result
                const isActiveSpy = !!p.mission && _ACTIVE_SPY_STATES.has(p.mission.state)

                return (
                  <React.Fragment key={p.pKey}>
                    <tr className={`border-b transition-colors ${
                      isExpanded ? 'border-indigo-200 bg-indigo-50/30' : 'border-slate-100 hover:bg-slate-50'
                    } ${!isExpanded && idx % 2 ? 'bg-slate-50/40' : ''}`}>
                      <Td>
                        <MissionStatePill priority={p.priority} mission={p.mission} wave={p.wave} />
                      </Td>
                      <Td>
                        <div className="font-medium text-slate-700 text-sm">{p.cityName}</div>
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
                      {/* Report button */}
                      <Td className="text-center px-1">
                        {hasReport ? (
                          <button
                            onClick={() => setExpandedKey(prev => prev === p.pKey ? null : p.pKey)}
                            title={t('spy_report_title')}
                            className={`w-7 h-7 rounded-lg flex items-center justify-center text-xs transition-colors ${
                              isExpanded ? 'bg-indigo-500 text-white' : 'bg-emerald-50 text-emerald-600 hover:bg-emerald-100'
                            }`}
                          >
                            <i className="fa-solid fa-file-lines" />
                          </button>
                        ) : <span className="block w-7 h-7" />}
                      </Td>
                      {/* Ignore button */}
                      <Td className="text-center px-1">
                        <button
                          onClick={() => handleIgnore(p)}
                          title={t('btn_ignore_city')}
                          className="w-7 h-7 rounded-lg flex items-center justify-center text-xs text-slate-300 hover:text-red-400 hover:bg-red-50 transition-colors"
                        >
                          🚫
                        </button>
                      </Td>
                    </tr>

                    {isExpanded && p.mission?.state === 'DONE' && p.mission.result && (
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

                            {/* Wave plan */}
                            {p.wave && (
                              <div className="bg-white rounded-lg border border-slate-200 px-4 py-3">
                                {(() => {
                                  const stateColor: Record<string, string> = {
                                    PENDING: 'text-amber-600', IN_PROGRESS: 'text-blue-600',
                                    DONE: 'text-emerald-600', FAILED: 'text-red-600', AUTO_SKIPPED: 'text-slate-400',
                                  }
                                  return (
                                    <>
                                      <p className={`text-xs font-semibold mb-2 flex items-center justify-between gap-1.5 ${stateColor[p.wave!.state] || 'text-slate-600'}`}>
                                        <span><i className="fa-solid fa-bolt" /> {t('auto_attack_title')}</span>
                                        <span className="font-normal">
                                          {t(`auto_attack_state_${p.wave!.state}` as 'auto_attack_title')}
                                          {p.wave!.tier !== null && ` — ${t(`auto_attack_tier${p.wave!.tier}` as 'auto_attack_title')}`}
                                        </span>
                                        <button
                                          onClick={() => {
                                            fetch('/api/espionage/attack-waves/cancel', {
                                              method: 'POST',
                                              headers: { 'Content-Type': 'application/json' },
                                              body: JSON.stringify({ id: p.wave!.id }),
                                            }).then(() => setAttackWaves(prev => prev.filter(w => w.id !== p.wave!.id)))
                                          }}
                                          className="text-[10px] font-normal text-slate-400 hover:text-red-500 transition-colors"
                                        >
                                          {t('auto_attack_cancel')}
                                        </button>
                                      </p>
                                      {p.wave!.skippedReason && (
                                        <p className="text-[10px] text-slate-400 italic mb-1">{t('auto_attack_skipped_reason', { r: p.wave!.skippedReason })}</p>
                                      )}
                                      {p.wave!.wavePlans.map(wv => {
                                        const wColor: Record<string, string> = {
                                          PENDING: 'text-slate-500', FLEET_DISPATCHED: 'text-blue-600',
                                          ARMY_DISPATCHED: 'text-indigo-600', DONE: 'text-emerald-600', FAILED: 'text-red-600',
                                        }
                                        return (
                                          <div key={wv.waveNum} className={`text-[11px] mb-1.5 ${wColor[wv.status] || 'text-slate-500'}`}>
                                            <span className="font-medium">{t('auto_attack_wave_num', { n: String(wv.waveNum) })}</span>
                                            {' — '}{wv.originCityName}
                                            {' · '}{t('auto_attack_transporters', { n: String(wv.transporters) })}
                                            {wv.armyDispatchAfter && (
                                              <span className="text-slate-400 ml-1">
                                                ({t('auto_attack_army_dispatch')}: {new Date(wv.armyDispatchAfter * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })})
                                              </span>
                                            )}
                                          </div>
                                        )
                                      })}
                                    </>
                                  )
                                })()}
                              </div>
                            )}

                            {/* Manual attack button */}
                            <div className="flex justify-end pt-1">
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
    </div>
  )
}

// ── IlhasTab ──────────────────────────────────────────────────────────────────

function useResourceLabels(): string[] {
  const t = useT()
  return ['', t('res_wine'), t('res_marble'), t('res_crystal'), t('res_sulfur')]
}

type IslandSortKey = 'freeSlots' | 'wood' | 'luxury' | 'distance'

interface IlhasTabProps {
  scanData: WorldScanData | null
  loading: boolean
  error: string | null
  onForceRefresh: () => void
  onSelectIsland?: (preset: { resType: 'wood' | 'marble', level: number }) => void
}

function IlhasTab({ scanData, loading, error, onForceRefresh, onSelectIsland }: IlhasTabProps) {
  const t    = useT()
  const RESOURCE_LABELS = useResourceLabels()
  const [filterDist,     setFilterDist]     = useState(0)
  const [filterFree,     setFilterFree]     = useState(true)
  const [filterOwn,      setFilterOwn]      = useState(false)
  const [filterResource, setFilterResource] = useState(0)
  const [sortKey,        setSortKey]        = useState<IslandSortKey>('freeSlots')
  const [sortAsc,        setSortAsc]        = useState(false)

  const islands = useMemo((): WorldScanIsland[] => {
    if (!scanData?.islands) return []
    let list = [...scanData.islands]
    if (filterFree)       list = list.filter(i => i.freeSlots > 0)
    if (!filterOwn)       list = list.filter(i => !i.hasOwnCity)
    if (filterResource)   list = list.filter(i => i.resourceType === filterResource)
    if (filterDist > 0)   list = list.filter(i => i.distance <= filterDist)

    list.sort((a, b) => {
      let va: number, vb: number
      if      (sortKey === 'freeSlots') { va = a.freeSlots;                       vb = b.freeSlots }
      else if (sortKey === 'wood')      { va = parseInt(a.woodLevel  || '0') || 0; vb = parseInt(b.woodLevel  || '0') || 0 }
      else if (sortKey === 'luxury')    { va = parseInt(a.luxuryLevel || '0') || 0; vb = parseInt(b.luxuryLevel || '0') || 0 }
      else                              { va = a.distance;                         vb = b.distance }
      if (va < vb) return sortAsc ? -1 : 1
      if (va > vb) return sortAsc ? 1 : -1
      return 0
    })
    return list
  }, [scanData, filterFree, filterOwn, filterResource, filterDist, sortKey, sortAsc])

  const handleSort = (key: IslandSortKey) => {
    if (sortKey === key) setSortAsc(a => !a)
    else { setSortKey(key); setSortAsc(false) }
  }

  const SortTh = ({ colKey, children }: { colKey: IslandSortKey; children: React.ReactNode }) => (
    <th
      className="px-3 py-3 font-semibold text-center whitespace-nowrap cursor-pointer select-none hover:bg-slate-700 transition-colors"
      onClick={() => handleSort(colKey)}
    >
      {children}{sortKey === colKey && <span className="ml-1 opacity-70">{sortAsc ? '↑' : '↓'}</span>}
    </th>
  )

  const handleExportCsv = () => {
    const header = [t('col_island'), 'Coord', t('col_resource'), t('col_forest'), 'Lux.', t('col_wonder'), 'Lv Wonder', t('col_free_slots'), 'Total Slots', 'Nearest city', t('col_dist')]
    const rows = [header, ...islands.map(i => [
      i.islandName, `(${i.x},${i.y})`,
      RESOURCE_LABELS[i.resourceType] || '—', i.woodLevel || '—', i.luxuryLevel || '—',
      i.wonder || '—', i.wonderLevel || '—', i.freeSlots, i.totalSlots,
      i.nearestOwnCity, i.distance,
    ])]
    exportCsv(`islands_${new Date().toISOString().slice(0, 10)}.csv`, rows)
  }

  if (loading) return <Card className="p-8 text-center text-slate-400 text-sm">{t('loading')}</Card>
  if (error || !scanData?.islands) return (
    <Card className="p-8 text-center">
      <p className="text-slate-500 text-sm mb-3">{error || t('islands_not_available')}</p>
      <button onClick={onForceRefresh} className="px-4 py-2 bg-orange-500 hover:bg-orange-600 text-white text-sm rounded-lg">
        {t('force_scan')}
      </button>
    </Card>
  )

  return (
    <div>
      <Card className="mb-4">
        <div className="px-5 py-3 flex flex-wrap items-center gap-3">
          <button
            onClick={() => setFilterFree(v => !v)}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors ${filterFree ? 'bg-indigo-600 text-white border-indigo-600' : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'}`}
          >
            <i className="fa-solid fa-circle-plus" /> {t('only_free_slots')}
          </button>
          <button
            onClick={() => setFilterOwn(v => !v)}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors ${filterOwn ? 'bg-indigo-600 text-white border-indigo-600' : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'}`}
          >
            <i className="fa-solid fa-flag" /> {t('include_own_islands')}
          </button>
          <div className="flex items-center gap-2">
            <label className="text-xs text-slate-500">{t('filter_resource')}</label>
            <select
              value={filterResource}
              onChange={e => setFilterResource(Number(e.target.value))}
              className="border border-slate-200 rounded-lg px-2 py-1.5 text-xs bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400"
            >
              <option value={0}>{t('all')}</option>
              {RESOURCE_LABELS.slice(1).map((l, i) => <option key={i + 1} value={i + 1}>{l}</option>)}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-slate-500 whitespace-nowrap">{t('max_dist')}</label>
            <select
              value={filterDist}
              onChange={e => setFilterDist(Number(e.target.value))}
              className="border border-slate-200 rounded-lg px-2 py-1.5 text-xs bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400"
            >
              {[5, 8, 10, 15, 20, 0].map(v => <option key={v} value={v}>{v === 0 ? t('all') : `≤ ${v}`}</option>)}
            </select>
          </div>
          <button
            onClick={handleExportCsv}
            className="ml-auto flex items-center gap-1.5 px-3 py-1.5 text-xs text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors"
          >
            <i className="fa-solid fa-download" /> CSV
          </button>
        </div>
      </Card>

      {islands.length === 0 ? (
        <Card className="p-8 text-center text-slate-400 text-sm">{t('no_islands_found')}</Card>
      ) : (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="bg-slate-800 text-white text-xs uppercase tracking-wide">
                  <th className="px-3 py-3 font-semibold text-left whitespace-nowrap">{t('col_island')}</th>
                  <th className="px-3 py-3 font-semibold text-center whitespace-nowrap">{t('col_resource')}</th>
                  <SortTh colKey="wood">{t('col_forest')}</SortTh>
                  <SortTh colKey="luxury">{t('col_lux_level')}</SortTh>
                  <th className="px-3 py-3 font-semibold text-center whitespace-nowrap">{t('col_wonder')}</th>
                  <SortTh colKey="freeSlots">{t('col_free_slots')}</SortTh>
                  <SortTh colKey="distance">{t('col_dist')}</SortTh>
                  {onSelectIsland && <th className="px-3 py-3 font-semibold text-center whitespace-nowrap" />}
                </tr>
              </thead>
              <tbody>
                {islands.map((isl, idx) => (
                  <tr
                    key={isl.islandId}
                    className={`border-b border-slate-100 hover:bg-slate-50 transition-colors ${idx % 2 ? 'bg-slate-50/40' : ''}`}
                  >
                    <Td className="font-medium text-slate-800">
                      {isl.islandName}
                      <span className="text-slate-400 text-xs ml-1">({isl.x},{isl.y})</span>
                      {isl.hasOwnCity && (
                        <span className="ml-1.5 text-[10px] bg-indigo-100 text-indigo-600 px-1.5 py-0.5 rounded-full font-medium">
                          {t('own_city_badge')}
                        </span>
                      )}
                    </Td>
                    <Td className="text-center">
                      {isl.resourceType > 0 && (
                        <span className={`flex items-center justify-center gap-1 text-xs font-medium ${RESOURCE_COLORS[isl.resourceType]}`}>
                          <i className={`fa-solid ${RESOURCE_ICONS[isl.resourceType]}`} />
                          {RESOURCE_LABELS[isl.resourceType]}
                        </span>
                      )}
                    </Td>
                    <Td className="text-center font-mono text-slate-700">{isl.woodLevel || '—'}</Td>
                    <Td className="text-center font-mono text-slate-700">{isl.luxuryLevel || '—'}</Td>
                    <Td className="text-center text-slate-600 text-xs">
                      {isl.wonder
                        ? <span>{isl.wonder}{isl.wonderLevel ? <span className="text-slate-400 ml-1">Lv {isl.wonderLevel}</span> : null}</span>
                        : <span className="text-slate-300">—</span>}
                    </Td>
                    <Td className="text-center">
                      <span className={`font-bold text-sm ${isl.freeSlots > 0 ? 'text-emerald-600' : 'text-slate-400'}`}>
                        {isl.freeSlots}
                      </span>
                      <span className="text-slate-400 text-xs">/{isl.totalSlots}</span>
                    </Td>
                    <Td className="text-center">
                      <span className="font-mono text-slate-700 text-sm font-semibold">{isl.distance}</span>
                      <br /><span className="text-slate-400 text-xs">{isl.nearestOwnCity}</span>
                    </Td>
                    {onSelectIsland && (
                      <Td className="text-center">
                        <button
                          onClick={() => {
                            const resType = isl.resourceType === 2 ? 'marble' : 'wood'
                            const level = parseInt(isl.resourceType === 2 ? (isl.luxuryLevel || '1') : (isl.woodLevel || '1')) || 1
                            onSelectIsland({ resType, level })
                          }}
                          className="flex items-center gap-1 px-2 py-1 text-[11px] font-medium rounded bg-indigo-50 text-indigo-600 hover:bg-indigo-100 border border-indigo-200 transition-colors whitespace-nowrap"
                          title={t('use_in_calc')}
                        >
                          <i className="fa-solid fa-calculator text-[10px]" />
                          {t('use_in_calc')}
                        </button>
                      </Td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="px-5 py-3 border-t border-slate-100 text-xs text-slate-400">
            {islands.length !== 1 ? t('island_count_plural', { n: islands.length }) : t('island_count_single', { n: islands.length })}
          </div>
        </Card>
      )}
    </div>
  )
}

// ── MundoPage ─────────────────────────────────────────────────────────────────

export function MundoPage({ onSelectIsland }: { onSelectIsland?: (preset: { resType: 'wood' | 'marble', level: number }) => void }) {
  const t    = useT()
  const lang = useLang()
  const [tab,        setTab]        = useState('inactivos')
  const [scanData,   setScanData]   = useState<WorldScanData | null>(null)
  const [scanStatus, setScanStatus] = useState<ScanStatus | null>(null)
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState<string | null>(null)
  const [ownCities,       setOwnCities]       = useState<OwnCity[]>([])
  const [spyCounts,       setSpyCounts]       = useState<Record<string, CitySpyCounts>>({})
  const [spyOriginCityId, setSpyOriginCityId] = useState<string>(() => loadSpyDefaults().originCityId)
  const [worldScanEnabled,     setWorldScanEnabled]     = useState(true)
  const [spyProcessingEnabled, setSpyProcessingEnabled] = useState(true)

  useEffect(() => {
    fetch('/api/own-cities').then(r => r.json()).then((d: OwnCity[]) => {
      if (Array.isArray(d)) {
        setOwnCities(d)
        setSpyOriginCityId(prev => prev || (d.length > 0 ? String(d[0].cityId) : ''))
      }
    }).catch(() => {})
    fetch('/api/espionage/spy-counts').then(r => r.json()).then(d => {
      if (d.counts) {
        const counts: Record<string, CitySpyCounts> = {}
        for (const [id, val] of Object.entries(d.counts)) {
          const v = val as Record<string, number | null>
          counts[id] = { available: v.available ?? null, inDefense: v.inDefense ?? null, inTraining: v.inTraining ?? null, deployed: v.deployed ?? null }
        }
        setSpyCounts(counts)
      }
    }).catch(() => {})
    fetch('/api/world-scan/settings').then(r => r.json())
      .then(d => { if (d.enabled !== undefined) setWorldScanEnabled(d.enabled) }).catch(() => {})
    fetch('/api/espionage/settings').then(r => r.json())
      .then(d => { if (d.processingEnabled !== undefined) setSpyProcessingEnabled(d.processingEnabled) }).catch(() => {})
  }, [])

  const handleSpyCityChange = useCallback((cityId: string) => {
    setSpyOriginCityId(cityId)
    saveSpyDefaults(cityId, loadSpyDefaults().numAgents)
  }, [])

  const handleWorldScanToggle = useCallback(() => {
    const next = !worldScanEnabled
    setWorldScanEnabled(next)
    fetch('/api/world-scan/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: next }),
    }).catch(() => setWorldScanEnabled(!next))
  }, [worldScanEnabled])

  const handleSpyProcessingToggle = useCallback(() => {
    const next = !spyProcessingEnabled
    setSpyProcessingEnabled(next)
    fetch('/api/espionage/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ processingEnabled: next }),
    }).catch(() => setSpyProcessingEnabled(!next))
  }, [spyProcessingEnabled])

  const fetchScan = useCallback(() => {
    fetch('/api/world-scan')
      .then(r => r.ok ? r.json() : r.json().then((e: { error: string }) => Promise.reject(e.error)))
      .then((d: WorldScanData) => {
        setScanData(d)
        setLoading(false)
      })
      .catch((e: unknown) => {
        setError(typeof e === 'string' ? e : 'Error loading scan data')
        setLoading(false)
      })
  }, [])

  const fetchStatus = useCallback(() => {
    fetch('/api/world-scan/status').then(r => r.json()).then(setScanStatus).catch(() => {})
  }, [])

  useEffect(() => { fetchScan(); fetchStatus() }, [fetchScan, fetchStatus])

  useEffect(() => {
    if (scanStatus?.status !== 'running') return
    const timer = setInterval(() => {
      fetchStatus()
      if (scanStatus?.status !== 'running') fetchScan()
    }, 5000)
    return () => clearInterval(timer)
  }, [scanStatus?.status, fetchScan, fetchStatus])

  const handleForceRefresh = () => {
    fetch('/api/world-scan/refresh', { method: 'POST' })
      .then(() => alert(t('scan_scheduled_msg')))
  }

  const isRunning      = scanStatus?.status === 'running'
  const lastUpdated    = scanData?.lastUpdated ? new Date(scanData.lastUpdated * 1000).toLocaleString(getLocale(lang)) : null
  const nextScan       = scanData?.lastUpdated ? new Date((scanData.lastUpdated + 7 * 24 * 3600) * 1000).toLocaleDateString(getLocale(lang)) : null
  const inactiveCount  = (scanData?.players || []).filter(p => p.state === 'inactive').length
  const newCount       = (scanData?.players || []).filter(p => p.state === 'inactive' && p.isNew).length

  const TABS = [
    { key: 'inactivos', label: t('tab_inactive'), icon: 'fa-user-slash' },
    { key: 'ilhas',     label: t('tab_islands'),  icon: 'fa-map'        },
  ]

  return (
    <div>
      <PageHeader icon="fa-earth-europe" title={t('world_title')} />

      <Card className="mb-4">
        <div className="px-5 py-4 flex flex-wrap items-start gap-4">
          <div className="flex-1 min-w-0 space-y-2">
            {lastUpdated ? (
              <p className="text-sm text-slate-600">
                <i className="fa-regular fa-clock mr-1.5 text-slate-400" />
                {t('last_scan_label')} <span className="font-medium text-slate-800">{lastUpdated}</span>
                {nextScan && <span className="ml-3 text-slate-400 text-xs">{t('next_scan_label')} {nextScan}</span>}
              </p>
            ) : (
              <p className="text-sm text-slate-500">{t('no_scan_yet')}</p>
            )}
            {scanData && (
              <p className="text-xs text-slate-400">
                {t('scan_radius')}: {scanData.scanRadius}
                {' · '}{t('inactive_label')}: <span className="font-semibold text-slate-600">{inactiveCount}</span>
                {newCount > 0 && <span className="ml-1.5 text-emerald-600 font-semibold">{t('new_count_world', { n: newCount })}</span>}
                {scanData.islands && <span>{' · '}{t('islands_count_world')}: <span className="font-semibold text-slate-600">{scanData.islands.length}</span></span>}
              </p>
            )}
            {isRunning && (
              <div>
                <p className="text-xs text-indigo-600 mb-1 flex items-center gap-1.5">
                  <span className="w-3 h-3 rounded-full border-2 border-indigo-300 border-t-indigo-600 animate-spin inline-block" />
                  {scanStatus!.message}
                </p>
                {scanStatus!.total > 0 && (
                  <div className="w-full max-w-xs h-1.5 bg-slate-200 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-indigo-500 rounded-full transition-all"
                      style={{ width: `${Math.round((scanStatus!.progress / scanStatus!.total) * 100)}%` }}
                    />
                  </div>
                )}
              </div>
            )}
            {/* Enable/disable toggles */}
            <div className="flex gap-2 pt-1">
              <button
                onClick={handleWorldScanToggle}
                className={`flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-lg border transition-colors ${
                  worldScanEnabled
                    ? 'bg-indigo-50 text-indigo-700 border-indigo-200 hover:bg-indigo-100'
                    : 'bg-slate-100 text-slate-500 border-slate-200 hover:bg-slate-200'
                }`}
              >
                <i className={`fa-solid ${worldScanEnabled ? 'fa-earth-europe' : 'fa-earth-europe opacity-40'} text-[10px]`} />
                {t('world_scan_toggle')}
                <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-bold ${worldScanEnabled ? 'bg-indigo-200 text-indigo-700' : 'bg-slate-200 text-slate-500'}`}>
                  {worldScanEnabled ? 'ON' : 'OFF'}
                </span>
              </button>
              <button
                onClick={handleSpyProcessingToggle}
                className={`flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-lg border transition-colors ${
                  spyProcessingEnabled
                    ? 'bg-indigo-50 text-indigo-700 border-indigo-200 hover:bg-indigo-100'
                    : 'bg-slate-100 text-slate-500 border-slate-200 hover:bg-slate-200'
                }`}
              >
                <i className={`fa-solid fa-user-secret text-[10px] ${spyProcessingEnabled ? '' : 'opacity-40'}`} />
                {t('spy_processing_toggle')}
                <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-bold ${spyProcessingEnabled ? 'bg-indigo-200 text-indigo-700' : 'bg-slate-200 text-slate-500'}`}>
                  {spyProcessingEnabled ? 'ON' : 'OFF'}
                </span>
              </button>
            </div>
          </div>
          <button
            onClick={handleForceRefresh}
            disabled={isRunning}
            className="flex items-center gap-2 px-4 py-2 bg-orange-500 hover:bg-orange-600 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors shrink-0"
          >
            <i className="fa-solid fa-rotate" />
            {isRunning ? t('scanning') : t('force_scan')}
          </button>
        </div>
      </Card>

      <div className="flex items-center gap-3 mb-4">
        <div className="flex gap-1 bg-white border border-slate-200 rounded-xl p-1 shadow-sm">
          {TABS.map(tb => (
            <button
              key={tb.key}
              onClick={() => setTab(tb.key)}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                tab === tb.key ? 'bg-indigo-600 text-white shadow' : 'text-slate-500 hover:text-slate-700 hover:bg-slate-100'
              }`}
            >
              <i className={`fa-solid ${tb.icon} text-xs`} />{tb.label}
            </button>
          ))}
        </div>
        {ownCities.length > 0 && (
          <div className="flex items-center gap-1.5 bg-white border border-slate-200 rounded-xl px-3 py-1.5 shadow-sm">
            <i className="fa-solid fa-user-secret text-slate-400 text-xs" />
            <select
              value={spyOriginCityId}
              onChange={e => handleSpyCityChange(e.target.value)}
              className="text-sm border-none bg-transparent focus:outline-none text-slate-700 cursor-pointer"
            >
              {ownCities.map(c => {
                const id = String(c.cityId)
                const sc = spyCounts[id]
                const label = sc?.inDefense != null ? `${c.name} (${sc.inDefense})` : c.name
                return <option key={id} value={id}>{label}</option>
              })}
            </select>
          </div>
        )}
      </div>

      {tab === 'inactivos' && (
        <InactivosTab
          scanData={scanData}
          loading={loading}
          error={error}
          onForceRefresh={handleForceRefresh}
          ownCities={ownCities}
          spyCounts={spyCounts}
          spyOriginCityId={spyOriginCityId}
        />
      )}
      {tab === 'ilhas' && (
        <IlhasTab
          scanData={scanData}
          loading={loading}
          error={error}
          onForceRefresh={handleForceRefresh}
          onSelectIsland={onSelectIsland}
        />
      )}
    </div>
  )
}
