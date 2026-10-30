import { useState, useEffect, useCallback } from 'react'
import { useT, useLang } from '../../i18n'
import { fmt, fmtArrival } from '../../utils'
import { MATERIALS } from '../../constants'
import { Card, CardHeader } from '../ui/Card'

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

export function HistoryPanel() {
  const t    = useT()
  const lang = useLang()

  const [attackLog, setAttackLog] = useState<AttackLogEntry[]>([])
  const [lootStats, setLootStats] = useState<LootStat[]>([])
  const [logFilter, setLogFilter] = useState('')

  const loadAll = useCallback(() => {
    fetch('/api/attack-log?limit=100').then(r => r.json()).then((data: any) => {
      if (Array.isArray(data)) setAttackLog(data)
    }).catch(() => {})

    fetch('/api/loot-stats').then(r => r.json()).then((data: any) => {
      if (Array.isArray(data)) setLootStats(data)
    }).catch(() => {})
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  return (
    <div>
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
    </div>
  )
}
