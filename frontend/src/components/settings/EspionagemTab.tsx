import { useState, useEffect } from 'react'
import { useT } from '../../i18n'
import { useSettings } from '../../hooks/useSettings'
import { Card } from '../ui/Card'
import { NumberField } from '../ui/NumberField'
import { CardTitle, SavedBadge, SaveButton, SELECT_CLS } from './shared'
import { loadSpyDefaults, saveSpyDefaults } from './spyDefaults'
import { WatchlistCard } from './WatchlistCard'
import type { OwnCity } from '../../types'

interface EspionageSettings {
  garrisonThresholdTotal?: number
  minLootTotal?: number
  ignoreExpiryDays?: number
  ignorePermanentAfter?: number
  missionRetentionDays?: number
  spyTargetSuccess?: number
  spyMaxDecoys?: number
}

// Same defaults as the server (app.py `_DEFAULT_ESPIONAGE_SETTINGS` / `_auto_mark_ignored`).
const DEFAULTS = { garrisonThresholdTotal: 50000, minLootTotal: 50000, ignoreExpiryDays: 60, ignorePermanentAfter: 4, missionRetentionDays: 30 }

function SpyDefaultsCard() {
  const t = useT()
  const [ownCities, setOwnCities] = useState<OwnCity[]>([])
  const defaults = loadSpyDefaults()
  const [originCityId, setOriginCityId] = useState(defaults.originCityId)
  const [numAgents, setNumAgents] = useState(defaults.numAgents)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    fetch('/api/own-cities')
      .then(r => r.json())
      .then(d => {
        const cities: OwnCity[] = Array.isArray(d) ? d : (d.cities || [])
        setOwnCities(cities)
        setOriginCityId(prev => prev || (cities[0] ? String(cities[0].cityId) : ''))
      })
      .catch(() => {})
  }, [])

  const handleSave = () => {
    saveSpyDefaults(originCityId, numAgents)
    setSaved(true)
    setTimeout(() => setSaved(false), 3000)
  }

  return (
    <>
      <Card>
        <div className="px-5 py-4">
          <CardTitle icon="fa-user-secret text-indigo-400" className="mb-1">{t('settings_spy_title')}</CardTitle>
          <p className="text-xs text-slate-400 mb-4">{t('settings_spy_hint')}</p>
          <div className="space-y-4">
            <div>
              <label htmlFor="spy-origin" className="block text-xs font-medium text-slate-600 mb-1">{t('spy_origin_city')}</label>
              <select id="spy-origin" value={originCityId} onChange={e => setOriginCityId(e.target.value)} className={SELECT_CLS}>
                {ownCities.map(c => (
                  <option key={c.cityId} value={String(c.cityId)}>{c.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="spy-agents" className="block text-xs font-medium text-slate-600 mb-1">{t('spy_num_agents')}</label>
              <NumberField id="spy-agents" value={numAgents} onCommit={setNumAgents} min={1} max={99} size="lg" align="center" className="w-24" />
            </div>
          </div>
        </div>
      </Card>
      <div className="flex items-center gap-3">
        <SaveButton onClick={handleSave} />
        <SavedBadge show={saved} />
      </div>
    </>
  )
}

function ThresholdsCard() {
  const t = useT()
  const settings = useSettings<EspionageSettings>('/api/espionage/settings')
  const [farmLoots, setFarmLoots] = useState<number[]>([])

  useEffect(() => {
    fetch('/api/farm')
      .then(r => r.json())
      .then((d: Array<{ enabled: boolean; min_loot: number }>) => {
        if (Array.isArray(d)) setFarmLoots(d.filter(f => f.enabled).map(f => f.min_loot || 0))
      })
      .catch(() => {})
  }, [])

  const s = settings.data
  if (!s) return null
  const v = { ...DEFAULTS, ...Object.fromEntries(Object.entries(s).filter(([, x]) => x != null)) } as typeof DEFAULTS
  const field = (key: keyof typeof DEFAULTS, opts: { min: number; max?: number; step?: number; width: string }) => (
    <NumberField value={v[key]} min={opts.min} max={opts.max} step={opts.step} size="lg" className={opts.width}
      onCommit={x => settings.set({ [key]: x })} />
  )

  return (
    <>
      <Card>
        <div className="px-5 py-4">
          <CardTitle icon="fa-shield-halved text-amber-400" className="mb-1">{t('spy_garrison_threshold_title')}</CardTitle>
          <p className="text-xs text-slate-400 mb-4">{t('spy_garrison_threshold_desc')}</p>
          <div className="space-y-3">
            <label className="flex items-center gap-3">
              <span className="text-xs font-medium text-slate-600 whitespace-nowrap">{t('spy_garrison_threshold_label')}</span>
              {field('garrisonThresholdTotal', { min: 0, step: 5000, width: 'w-36' })}
            </label>
            <label className="flex items-center gap-3">
              <span className="text-xs font-medium text-slate-600 whitespace-nowrap">{t('spy_min_loot_label')}</span>
              {field('minLootTotal', { min: 0, step: 5000, width: 'w-36' })}
              <span className="text-[10px] text-slate-400">{t('spy_min_loot_hint')}</span>
            </label>
            <div className="flex items-center gap-3 flex-wrap pt-1 border-t border-slate-100">
              <label className="flex items-center gap-3">
                <span className="text-xs font-medium text-slate-600 whitespace-nowrap">{t('ignore_expiry_label')}</span>
                {field('ignoreExpiryDays', { min: 1, max: 365, width: 'w-20' })}
              </label>
              <label className="flex items-center gap-3">
                <span className="text-xs font-medium text-slate-600 whitespace-nowrap">{t('ignore_permanent_label')}</span>
                {field('ignorePermanentAfter', { min: 1, max: 20, width: 'w-20' })}
              </label>
            </div>
            <p className="text-[10px] text-slate-400 -mt-1">{t('ignore_policy_hint')}</p>
            <label className="flex items-center gap-3 pt-1 border-t border-slate-100">
              <span className="text-xs font-medium text-slate-600 whitespace-nowrap">{t('mission_retention_label')}</span>
              {field('missionRetentionDays', { min: 1, max: 365, width: 'w-20' })}
              <span className="text-[10px] text-slate-400">{t('mission_retention_hint')}</span>
            </label>
            <div className="bg-slate-50 rounded-lg px-3 py-2.5 space-y-1">
              <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wide">{t('threshold_funnel_title')}</p>
              <p className="text-[11px] text-slate-500">1. {t('threshold_funnel_1', { n: v.garrisonThresholdTotal.toLocaleString() })}</p>
              <p className="text-[11px] text-slate-500">2. {t('threshold_funnel_2', { n: v.minLootTotal.toLocaleString() })}</p>
              <p className="text-[11px] text-slate-500">
                3. {farmLoots.length > 0
                  ? t('threshold_funnel_3', {
                      c: String(farmLoots.length),
                      min: Math.min(...farmLoots).toLocaleString(),
                      max: Math.max(...farmLoots).toLocaleString(),
                    })
                  : t('threshold_funnel_3_empty')}
              </p>
            </div>
          </div>
        </div>
      </Card>
      <div className="flex items-center gap-3">
        {/* Only this card's keys: the loadout card saves the rest of the same file. */}
        <SaveButton onClick={() => settings.save(pick(v, Object.keys(DEFAULTS)) as EspionageSettings)} saving={settings.saving} />
        <SavedBadge show={settings.saved} />
      </div>
    </>
  )
}

function pick<T extends object>(obj: T, keys: string[]): Partial<T> {
  return Object.fromEntries(Object.entries(obj).filter(([k]) => keys.includes(k))) as Partial<T>
}

// Same defaults and limits as the server (settings_registry "espionage").
const LOADOUT_DEFAULTS = { spyTargetSuccess: 90, spyMaxDecoys: 2 }

function LoadoutCard() {
  const t = useT()
  const settings = useSettings<EspionageSettings>('/api/espionage/settings')
  const s = settings.data
  if (!s) return null
  const v = {
    spyTargetSuccess: s.spyTargetSuccess ?? LOADOUT_DEFAULTS.spyTargetSuccess,
    spyMaxDecoys: s.spyMaxDecoys ?? LOADOUT_DEFAULTS.spyMaxDecoys,
  }
  return (
    <>
      <Card>
        <div className="px-5 py-4">
          <CardTitle icon="fa-masks-theater text-indigo-400" className="mb-1">{t('spy_loadout_title')}</CardTitle>
          <p className="text-xs text-slate-400 mb-4">{t('spy_loadout_desc')}</p>
          <div className="space-y-3">
            <label className="flex items-center gap-3">
              <span className="text-xs font-medium text-slate-600 whitespace-nowrap">{t('spy_target_success_label')}</span>
              <NumberField value={v.spyTargetSuccess} min={50} max={99} size="lg" className="w-20"
                onCommit={x => settings.set({ spyTargetSuccess: x })} />
              <span className="text-[10px] text-slate-400">%</span>
            </label>
            <label className="flex items-center gap-3">
              <span className="text-xs font-medium text-slate-600 whitespace-nowrap">{t('spy_max_decoys_label')}</span>
              <NumberField value={v.spyMaxDecoys} min={0} max={10} size="lg" className="w-20"
                onCommit={x => settings.set({ spyMaxDecoys: x })} />
              <span className="text-[10px] text-slate-400">{t('spy_max_decoys_hint')}</span>
            </label>
            <div className="bg-slate-50 rounded-lg px-3 py-2.5 space-y-1">
              <p className="text-[11px] text-slate-500">{t('spy_decoy_cost_hint')}</p>
              <p className="text-[11px] text-slate-500">{t('spy_decoy_budget_hint')}</p>
            </div>
          </div>
        </div>
      </Card>
      <div className="flex items-center gap-3">
        <SaveButton onClick={() => settings.save(v)} saving={settings.saving} />
        <SavedBadge show={settings.saved} />
      </div>
    </>
  )
}

export function EspionagemTab() {
  return (
    <div className="grid gap-4 max-w-lg">
      <SpyDefaultsCard />
      <LoadoutCard />
      <ThresholdsCard />
      <WatchlistCard />
    </div>
  )
}
