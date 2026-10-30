import { useState, useEffect, useCallback } from 'react'
import { useT } from '../../i18n'
import { fmt } from '../../utils'
import { Card, CardHeader } from '../ui/Card'
import type { FarmTarget } from './shared'
import { FarmSettings } from './FarmSettings'

export function FarmPanel() {
  const t = useT()

  const [farmTargets, setFarmTargets] = useState<FarmTarget[]>([])

  const loadAll = useCallback(() => {
    fetch('/api/farm').then(r => r.json()).then((data: any) => {
      if (Array.isArray(data)) setFarmTargets(data)
    }).catch(() => {})
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  // ── Farm (F4) ────────────────────────────────────────────────────────────────

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

  // Pure-queue order (mirrors farm_manager._queue_head): active target first, then enabled
  // IDLE targets by loot/hour desc. Disabled (drained) targets get no position.
  const DEFAULT_RT = 4 * 3600
  const roundTrip = (f: FarmTarget) => (f.last_troop_journey > 0 ? f.last_troop_journey * 2 : DEFAULT_RT)
  const score = (f: FarmTarget) => (f.last_loot || 0) / Math.max(1, roundTrip(f))
  const queueOrder = farmTargets
    .filter(f => f.enabled)
    .sort((a, b) => {
      const aActive = a.state !== 'IDLE', bActive = b.state !== 'IDLE'
      if (aActive !== bActive) return aActive ? -1 : 1   // mid-cycle target leads
      return score(b) - score(a)
    })
  const queuePos: Record<string, number> = {}
  queueOrder.forEach((f, i) => { queuePos[f.target_city_id] = i + 1 })

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div>
      {/* ── Target farm (F4) ──────────────────────────────────────────────── */}
      <Card>
        <CardHeader icon="fa-seedling" title={t('farm_title')} />
        <p className="px-5 pt-2 text-xs text-slate-400">{t('farm_note')}</p>

        <FarmSettings />

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
                      {queuePos[f.target_city_id] && (
                        <span
                          className={`mr-1.5 px-1.5 py-0.5 rounded text-[10px] font-bold ${queuePos[f.target_city_id] === 1 ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-400'}`}
                          title={queuePos[f.target_city_id] === 1 ? t('farm_queue_head') : t('farm_queue_waiting')}
                        >
                          #{queuePos[f.target_city_id]}
                        </span>
                      )}
                      {f.target_city_name}
                      <span className="text-slate-400 text-xs ml-1 font-normal">({f.target_player})</span>
                      <span className={`ml-2 px-1.5 py-0.5 rounded text-[10px] font-medium ${stateColor}`}>
                        {t(`farm_state_${f.state}`)}
                      </span>
                    </div>
                    <div className="text-xs text-slate-400 mt-0.5 flex items-center gap-1.5 flex-wrap">
                      <span>{t('farm_minloot')} {fmt(f.min_loot)}</span>
                      <span>·</span>
                      <span className="flex items-center gap-1" title={t('farm_maxships_hint')}>
                        {t('farm_maxships')}
                        <input
                          type="number" min={0} max={9999} value={f.max_enemy_ships}
                          onChange={e => farmUpdate(f.target_city_id, { maxEnemyShips: Math.max(0, Number(e.target.value)) })}
                          className="w-14 border border-slate-200 rounded px-1 py-0.5 text-xs text-right"
                        />
                      </span>
                      <span>·</span>
                      <span className="flex items-center gap-1">
                        {t('farm_respy')}
                        <input
                          type="number" min={1} max={50} value={f.respy_every}
                          onChange={e => farmUpdate(f.target_city_id, { respyEvery: Math.max(1, Number(e.target.value)) })}
                          className="w-12 border border-slate-200 rounded px-1 py-0.5 text-xs text-right"
                        />
                      </span>
                      {f.is_fleet_target === 1 && (
                        <>
                          <span>·</span>
                          <span className="px-1 py-0.5 rounded bg-cyan-100 text-cyan-700 text-[10px] font-medium" title={t('farm_fleet_target_hint')}>
                            <i className="fa-solid fa-anchor mr-1" />{t('farm_fleet_target')}
                          </span>
                          <span className="flex items-center gap-1" title={t('farm_fleetlead_hint')}>
                            {t('farm_fleetlead')}
                            <input
                              type="number" min={1} max={120} value={f.fleet_lead_min ?? 5}
                              onChange={e => farmUpdate(f.target_city_id, { fleetLeadMin: Math.max(1, Number(e.target.value)) })}
                              className="w-12 border border-slate-200 rounded px-1 py-0.5 text-xs text-right"
                            />
                            min
                          </span>
                          <span className="flex items-center gap-1" title={t('farm_disperse_hint')}>
                            {t('farm_disperse')}
                            <input
                              type="number" min={1} max={1440} value={f.disperse_min ?? 240}
                              onChange={e => farmUpdate(f.target_city_id, { disperseMin: Math.max(1, Number(e.target.value)) })}
                              className="w-14 border border-slate-200 rounded px-1 py-0.5 text-xs text-right"
                            />
                            min
                          </span>
                        </>
                      )}
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
