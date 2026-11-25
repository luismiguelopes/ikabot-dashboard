import { useState, useEffect } from 'react'
import { useT } from '../../i18n'
import { useSettings } from '../../hooks/useSettings'
import { Toggle } from '../ui/Toggle'
import { NumberField } from '../ui/NumberField'
import type { MilitaryData } from './shared'

// What /api/farm/army stores (GET and POST answer the same keys). `lootCapPerRaid` is the
// MANUAL ceiling (0 = learn); `lootCapInUse` is the ceiling in use now, only on the GET.
interface FarmSettingsData {
  army: Record<string, number>
  fleet: Record<string, number>
  spyAgents: number
  shipReserveEnabled: boolean
  reserveHorizonMin: number
  earlyRespyEnabled: boolean
  earlyReportMaxAgeMins: number
  spyFreshnessHours: number
  lootCapPerRaid: number
  fleetDemoteAfterSweeps: number
  minShipFraction: number
  emptyReturnStrikes: number
  lootCapInUse?: number | null
}

// Farm-wide settings: the minimal army loadout sent per raid, the combat-fleet loadout for
// blockading flee-fleet targets, the ship reserve, and pipelined re-spy. Extracted from the
// Combat Farm panel so the same controls can live in the unified world/target view (P11.6).
// Saved through the shared settings hook: "saved" only on a 2xx, the server's (clamped)
// values replace what is shown, and a failed save shows what is really stored.
export function FarmSettings() {
  const t = useT()
  const s = useSettings<FarmSettingsData>('/api/farm/army')
  const [military, setMilitary] = useState<MilitaryData | null>(null)
  // Loadouts being typed (null = untouched, show what is stored). They stay out of the hook's
  // data, so a toggle saved meanwhile never sends a half-typed loadout (P13.37).
  const [armyDraft,  setArmyDraft]  = useState<Record<string, number> | null>(null)
  const [fleetDraft, setFleetDraft] = useState<Record<string, number> | null>(null)

  useEffect(() => {
    fetch('/api/military').then(r => r.json()).then(setMilitary).catch(() => {})
  }, [])

  const d = s.data
  const farmArmy  = armyDraft  ?? d?.army  ?? {}
  const farmFleet = fleetDraft ?? d?.fleet ?? {}

  const positive = (m: Record<string, number>) => Object.fromEntries(Object.entries(m).filter(([, v]) => v > 0))

  async function saveArmy() {
    if (await s.saveNow({ army: positive(farmArmy) })) setArmyDraft(null)
  }
  async function saveFleet() {
    if (await s.saveNow({ fleet: positive(farmFleet) })) setFleetDraft(null)
  }
  // the ceiling in use is computed by the server from the manual one
  async function saveLootCap(v: number) {
    if (await s.saveNow({ lootCapPerRaid: v })) s.reload()
  }

  const troopTypes: Record<string, string> = {}
  Object.values(military?.byCityName ?? {}).forEach(c => {
    Object.entries(c.troops ?? {}).forEach(([uid, u]) => { troopTypes[uid] = u.name })
  })
  const fleetTypes: Record<string, string> = {}
  Object.values(military?.byCityName ?? {}).forEach(c => {
    Object.entries(c.fleet ?? {}).forEach(([uid, u]) => { fleetTypes[uid] = u.name })
  })

  const fleetEmpty = !Object.values(farmFleet).some(v => v > 0)

  if (!d) return null
  const capInUse = d.lootCapInUse ?? 0

  const advRow = (label: string, hint: string, field: React.ReactNode) => (
    <div className="flex items-start justify-between gap-3 py-1.5">
      <div className="min-w-0">
        <div className="text-xs text-slate-600">{label}</div>
        <div className="text-xs text-slate-400">{hint}</div>
      </div>
      <div className="shrink-0 flex items-center gap-1 text-xs text-slate-500">{field}</div>
    </div>
  )

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
            <NumberField value={d.spyAgents} min={1} max={99} label={t('farm_spies')}
              onCommit={v => s.saveNow({ spyAgents: v })}
              size="sm" className="w-14" />
            {s.saved && <span className="text-emerald-600 ml-1">{t('transport_saved')}</span>}
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
                      setArmyDraft({ ...farmArmy, [uid]: v })
                    }}
                    className="w-16 border border-slate-200 rounded px-2 py-1 text-xs text-right focus:outline-none focus:ring-2 focus:ring-indigo-400"
                  />
                </div>
              ))}
            </div>
            <button
              onClick={saveArmy}
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
            {fleetEmpty && (
              <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1.5 mb-2">
                <i className="fa-solid fa-triangle-exclamation mr-1" />{t('farm_fleet_empty_warn')}
              </p>
            )}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {Object.entries(fleetTypes).map(([uid, uname]) => (
                <div key={uid} className="flex items-center gap-2">
                  <span className="flex-1 text-xs text-slate-600 truncate" title={uname}>{uname}</span>
                  <input
                    type="number" min={0}
                    value={farmFleet[uid] ?? 0}
                    onChange={e => {
                      const v = Math.max(0, Number(e.target.value))
                      setFleetDraft({ ...farmFleet, [uid]: v })
                    }}
                    className="w-16 border border-slate-200 rounded px-2 py-1 text-xs text-right focus:outline-none focus:ring-2 focus:ring-indigo-400"
                  />
                </div>
              ))}
            </div>
            <button
              onClick={saveFleet}
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
          <Toggle size="sm" on={d.shipReserveEnabled} label={t('farm_reserve')} onChange={v => s.saveNow({ shipReserveEnabled: v })} />
        </div>
        <p className="text-xs text-slate-400 mt-1">{t('farm_reserve_hint')}</p>
        {d.shipReserveEnabled && (
          <label className="flex items-center gap-2 mt-2 text-xs text-slate-500">
            {t('farm_reserve_horizon')}
            <NumberField value={d.reserveHorizonMin} min={0} max={720} label={t('farm_reserve_horizon')}
              onCommit={v => s.saveNow({ reserveHorizonMin: v })}
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
          <Toggle size="sm" on={d.earlyRespyEnabled} label={t('farm_earlyrespy')} onChange={v => s.saveNow({ earlyRespyEnabled: v })} />
        </div>
        <p className="text-xs text-slate-400 mt-1">{t('farm_earlyrespy_hint')}</p>
      </div>

      {/* Advanced rules — each field saves itself when you leave it */}
      <div className="px-5 py-3 border-b border-slate-100">
        <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
          {t('farm_adv')}
        </span>
        <div className="mt-1 divide-y divide-slate-50">
          {advRow(t('farm_adv_strikes'), t('farm_adv_strikes_hint'),
            <NumberField value={d.emptyReturnStrikes} min={0} max={20} label={t('farm_adv_strikes')}
              onCommit={v => s.saveNow({ emptyReturnStrikes: v })}
              size="sm" className="w-16" />)}
          {advRow(t('farm_adv_fresh'), t('farm_adv_fresh_hint'),
            <><NumberField value={d.spyFreshnessHours} min={0} max={720} integer={false} step={0.5} label={t('farm_adv_fresh')}
              onCommit={v => s.saveNow({ spyFreshnessHours: v })}
              size="sm" className="w-16" />h</>)}
          {advRow(t('farm_adv_early_age'), t('farm_adv_early_age_hint'),
            <><NumberField value={d.earlyReportMaxAgeMins} min={10} max={1440} label={t('farm_adv_early_age')}
              onCommit={v => s.saveNow({ earlyReportMaxAgeMins: v })}
              size="sm" className="w-16" />min</>)}
          {advRow(t('farm_adv_ship_frac'), t('farm_adv_ship_frac_hint'),
            <><NumberField value={Math.round(d.minShipFraction * 100)} min={0} max={100} label={t('farm_adv_ship_frac')}
              onCommit={v => s.saveNow({ minShipFraction: v / 100 })}
              size="sm" className="w-16" />%</>)}
          {advRow(t('farm_adv_demote'), t('farm_adv_demote_hint'),
            <NumberField value={d.fleetDemoteAfterSweeps} min={0} max={50} label={t('farm_adv_demote')}
              onCommit={v => s.saveNow({ fleetDemoteAfterSweeps: v })}
              size="sm" className="w-16" />)}
          {advRow(t('farm_adv_cap'),
            `${t('farm_adv_cap_hint')} ${capInUse > 0 ? `${t('farm_adv_cap_now')} ${capInUse.toLocaleString('pt-PT')}.` : t('farm_adv_cap_none')}`,
            <NumberField value={d.lootCapPerRaid} min={0} label={t('farm_adv_cap')}
              onCommit={saveLootCap}
              size="sm" className="w-24" />)}
        </div>
      </div>
    </div>
  )
}
