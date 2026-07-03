import React, { useState, useMemo } from 'react'
import { useT } from '../../i18n'
import { exportCsv } from '../../utils'
import { RESOURCE_ICONS, RESOURCE_COLORS } from '../../constants'
import { Card } from '../ui/Card'
import { Td } from '../ui/TableCells'
import type { WorldScanData, WorldScanIsland } from '../../types'

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

export function IlhasTab({ scanData, loading, error, onForceRefresh, onSelectIsland }: IlhasTabProps) {
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

