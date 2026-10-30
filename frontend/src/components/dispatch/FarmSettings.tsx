import { useState, useEffect, useCallback } from 'react'
import { useT } from '../../i18n'
import type { MilitaryData } from './shared'

// Farm-wide settings: the minimal army loadout sent per raid, the combat-fleet loadout for
// blockading flee-fleet targets, the ship reserve, and pipelined re-spy. Extracted from the
// Combat Farm panel so the same controls can live in the unified world/target view (P11.6).
// Self-contained: fetches its own military + /api/farm/army and persists via /api/farm/army.
export function FarmSettings() {
  const t = useT()

  const [military,       setMilitary]       = useState<MilitaryData | null>(null)
  const [farmArmy,       setFarmArmy]       = useState<Record<string, number>>({})
  const [farmFleet,      setFarmFleet]      = useState<Record<string, number>>({})
  const [farmSpyAgents,  setFarmSpyAgents]  = useState(1)
  const [shipReserve,    setShipReserve]    = useState(true)
  const [reserveHorizon, setReserveHorizon] = useState(45)
  const [earlyRespy,     setEarlyRespy]     = useState(true)
  const [farmArmySaved,  setFarmArmySaved]  = useState(false)

  const loadAll = useCallback(() => {
    fetch('/api/military').then(r => r.json()).then(setMilitary).catch(() => {})
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

  const troopTypes: Record<string, string> = {}
  Object.values(military?.byCityName ?? {}).forEach(c => {
    Object.entries(c.troops ?? {}).forEach(([uid, u]) => { troopTypes[uid] = u.name })
  })
  const fleetTypes: Record<string, string> = {}
  Object.values(military?.byCityName ?? {}).forEach(c => {
    Object.entries(c.fleet ?? {}).forEach(([uid, u]) => { fleetTypes[uid] = u.name })
  })

  return (
    <div>
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
    </div>
  )
}
