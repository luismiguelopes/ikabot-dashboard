import { useState, useEffect, useCallback } from 'react'
import { useT } from '../../i18n'
import { fmt } from '../../utils'
import { Card, CardHeader } from '../ui/Card'
import type { MilitaryData, FarmTarget } from './shared'

export function FarmPanel() {
  const t = useT()

  // Data
  const [military,       setMilitary]       = useState<MilitaryData | null>(null)
  const [farmTargets,    setFarmTargets]    = useState<FarmTarget[]>([])
  const [farmArmy,       setFarmArmy]       = useState<Record<string, number>>({})
  const [farmFleet,      setFarmFleet]      = useState<Record<string, number>>({})
  const [farmSpyAgents,  setFarmSpyAgents]  = useState(1)
  const [shipReserve,    setShipReserve]    = useState(true)
  const [reserveHorizon, setReserveHorizon] = useState(45)
  const [earlyRespy,     setEarlyRespy]     = useState(true)
  const [farmArmySaved,  setFarmArmySaved]  = useState(false)

  // ── Fetch data ──────────────────────────────────────────────────────────────

  const loadAll = useCallback(() => {
    fetch('/api/military').then(r => r.json()).then(setMilitary).catch(() => {})

    fetch('/api/farm').then(r => r.json()).then((data: any) => {
      if (Array.isArray(data)) setFarmTargets(data)
    }).catch(() => {})

    fetch('/api/farm/army').then(r => r.json()).then((data: any) => {
      setFarmArmy(data?.army ?? {})
      setFarmFleet(data?.fleet ?? {})
      setFarmSpyAgents(data?.spyAgents ?? 1)
      setShipReserve(data?.shipReserveEnabled ?? true)
      setReserveHorizon(data?.reserveHorizonMin ?? 45)
      setEarlyRespy(data?.earlyRespyEnabled ?? true)
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

  async function saveFarmArmy(
    next: Record<string, number>,
    spyAgents = farmSpyAgents,
    settings: Record<string, unknown> = {
      shipReserveEnabled: shipReserve, reserveHorizonMin: reserveHorizon,
      earlyRespyEnabled: earlyRespy,
    },
  ) {
    setFarmArmy(next)
    setFarmArmySaved(false)
    await fetch('/api/farm/army', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ army: next, spyAgents, ...settings }),
    }).catch(() => {})
    setFarmArmySaved(true)
  }

  async function saveFarmFleet(next: Record<string, number>) {
    setFarmFleet(next)
    setFarmArmySaved(false)
    await fetch('/api/farm/army', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ army: farmArmy, spyAgents: farmSpyAgents, fleet: next }),
    }).catch(() => {})
    setFarmArmySaved(true)
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

  // Union of troop unit types across all cities (for the farm loadout editor)
  const troopTypes: Record<string, string> = {}
  Object.values(military?.byCityName ?? {}).forEach(c => {
    Object.entries(c.troops ?? {}).forEach(([uid, u]) => { troopTypes[uid] = u.name })
  })
  const fleetTypes: Record<string, string> = {}
  Object.values(military?.byCityName ?? {}).forEach(c => {
    Object.entries(c.fleet ?? {}).forEach(([uid, u]) => { fleetTypes[uid] = u.name })
  })

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div>
      {/* ── Target farm (F4) ──────────────────────────────────────────────── */}
      <Card>
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

        {/* Combat-fleet loadout — sent to blockade a flee-fleet target (F4.b) */}
        <div className="px-5 py-3 border-b border-slate-100">
          <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
            {t('farm_fleet_loadout')}
          </span>
          {Object.keys(fleetTypes).length === 0 ? (
            <p className="text-xs text-slate-400 italic mt-1">{t('dispatch_no_units')}</p>
          ) : (
            <>
              <p className="text-xs text-slate-400 my-2">{t('farm_fleet_hint')}</p>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {Object.entries(fleetTypes).map(([uid, uname]) => (
                  <div key={uid} className="flex items-center gap-2">
                    <span className="flex-1 text-xs text-slate-600 truncate" title={uname}>{uname}</span>
                    <input
                      type="number" min={0}
                      value={farmFleet[uid] ?? 0}
                      onChange={e => {
                        const v = Math.max(0, Number(e.target.value))
                        setFarmFleet(prev => ({ ...prev, [uid]: v }))
                        setFarmArmySaved(false)
                      }}
                      className="w-16 border border-slate-200 rounded px-2 py-1 text-xs text-right focus:outline-none focus:ring-2 focus:ring-indigo-400"
                    />
                  </div>
                ))}
              </div>
              <button
                onClick={() => saveFarmFleet(Object.fromEntries(Object.entries(farmFleet).filter(([, v]) => v > 0)))}
                className="mt-2 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-indigo-600 text-white hover:bg-indigo-700"
              >
                <i className="fa-solid fa-floppy-disk" /> {t('transport_save')}
              </button>
            </>
          )}
        </div>

        {/* Ship reserve — keep trade ships free for the farm vs. internal logistics */}
        <div className="px-5 py-3 border-b border-slate-100">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
              {t('farm_reserve')}
            </span>
            <button
              onClick={() => {
                const next = !shipReserve
                setShipReserve(next)
                saveFarmArmy(farmArmy, farmSpyAgents, { shipReserveEnabled: next, reserveHorizonMin: reserveHorizon, earlyRespyEnabled: earlyRespy })
              }}
              className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors shrink-0 ${shipReserve ? 'bg-indigo-600' : 'bg-slate-300'}`}
            >
              <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${shipReserve ? 'translate-x-4' : 'translate-x-1'}`} />
            </button>
          </div>
          <p className="text-xs text-slate-400 mt-1">{t('farm_reserve_hint')}</p>
          {shipReserve && (
            <label className="flex items-center gap-2 mt-2 text-xs text-slate-500">
              {t('farm_reserve_horizon')}
              <input
                type="number" min={0} max={720} value={reserveHorizon}
                onChange={e => setReserveHorizon(Math.max(0, Number(e.target.value)))}
                onBlur={() => saveFarmArmy(farmArmy, farmSpyAgents, { shipReserveEnabled: shipReserve, reserveHorizonMin: reserveHorizon, earlyRespyEnabled: earlyRespy })}
                className="w-16 border border-slate-200 rounded px-1.5 py-0.5 text-xs text-right"
              />
              min
            </label>
          )}
        </div>

        {/* Pipelined re-spy — scout while the troops return */}
        <div className="px-5 py-3 border-b border-slate-100">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
              {t('farm_earlyrespy')}
            </span>
            <button
              onClick={() => {
                const next = !earlyRespy
                setEarlyRespy(next)
                saveFarmArmy(farmArmy, farmSpyAgents, { shipReserveEnabled: shipReserve, reserveHorizonMin: reserveHorizon, earlyRespyEnabled: next })
              }}
              className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors shrink-0 ${earlyRespy ? 'bg-indigo-600' : 'bg-slate-300'}`}
            >
              <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${earlyRespy ? 'translate-x-4' : 'translate-x-1'}`} />
            </button>
          </div>
          <p className="text-xs text-slate-400 mt-1">{t('farm_earlyrespy_hint')}</p>
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
