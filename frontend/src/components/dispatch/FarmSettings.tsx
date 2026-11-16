import { useState, useEffect, useCallback } from 'react'
import { useT } from '../../i18n'
import { apiAction } from '../../api'
import { Toggle } from '../ui/Toggle'
import { NumberField } from '../ui/NumberField'
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

  // Each control saves only its own key (P13.37): a toggle used to send the half-typed army
  // draft along with it. "Saved" only on a 2xx; the server's (clamped) values are kept.
  async function saveFarm(patch: Record<string, unknown>): Promise<boolean> {
    setFarmArmySaved(false)
    const d: any = await apiAction('/api/farm/army', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(patch),
    })
    if (!d) return false
    if ('army' in patch)              setFarmArmy(d.army ?? {})
    if ('fleet' in patch)             setFarmFleet(d.fleet ?? {})
    if ('spyAgents' in patch)         setFarmSpyAgents(d.spyAgents ?? 1)
    if ('reserveHorizonMin' in patch) setReserveHorizon(d.reserveHorizonMin ?? 45)
    setFarmArmySaved(true)
    return true
  }

  const positive = (m: Record<string, number>) => Object.fromEntries(Object.entries(m).filter(([, v]) => v > 0))

  async function toggleSetting(key: 'shipReserveEnabled' | 'earlyRespyEnabled', next: boolean) {
    const set = key === 'shipReserveEnabled' ? setShipReserve : setEarlyRespy
    set(next)
    if (!(await saveFarm({ [key]: next }))) set(!next)   // failed → show what is really stored
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
            <NumberField value={farmSpyAgents} min={1} max={99} label={t('farm_spies')}
              onCommit={v => { setFarmSpyAgents(v); saveFarm({ spyAgents: v }) }}
              size="sm" className="w-14" />
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
              onClick={() => saveFarm({ army: positive(farmArmy) })}
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
              onClick={() => saveFarm({ fleet: positive(farmFleet) })}
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
          <Toggle size="sm" on={shipReserve} label={t('farm_reserve')} onChange={v => toggleSetting('shipReserveEnabled', v)} />
        </div>
        <p className="text-xs text-slate-400 mt-1">{t('farm_reserve_hint')}</p>
        {shipReserve && (
          <label className="flex items-center gap-2 mt-2 text-xs text-slate-500">
            {t('farm_reserve_horizon')}
            <NumberField value={reserveHorizon} min={0} max={720} label={t('farm_reserve_horizon')}
              onCommit={v => { setReserveHorizon(v); saveFarm({ reserveHorizonMin: v }) }}
              size="sm" className="w-16" />
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
          <Toggle size="sm" on={earlyRespy} label={t('farm_earlyrespy')} onChange={v => toggleSetting('earlyRespyEnabled', v)} />
        </div>
        <p className="text-xs text-slate-400 mt-1">{t('farm_earlyrespy_hint')}</p>
      </div>
    </div>
  )
}
