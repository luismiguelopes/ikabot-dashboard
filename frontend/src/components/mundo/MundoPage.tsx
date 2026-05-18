import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { useT, useLang, getLocale } from '../../i18n'
import { fmtScore, exportCsv } from '../../utils'
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

interface MarkConfigEntry {
  label: string
  bg: string
  text: string
  ring: string
}

function useMarkConfig(): Record<string, MarkConfigEntry> {
  const t = useT()
  return {
    novo:    { label: t('mark_novo'),    bg: 'bg-blue-100',   text: 'text-blue-700',   ring: 'ring-blue-300'   },
    alvo:    { label: t('mark_alvo'),    bg: 'bg-orange-100', text: 'text-orange-700', ring: 'ring-orange-300' },
    visto:   { label: t('mark_visto'),   bg: 'bg-slate-100',  text: 'text-slate-500',  ring: 'ring-slate-300'  },
    ignorar: { label: t('mark_ignorar'), bg: 'bg-slate-50',   text: 'text-slate-400',  ring: 'ring-slate-200'  },
  }
}

function useResourceLabels(): string[] {
  const t = useT()
  return ['', t('res_wine'), t('res_marble'), t('res_crystal'), t('res_sulfur')]
}

function MarkBadge({ status }: { status: string }) {
  const MARK_CONFIG = useMarkConfig()
  const cfg = MARK_CONFIG[status] || MARK_CONFIG.novo
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${cfg.bg} ${cfg.text}`}>
      {cfg.label}
    </span>
  )
}

function MarkSelect({ markKey, current, onChange }: {
  markKey: string
  current: string
  onChange: (key: string, status: string) => void
}) {
  const MARK_CONFIG = useMarkConfig()
  const cfg = MARK_CONFIG[current] || MARK_CONFIG.novo
  return (
    <select
      value={current}
      onChange={e => onChange(markKey, e.target.value)}
      className={`text-xs rounded-full px-2 py-0.5 border font-medium cursor-pointer focus:outline-none ${cfg.bg} ${cfg.text} border-transparent`}
    >
      {Object.entries(MARK_CONFIG).map(([k, v]) => (
        <option key={k} value={k}>{v.label}</option>
      ))}
    </select>
  )
}

function StatePill({ state }: { state: string }) {
  const t = useT()
  if (state === 'inactive') return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700">
      <span className="w-1.5 h-1.5 rounded-full bg-red-500 inline-block" /> {t('state_inactive')}
    </span>
  )
  if (state === 'vacation') return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-700">
      <span className="w-1.5 h-1.5 rounded-full bg-yellow-500 inline-block" /> {t('state_vacation')}
    </span>
  )
  return <span className="text-slate-400 text-xs">{state}</span>
}

function parseScore(s: string | undefined | null): number {
  if (!s) return 0
  return parseInt(String(s).replace(/[,.\s ]/g, ''), 10) || 0
}

type PlayerSortKey = 'distance' | 'army' | 'building' | 'player'
type IslandSortKey = 'freeSlots' | 'wood' | 'luxury' | 'distance'

interface PlayerWithMark extends WorldScanPlayer {
  markKey: string
  mark: string
}

interface InactivosTabProps {
  scanData: WorldScanData | null
  scanStatus: ScanStatus | null
  loading: boolean
  error: string | null
  marks: Record<string, string>
  setMarks: React.Dispatch<React.SetStateAction<Record<string, string>>>
  onForceRefresh: () => void
  onRefreshScan: () => void
  ownCities: OwnCity[]
  spyCounts: Record<string, CitySpyCounts>
  spyOriginCityId: string
}

function parseMarkKey(markKey: string): { playerId: string; islandX: string; islandY: string } {
  const parts   = markKey.split('_')
  const islandY = parts.pop()!
  const islandX = parts.pop()!
  const playerId = parts.join('_')
  return { playerId, islandX, islandY }
}

function InactivosTab({ scanData, loading, error, marks, setMarks, onForceRefresh, onRefreshScan, ownCities, spyCounts, spyOriginCityId }: InactivosTabProps) {
  const t    = useT()
  const lang = useLang()
  const [filterDist, setFilterDist] = useState(20)
  const [filterMark, setFilterMark] = useState('excl_ignorar')
  const [filterNew,  setFilterNew]  = useState(false)
  const [search,     setSearch]     = useState('')
  const [sortKey,    setSortKey]    = useState<PlayerSortKey>('distance')
  const [sortAsc,    setSortAsc]    = useState(true)
  const [expandedKey,  setExpandedKey]  = useState<string | null>(null)
  const [noteInputs,   setNoteInputs]   = useState<Record<string, string>>({})
  const [actionInputs, setActionInputs] = useState<Record<string, string>>({})
  const [spyTarget,      setSpyTarget]      = useState<PlayerWithMark | null>(null)
  const [dispatchedOk,   setDispatchedOk]   = useState<string | null>(null)
  const [dispatchedKeys, setDispatchedKeys] = useState<Set<string>>(new Set())
  const [missions,       setMissions]       = useState<SpyMission[]>([])

  useEffect(() => {
    const load = () => fetch('/api/espionage/missions').then(r => r.json())
      .then((d: { missions: SpyMission[] }) => { if (d.missions) setMissions(d.missions) }).catch(() => {})
    load()
    const t = setInterval(load, 60000)
    return () => clearInterval(t)
  }, [])

  const latestMissionByKey = useMemo(() => {
    const map: Record<string, SpyMission> = {}
    for (const m of missions) {
      const key = `${m.targetPlayerName}_${m.islandX}_${m.islandY}`
      if (!map[key] || m.dispatchedAt > map[key].dispatchedAt) map[key] = m
    }
    return map
  }, [missions])

  const handleMark = useCallback((markKey: string, status: string) => {
    setMarks(prev => ({ ...prev, [markKey]: status }))
    const { playerId, islandX, islandY } = parseMarkKey(markKey)
    fetch('/api/world-scan/mark', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ playerId, islandX, islandY, status }),
    }).catch(() => {})
  }, [setMarks])

  const handleToggleExpand = useCallback((markKey: string, currentNote: string) => {
    setExpandedKey(prev => {
      if (prev === markKey) return null
      setNoteInputs(n => ({ ...n, [markKey]: n[markKey] ?? currentNote ?? '' }))
      return markKey
    })
  }, [])

  const handleSaveNote = useCallback((markKey: string, currentStatus: string) => {
    const { playerId, islandX, islandY } = parseMarkKey(markKey)
    const note = noteInputs[markKey] ?? ''
    fetch('/api/world-scan/mark', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ playerId, islandX, islandY, status: currentStatus, note }),
    }).then(() => onRefreshScan()).catch(() => {})
  }, [noteInputs, onRefreshScan])

  const handleAddAction = useCallback((markKey: string) => {
    const text = (actionInputs[markKey] || '').trim()
    if (!text) return
    const { playerId, islandX, islandY } = parseMarkKey(markKey)
    fetch('/api/world-scan/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ playerId, islandX, islandY, text }),
    }).then(() => {
      setActionInputs(prev => ({ ...prev, [markKey]: '' }))
      onRefreshScan()
    }).catch(() => {})
  }, [actionInputs, onRefreshScan])

  const players = useMemo((): PlayerWithMark[] => {
    if (!scanData?.players) return []
    let list = scanData.players
      .filter(p => p.state === 'inactive')
      .map(p => {
        const markKey = `${p.playerId}_${p.islandX}_${p.islandY}`
        return { ...p, markKey, mark: marks[markKey] || p.mark || 'novo' }
      })

    if (filterNew) list = list.filter(p => p.isNew)
    if (filterMark === 'excl_ignorar')      list = list.filter(p => p.mark !== 'ignorar')
    else if (filterMark !== 'all')          list = list.filter(p => p.mark === filterMark)
    if (filterDist > 0)  list = list.filter(p => p.distance <= filterDist)
    if (search.trim())   list = list.filter(p => (p.playerName || '').toLowerCase().includes(search.trim().toLowerCase()))

    list.sort((a, b) => {
      let va: number | string, vb: number | string
      if      (sortKey === 'distance') { va = a.distance; vb = b.distance }
      else if (sortKey === 'army')     { va = parseScore(a.scores?.army); vb = parseScore(b.scores?.army) }
      else if (sortKey === 'building') { va = parseScore(a.scores?.building); vb = parseScore(b.scores?.building) }
      else                             { va = a.playerName.toLowerCase(); vb = b.playerName.toLowerCase() }
      if (va < vb) return sortAsc ? -1 : 1
      if (va > vb) return sortAsc ? 1 : -1
      return 0
    })
    return list
  }, [scanData, marks, filterMark, filterDist, filterNew, search, sortKey, sortAsc])

  const newCount = useMemo(() =>
    (scanData?.players || []).filter(p => p.state === 'inactive' && p.isNew).length, [scanData])

  const handleSort = (key: PlayerSortKey) => {
    if (sortKey === key) setSortAsc(a => !a)
    else { setSortKey(key); setSortAsc(true) }
  }

  const SortTh = ({ colKey, children, align = 'text-center' }: {
    colKey: PlayerSortKey; children: React.ReactNode; align?: string
  }) => (
    <th
      className={`px-3 py-3 font-semibold ${align} whitespace-nowrap cursor-pointer select-none hover:bg-slate-700 transition-colors`}
      onClick={() => handleSort(colKey)}
    >
      {children}
      {sortKey === colKey && <span className="ml-1 opacity-70">{sortAsc ? '↑' : '↓'}</span>}
    </th>
  )

  const handleExportCsv = () => {
    const header = [t('col_player'), t('col_alliance'), 'New?', t('col_island'), 'Coord', 'Nearest city', t('col_dist'),
                    'Military score', 'Building score', 'Rank', t('col_mark')]
    const rows = [header, ...players.map(p => [
      p.playerName, p.allyTag || '—', p.isNew ? 'Yes' : 'No',
      p.islandName, `(${p.islandX},${p.islandY})`,
      p.nearestOwnCity, p.distance,
      fmtScore(p.scores?.army, lang), fmtScore(p.scores?.building, lang), p.scores?.rank || '—',
      p.mark,
    ])]
    exportCsv(`inactive_${new Date().toISOString().slice(0, 10)}.csv`, rows)
  }

  if (loading) return <Card className="p-8 text-center text-slate-400 text-sm">{t('loading')}</Card>
  if (error) return (
    <Card className="p-8 text-center">
      <p className="text-slate-500 text-sm mb-3">{error}</p>
      <button onClick={onForceRefresh} className="px-4 py-2 bg-orange-500 hover:bg-orange-600 text-white text-sm rounded-lg">
        {t('force_first_scan')}
      </button>
    </Card>
  )

  return (
    <div>
      <Card className="mb-4">
        <div className="px-5 py-3 flex flex-wrap items-center gap-3">
          <button
            onClick={() => setFilterNew(v => !v)}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors ${
              filterNew
                ? 'bg-emerald-500 text-white border-emerald-500'
                : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
            }`}
          >
            <i className="fa-solid fa-star" />
            {t('new_this_week')}
            {newCount > 0 && (
              <span className={`ml-1 px-1.5 rounded-full text-[10px] font-bold ${filterNew ? 'bg-emerald-400 text-white' : 'bg-emerald-100 text-emerald-700'}`}>
                {newCount}
              </span>
            )}
          </button>
          <div className="flex items-center gap-2">
            <label className="text-xs text-slate-500 whitespace-nowrap">{t('max_dist')}</label>
            <select
              value={filterDist}
              onChange={e => setFilterDist(Number(e.target.value))}
              className="border border-slate-200 rounded-lg px-2 py-1.5 text-xs bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400"
            >
              {[5, 8, 10, 15, 20, 30, 0].map(v => <option key={v} value={v}>{v === 0 ? t('all') : `≤ ${v}`}</option>)}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-slate-500">{t('filter_mark')}</label>
            <select
              value={filterMark}
              onChange={e => setFilterMark(e.target.value)}
              className="border border-slate-200 rounded-lg px-2 py-1.5 text-xs bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400"
            >
              <option value="excl_ignorar">{t('excl_ignored')}</option>
              <option value="all">{t('all')}</option>
              <option value="novo">{t('only_new')}</option>
              <option value="alvo">{t('only_target')}</option>
              <option value="visto">{t('only_seen')}</option>
            </select>
          </div>
          <input
            type="text"
            placeholder={t('search_player')}
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="border border-slate-200 rounded-lg px-3 py-1.5 text-xs bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400 flex-1 min-w-[160px]"
          />
          <button
            onClick={handleExportCsv}
            className="ml-auto flex items-center gap-1.5 px-3 py-1.5 text-xs text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors"
          >
            <i className="fa-solid fa-download" /> CSV
          </button>
        </div>
      </Card>

      {players.length === 0 ? (
        <Card className="p-8 text-center text-slate-400 text-sm">{t('no_players_found')}</Card>
      ) : (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="bg-slate-800 text-white text-xs uppercase tracking-wide">
                  <SortTh colKey="player" align="text-left">{t('col_player')}</SortTh>
                  <th className="px-3 py-3 font-semibold text-center whitespace-nowrap">{t('col_alliance')}</th>
                  <th className="px-3 py-3 font-semibold text-center whitespace-nowrap">{t('col_island')}</th>
                  <SortTh colKey="distance">{t('col_dist')}</SortTh>
                  <SortTh colKey="army">{t('col_military')}</SortTh>
                  <SortTh colKey="building">{t('col_buildings_score')}</SortTh>
                  <th className="px-3 py-3 font-semibold text-center whitespace-nowrap">{t('col_mark')}</th>
                </tr>
              </thead>
              <tbody>
                {players.map((p, idx) => {
                  const isExpanded = expandedKey === p.markKey
                  const actions = p.markActions || []
                  return (
                  <React.Fragment key={p.markKey}>
                  <tr
                    className={`border-b ${isExpanded ? 'border-indigo-200 bg-indigo-50/30' : 'border-slate-100'} hover:bg-slate-50 transition-colors ${p.mark === 'ignorar' ? 'opacity-40' : ''} ${!isExpanded && idx % 2 ? 'bg-slate-50/40' : ''}`}
                  >
                    <Td className="font-medium text-slate-800">
                      <div className="flex items-center gap-1.5">
                        <button
                          onClick={() => handleToggleExpand(p.markKey, p.markNote || '')}
                          className={`w-5 h-5 rounded flex items-center justify-center text-[10px] transition-colors ${isExpanded ? 'bg-indigo-500 text-white' : 'bg-slate-100 text-slate-400 hover:bg-indigo-100 hover:text-indigo-500'}`}
                          title={t('action_log_title')}
                        >
                          <i className={`fa-solid ${isExpanded ? 'fa-chevron-up' : 'fa-chevron-down'}`} />
                        </button>
                        {p.playerName}
                        {p.isNew && (
                          <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full text-[10px] font-bold bg-emerald-100 text-emerald-700">
                            <i className="fa-solid fa-star text-[8px]" /> {t('new_badge')}
                          </span>
                        )}
                        {actions.length > 0 && (
                          <span className="text-[10px] font-semibold text-indigo-500 bg-indigo-50 px-1.5 rounded-full border border-indigo-200">{actions.length}</span>
                        )}
                      </div>
                    </Td>
                    <Td className="text-center">
                      {p.allyTag
                        ? <span className="px-1.5 py-0.5 bg-indigo-50 text-indigo-700 rounded text-xs font-mono">{p.allyTag}</span>
                        : <span className="text-slate-300">—</span>}
                    </Td>
                    <Td className="text-center">
                      <span className="text-slate-700 font-medium">{p.islandName}</span>
                      <span className="text-slate-400 text-xs ml-1">({p.islandX},{p.islandY})</span>
                      <br /><span className="text-slate-400 text-xs">{p.cityName}</span>
                    </Td>
                    <Td className="text-center">
                      <span className="font-mono text-slate-700 text-sm font-semibold">{p.distance}</span>
                      <br /><span className="text-slate-400 text-xs">{p.nearestOwnCity}</span>
                    </Td>
                    <Td className="text-center font-mono text-slate-700">
                      {fmtScore(p.scores?.army, lang)}
                      {p.scores?.rank && <div className="text-slate-400 text-[10px]">#{p.scores.rank}</div>}
                    </Td>
                    <Td className="text-center font-mono text-slate-600 text-xs">
                      {fmtScore(p.scores?.building, lang)}
                    </Td>
                    <Td className="text-center">
                      {(() => {
                        const mKey = `${p.playerName}_${p.islandX}_${p.islandY}`
                        const mission = latestMissionByKey[mKey]
                        const isActive = mission && ['TRAVELING','WAITING_AT_CITY','EXECUTING','EXECUTING_WAREHOUSE','WAITING_FOR_GARRISON','EXECUTING_GARRISON'].includes(mission.state)
                        const isDone   = mission?.state === 'DONE'
                        const isFailed = mission?.state === 'FAILED'
                        const spyTitle = !p.cityId || !p.islandId ? t('spy_no_city_id')
                          : isDone   ? t('spy_done')
                          : isFailed ? t('spy_failed')
                          : isActive ? (
                              mission.state === 'TRAVELING' ? t('spy_traveling')
                            : mission.state === 'WAITING_AT_CITY' ? t('spy_waiting')
                            : mission.state === 'WAITING_FOR_GARRISON' ? t('spy_waiting_garrison')
                            : mission.state === 'EXECUTING_GARRISON' ? t('spy_executing_garrison')
                            : t('spy_executing')
                          )
                          : t('spy_send_btn')
                        return (
                          <div className="flex items-center justify-center gap-1">
                            <MarkSelect markKey={p.markKey} current={p.mark} onChange={handleMark} />
                            <button
                              onClick={() => setSpyTarget(p)}
                              title={spyTitle}
                              className={`w-6 h-6 rounded flex items-center justify-center text-[11px] transition-colors ${
                                !p.cityId || !p.islandId
                                  ? 'bg-slate-50 text-slate-300 cursor-not-allowed'
                                  : isDone
                                    ? 'bg-emerald-100 text-emerald-700 hover:bg-emerald-200'
                                    : isFailed
                                      ? 'bg-red-100 text-red-600 hover:bg-red-200'
                                      : (isActive || dispatchedKeys.has(p.markKey))
                                        ? 'bg-amber-200 text-amber-700 hover:bg-amber-300'
                                        : 'bg-slate-100 text-slate-500 hover:bg-amber-100 hover:text-amber-700'
                              }`}
                              disabled={!p.cityId || !p.islandId}
                            >
                              <i className="fa-solid fa-user-secret" />
                            </button>
                            {isDone && mission.result && (
                              <button
                                onClick={() => handleToggleExpand(p.markKey, p.markNote ?? '')}
                                title={t('spy_report_title')}
                                className="w-5 h-5 rounded flex items-center justify-center text-[10px] bg-emerald-50 text-emerald-600 hover:bg-emerald-100 transition-colors"
                              >
                                <i className="fa-solid fa-file-lines" />
                              </button>
                            )}
                          </div>
                        )
                      })()}
                    </Td>
                  </tr>
                  {isExpanded && (
                    <tr className="bg-indigo-50/40 border-b border-indigo-200">
                      <td colSpan={7} className="px-5 py-3">
                        <div className="flex flex-col gap-3">
                          {(() => {
                            const mKey = `${p.playerName}_${p.islandX}_${p.islandY}`
                            const mission = latestMissionByKey[mKey]
                            if (!mission || mission.state !== 'DONE' || !mission.result) return null
                            const res = mission.result.resources
                            const RES_LABELS: Record<string, string> = { wood: 'Madeira', wine: 'Vinho', marble: 'Mármore', crystal: 'Cristal', sulfur: 'Enxofre' }
                            return (
                              <div className="flex flex-col gap-2">
                                <div className="bg-white rounded-lg border border-emerald-200 px-4 py-3">
                                  <p className="text-xs font-semibold text-emerald-700 mb-2 flex items-center gap-1.5">
                                    <i className="fa-solid fa-warehouse" /> {t('spy_report_resources')} — {mission.result.targetCityName || p.cityName}
                                  </p>
                                  <p className="text-[10px] text-emerald-600 mb-2">
                                    {mission.result.success ? t('spy_report_success') : t('spy_report_failed')}
                                    {mission.result.reportedAt && <span className="ml-2 text-slate-400">{new Date(mission.result.reportedAt * 1000).toLocaleString()}</span>}
                                  </p>
                                  {res && Object.keys(res).length > 0 ? (
                                    <div className="grid grid-cols-5 gap-1">
                                      {(['wood','wine','marble','crystal','sulfur'] as const).map(k => (
                                        <div key={k} className="text-center">
                                          <div className="text-[10px] text-slate-500">{RES_LABELS[k]}</div>
                                          <div className="text-xs font-semibold text-slate-700">{res[k]?.toLocaleString() ?? '—'}</div>
                                        </div>
                                      ))}
                                    </div>
                                  ) : (
                                    <p className="text-xs text-slate-400 italic">{t('spy_no_resources')}</p>
                                  )}
                                </div>
                                {mission.garrisonResult && !mission.garrisonResult.error && (
                                  <div className="bg-white rounded-lg border border-amber-200 px-4 py-3">
                                    <p className="text-xs font-semibold text-amber-700 mb-2 flex items-center gap-1.5">
                                      <i className="fa-solid fa-shield-halved" /> {t('spy_garrison_title')} — {mission.garrisonResult.targetCityName || p.cityName}
                                    </p>
                                    {mission.garrisonResult.reportedAt && (
                                      <p className="text-[10px] text-slate-400 mb-2">{new Date(mission.garrisonResult.reportedAt * 1000).toLocaleString()}</p>
                                    )}
                                    {mission.garrisonResult.troops && Object.keys(mission.garrisonResult.troops).length > 0 ? (
                                      <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                                        {Object.entries(mission.garrisonResult.troops).map(([name, count]) => (
                                          <div key={name} className="flex justify-between text-xs">
                                            <span className="text-slate-600">{name}</span>
                                            <span className="font-semibold text-slate-800">{count.toLocaleString()}</span>
                                          </div>
                                        ))}
                                      </div>
                                    ) : (
                                      <p className="text-xs text-slate-400 italic">{t('spy_garrison_no_troops')}</p>
                                    )}
                                  </div>
                                )}
                                {mission.garrisonResult?.error && (
                                  <p className="text-xs text-slate-400 italic px-1">{mission.garrisonResult.error}</p>
                                )}
                              </div>
                            )
                          })()}
                          <p className="text-xs font-semibold text-indigo-600 uppercase tracking-wide">{t('action_log_title')}</p>
                          <div className="flex gap-2 items-start">
                            <textarea
                              value={noteInputs[p.markKey] ?? p.markNote ?? ''}
                              onChange={e => setNoteInputs(prev => ({ ...prev, [p.markKey]: e.target.value }))}
                              placeholder={t('action_log_note_lbl')}
                              rows={2}
                              className="flex-1 text-xs border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-400 resize-none bg-white"
                            />
                            <button
                              onClick={() => handleSaveNote(p.markKey, p.mark)}
                              className="px-3 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-medium rounded-lg transition-colors shrink-0"
                            >
                              {t('action_log_save')}
                            </button>
                          </div>
                          <div>
                            {actions.length === 0 ? (
                              <p className="text-xs text-slate-400 italic">{t('action_log_empty')}</p>
                            ) : (
                              <ul className="space-y-1 mb-2">
                                {actions.map((a, ai) => (
                                  <li key={ai} className="flex gap-2 text-xs">
                                    <span className="text-slate-400 shrink-0 font-mono">{new Date(a.ts * 1000).toLocaleDateString()}</span>
                                    <span className="text-slate-700">{a.text}</span>
                                  </li>
                                ))}
                              </ul>
                            )}
                            <div className="flex gap-2 mt-2">
                              <input
                                type="text"
                                value={actionInputs[p.markKey] || ''}
                                onChange={e => setActionInputs(prev => ({ ...prev, [p.markKey]: e.target.value }))}
                                onKeyDown={e => { if (e.key === 'Enter') handleAddAction(p.markKey) }}
                                placeholder={t('action_log_placeholder')}
                                className="flex-1 text-xs border border-slate-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-400 bg-white"
                              />
                              <button
                                onClick={() => handleAddAction(p.markKey)}
                                disabled={!(actionInputs[p.markKey] || '').trim()}
                                className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-40 text-white text-xs font-medium rounded-lg transition-colors shrink-0"
                              >
                                {t('action_log_add')}
                              </button>
                            </div>
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
            {newCount > 0 && <span className="ml-2 text-emerald-600 font-medium">{t('new_count_note', { n: newCount })}</span>}
          </div>
        </Card>
      )}

      {spyTarget && (
        <SpyModal
          player={spyTarget}
          ownCities={ownCities}
          spyCounts={spyCounts}
          originCityId={spyOriginCityId}
          onClose={() => setSpyTarget(null)}
          onDispatched={() => {
            setDispatchedOk(spyTarget.playerName)
            setDispatchedKeys(prev => new Set(prev).add(spyTarget.markKey))
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
    </div>
  )
}

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

export function MundoPage({ onSelectIsland }: { onSelectIsland?: (preset: { resType: 'wood' | 'marble', level: number }) => void }) {
  const t    = useT()
  const lang = useLang()
  const [tab,        setTab]        = useState('inactivos')
  const [scanData,   setScanData]   = useState<WorldScanData | null>(null)
  const [scanStatus, setScanStatus] = useState<ScanStatus | null>(null)
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState<string | null>(null)
  const [marks,      setMarks]      = useState<Record<string, string>>({})
  const [ownCities,      setOwnCities]      = useState<OwnCity[]>([])
  const [spyCounts,      setSpyCounts]      = useState<Record<string, CitySpyCounts>>({})
  const [spyOriginCityId, setSpyOriginCityId] = useState<string>(() => loadSpyDefaults().originCityId)

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
  }, [])

  const handleSpyCityChange = useCallback((cityId: string) => {
    setSpyOriginCityId(cityId)
    saveSpyDefaults(cityId, loadSpyDefaults().numAgents)
  }, [])

  const fetchScan = useCallback(() => {
    fetch('/api/world-scan')
      .then(r => r.ok ? r.json() : r.json().then((e: { error: string }) => Promise.reject(e.error)))
      .then((d: WorldScanData) => {
        setScanData(d)
        const m: Record<string, string> = {}
        ;(d.players || []).forEach(p => {
          const mk = `${p.playerId}_${p.islandX}_${p.islandY}`
          m[mk] = p.mark || 'novo'
        })
        setMarks(m)
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
        <div className="px-5 py-4 flex flex-wrap items-center gap-4">
          <div className="flex-1 min-w-0 space-y-1">
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
              <div className="mt-2">
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
          </div>
          <button
            onClick={handleForceRefresh}
            disabled={isRunning}
            className="flex items-center gap-2 px-4 py-2 bg-orange-500 hover:bg-orange-600 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
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
          scanStatus={scanStatus}
          loading={loading}
          error={error}
          marks={marks}
          setMarks={setMarks}
          onForceRefresh={handleForceRefresh}
          onRefreshScan={fetchScan}
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
