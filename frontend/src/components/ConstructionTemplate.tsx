import { useState, useMemo } from 'react'
import { useT } from '../i18n'
import { fmt } from '../utils'
import { Card } from './ui/Card'
import { Th, Td } from './ui/TableCells'
import type { ApiData, BuildingQueue, BuildingCostsData } from '../types'

const TEMPLATE_KEY = 'ikabot_construction_template'

function loadTemplate(): Record<string, number> {
  try { return JSON.parse(localStorage.getItem(TEMPLATE_KEY) || '{}') } catch { return {} }
}

function saveTemplate(t: Record<string, number>) {
  try { localStorage.setItem(TEMPLATE_KEY, JSON.stringify(t)) } catch {}
}

type RowStatus = 'add' | 'queued' | 'done' | 'error'

interface PreviewRow {
  city: string
  building: string
  currentLevel: number
  targetLevel: number
  status: RowStatus
}

export function ConstructionTemplate({ data, queue, costsData }: {
  data: ApiData | null
  queue: BuildingQueue | null
  costsData: BuildingCostsData | null
}) {
  const t = useT()
  const [template, setTemplate] = useState<Record<string, number>>(loadTemplate)
  const [preview,  setPreview]  = useState<PreviewRow[] | null>(null)
  const [applying, setApplying] = useState(false)
  const [done,     setDone]     = useState(false)
  const [saved,    setSaved]    = useState(false)

  const empireData = data?.empireData || {}

  const allBuildings = useMemo(() => {
    const set = new Set<string>()
    Object.values(empireData).forEach(city =>
      Object.keys(city).forEach(k => { if (k !== '_constructionEnds') set.add(k) })
    )
    return Array.from(set).sort()
  }, [empireData])

  const handleSetLevel = (building: string, val: number) => {
    setTemplate(prev => {
      const next = { ...prev }
      if (!val || val <= 0) delete next[building]
      else next[building] = val
      saveTemplate(next)
      return next
    })
    setSaved(true)
    setTimeout(() => setSaved(false), 1500)
    setPreview(null)
    setDone(false)
  }

  const handlePreview = () => {
    const rows: PreviewRow[] = []
    const queueMap: Record<string, Set<string>> = {}
    const progressMap: Record<string, string> = {}
    if (queue) {
      Object.entries(queue.queues).forEach(([city, items]) =>
        items.forEach(i => {
          if (!queueMap[city]) queueMap[city] = new Set()
          queueMap[city].add(i.building)
        })
      )
      Object.entries(queue.inProgress).forEach(([city, ip]) => {
        progressMap[city] = ip.building
      })
    }

    for (const [building, targetLevel] of Object.entries(template)) {
      if (!targetLevel) continue
      for (const [city, buildings] of Object.entries(empireData)) {
        const raw = buildings[building]
        if (raw === undefined || raw === '') continue
        const currentLevel = parseInt(String(raw)) || 0
        if (currentLevel >= targetLevel) continue
        const alreadyQueued = queueMap[city]?.has(building) || progressMap[city] === building
        rows.push({ city, building, currentLevel, targetLevel, status: alreadyQueued ? 'queued' : 'add' })
      }
    }
    rows.sort((a, b) => a.city.localeCompare(b.city) || a.building.localeCompare(b.building))
    setPreview(rows)
    setDone(false)
  }

  const handleApply = async () => {
    if (!preview) return
    setApplying(true)
    const next = [...preview]
    for (let i = 0; i < next.length; i++) {
      const row = next[i]
      if (row.status !== 'add') continue
      try {
        const r = await fetch('/api/building-queue/add', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ cityName: row.city, buildingName: row.building, targetLevel: row.targetLevel }),
        })
        next[i] = { ...row, status: r.ok ? 'done' : 'error' }
      } catch {
        next[i] = { ...row, status: 'error' }
      }
      setPreview([...next])
    }
    setApplying(false)
    setDone(true)
  }

  const toAdd = preview?.filter(r => r.status === 'add').length ?? 0

  const statusColor: Record<RowStatus, string> = {
    add:    'text-slate-600',
    queued: 'text-slate-400',
    done:   'text-emerald-600 font-semibold',
    error:  'text-red-500 font-semibold',
  }
  const statusLabel: Record<RowStatus, string> = {
    add:    t('template_status_add'),
    queued: t('template_status_queued'),
    done:   t('template_status_done'),
    error:  t('template_status_error'),
  }

  if (!data) return (
    <p className="text-slate-400 text-sm mt-4">{t('queue_no_data')}</p>
  )

  return (
    <div className="space-y-4 max-w-3xl">
      <div className="text-sm text-slate-500 bg-indigo-50 border border-indigo-200 rounded-xl px-4 py-3">
        <i className="fa-solid fa-circle-info mr-2 text-indigo-400" />
        {t('template_desc')}
      </div>

      {/* Building target level inputs */}
      <Card>
        <div className="px-5 py-4">
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">{t('template_title')}</p>
            {saved && <span className="text-xs text-emerald-600">{t('template_save_note')}</span>}
          </div>
          {allBuildings.length === 0 ? (
            <p className="text-sm text-slate-400">{t('queue_no_data')}</p>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {allBuildings.map(b => {
                const maxLevel = Math.max(...Object.values(empireData).map(c => parseInt(String(c[b] || '0')) || 0))
                const val = template[b] ?? ''
                return (
                  <div key={b} className={`flex items-center gap-2 rounded-lg px-3 py-2 border text-sm ${template[b] ? 'border-indigo-200 bg-indigo-50' : 'border-slate-100 bg-slate-50'}`}>
                    <span className="flex-1 truncate text-slate-700" title={b}>{b}</span>
                    <span className="text-[10px] text-slate-400 shrink-0">lv {maxLevel}</span>
                    <input
                      type="number"
                      min={1}
                      value={val}
                      placeholder="—"
                      onChange={e => handleSetLevel(b, parseInt(e.target.value) || 0)}
                      className="w-14 border border-slate-200 rounded px-1.5 py-1 text-sm text-center focus:outline-none focus:ring-1 focus:ring-indigo-400"
                    />
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </Card>

      {/* Preview / Apply */}
      <div className="flex gap-2 items-center">
        <button
          onClick={handlePreview}
          disabled={Object.keys(template).length === 0}
          className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white text-sm font-medium rounded-lg transition-colors"
        >
          <i className="fa-solid fa-eye" />
          {t('template_preview_btn')}
        </button>
        {preview && toAdd > 0 && !done && (
          <button
            onClick={handleApply}
            disabled={applying}
            className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
          >
            <i className={`fa-solid ${applying ? 'fa-spinner fa-spin' : 'fa-check'}`} />
            {applying ? t('template_applying') : `${t('template_apply_btn')} (${toAdd})`}
          </button>
        )}
        {done && (
          <span className="text-sm text-emerald-600 font-medium flex items-center gap-1.5">
            <i className="fa-solid fa-circle-check" /> {t('template_done')}
          </span>
        )}
      </div>

      {/* Preview table */}
      {preview !== null && (
        preview.length === 0 ? (
          <p className="text-sm text-slate-400">{t('template_nothing_to_add')}</p>
        ) : (
          <Card>
            <div className="px-5 py-3 border-b border-slate-100 flex items-center justify-between">
              <span className="text-sm font-semibold text-slate-700">
                {toAdd > 0 ? t('template_to_add', { n: String(toAdd) }) : t('template_done')}
              </span>
              {done && (
                <button
                  onClick={() => { setPreview(null); setDone(false) }}
                  className="text-xs text-slate-400 hover:text-slate-600"
                >{t('template_clear_btn')}</button>
              )}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="bg-slate-800 text-white text-xs uppercase tracking-wide">
                    <Th align="text-left" className="px-4">{t('template_col_city')}</Th>
                    <Th align="text-left" className="px-3">{t('template_col_building')}</Th>
                    <Th>{t('template_col_current')}</Th>
                    <Th>{t('template_col_target')}</Th>
                    <Th>{t('template_col_status')}</Th>
                  </tr>
                </thead>
                <tbody>
                  {preview.map((row, i) => (
                    <tr key={i} className={`border-b border-slate-100 ${i % 2 ? 'bg-slate-50/40' : ''}`}>
                      <Td className="px-4 text-slate-700 font-medium">{row.city}</Td>
                      <Td className="px-3 text-slate-600">{row.building}</Td>
                      <Td className="text-center font-mono text-slate-500">{row.currentLevel}</Td>
                      <Td className="text-center font-mono font-semibold text-indigo-600">{row.targetLevel}</Td>
                      <Td className={`text-center text-xs ${statusColor[row.status]}`}>
                        {row.status === 'add' && !done
                          ? <i className="fa-solid fa-plus text-indigo-400" />
                          : statusLabel[row.status]}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )
      )}
    </div>
  )
}
