import { useState, useMemo, useEffect } from 'react'
import { useT, useLang } from '../../i18n'
import { fmt, fmtTime } from '../../utils'
import { MATERIALS } from '../../constants'
import { Card } from '../ui/Card'
import { CardHeader } from '../ui/Card'
import { NumInput } from './BuildingUpgradeCalc'
import { sawmillLevels, quarryLevels, residenceLevels, ISLAND_WORKER_BONUS } from '../../data/buildingData'
import type { ApiData } from '../../types'

function LevelSelect({ label, value, onChange, options }: {
  label: string
  value: number
  onChange: (v: number) => void
  options: [number, ...number[]][]
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-slate-500">{label}</label>
      <select value={value} onChange={e => onChange(+e.target.value)}
        className="border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 text-slate-700">
        {options.map(r => <option key={r[0]} value={r[0]}>{r[0]}</option>)}
      </select>
    </div>
  )
}

export function ColonyROICalc({ data, islandPreset }: { data: ApiData | null; islandPreset?: { resType: 'wood' | 'marble', level: number } | null }) {
  const t    = useT()
  const lang = useLang() as 'pt' | 'en'

  const numCities     = data?.empireData ? Object.keys(data.empireData).length : 0
  const requiredLevel = numCities

  const [resType,        setResType]        = useState('wood')
  const [goldPrice,      setGoldPrice]      = useState(15)
  const [upFrom,         setUpFrom]         = useState(1)
  const [upTo,           setUpTo]           = useState(2)
  const [newIslandLevel, setNewIslandLevel] = useState(10)

  useEffect(() => {
    if (!islandPreset) return
    setResType(islandPreset.resType)
    setNewIslandLevel(islandPreset.level || 1)
  }, [islandPreset])
  const [costsData,      setCostsData]      = useState<any>(null)
  const [costsLoading,   setCostsLoading]   = useState(true)

  useEffect(() => {
    fetch('/api/building-costs')
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(d => { setCostsData(d); setCostsLoading(false) })
      .catch(() => setCostsLoading(false))
  }, [])

  const isWood        = resType === 'wood'
  const islandLevels  = isWood ? sawmillLevels : quarryLevels
  const resName       = isWood ? MATERIALS[0][lang] : MATERIALS[2][lang]
  const resIcon       = isWood ? 'fa-tree' : 'fa-mountain'
  const resColorCls   = isWood ? 'text-green-500' : 'text-slate-400'
  const islandBldName = isWood ? t('wood_island_bld') : t('marble_island_bld')

  const upFromData  = islandLevels.find(r => r[0] === upFrom)
  const upToData    = islandLevels.find(r => r[0] === upTo)
  const gainPerCity = (upFromData && upToData && upTo > upFrom)
    ? Math.round((upToData[2] - upFromData[2]) * ISLAND_WORKER_BONUS * 10) / 10
    : 0
  const totalGainA  = gainPerCity * numCities
  const upgradeCost = islandLevels
    .filter(r => r[0] > upFrom && r[0] <= upTo)
    .reduce((s, r) => s + r[1], 0)
  const totalCostAGold = upgradeCost * goldPrice

  const PALACE_NAME = 'Palácio'
  const GOVRES_NAME = 'Residência do Governador'

  const cityResidences = useMemo(() => {
    if (!costsData?.cities) return []
    return Object.entries(costsData.cities).map(([cityName, buildings]: [string, any]) => {
      const isPalace = !!buildings[PALACE_NAME]
      const bname    = isPalace ? PALACE_NAME : GOVRES_NAME
      const bData    = buildings[bname]
      const currentLevel = bData ? bData.currentLevel : requiredLevel
      const needsUpgrade = currentLevel < requiredLevel
      let upgradeCost5   = [0, 0, 0, 0, 0]
      if (needsUpgrade && bData) {
        for (let lv = currentLevel + 1; lv <= requiredLevel; lv++) {
          const c = bData.costs[String(lv)]
          if (c) {
            upgradeCost5[0] += c.wood   || 0
            upgradeCost5[1] += c.wine   || 0
            upgradeCost5[2] += c.marble || 0
            upgradeCost5[3] += c.glass  || 0
            upgradeCost5[4] += c.sulfur || 0
          }
        }
      }
      return {
        cityName, bname, isPalace, currentLevel, needsUpgrade,
        upgradeCost5,
        costGold: upgradeCost5.reduce((s, v) => s + v * goldPrice, 0),
      }
    })
  }, [costsData, requiredLevel, goldPrice])

  const newCityResCost5 = useMemo(() =>
    residenceLevels
      .filter(r => r[0] >= 1 && r[0] <= requiredLevel)
      .reduce((acc, r) => [acc[0]+r[1], acc[1]+r[2], acc[2]+r[3], acc[3]+r[4], acc[4]+r[5]] as [number,number,number,number,number], [0,0,0,0,0] as [number,number,number,number,number]),
    [requiredLevel]
  )
  const newCityResGold = newCityResCost5.reduce((s, v) => s + v * goldPrice, 0)

  const existingResCost5 = useMemo(() =>
    cityResidences.reduce((acc, c) => acc.map((v, i) => v + c.upgradeCost5[i]) as [number,number,number,number,number], [0,0,0,0,0] as [number,number,number,number,number]),
    [cityResidences]
  )
  const totalResCost5    = existingResCost5.map((v, i) => v + newCityResCost5[i])
  const totalResCostGold = totalResCost5.reduce((s, v) => s + v * goldPrice, 0)

  const newIslandData  = islandLevels.find(r => r[0] === newIslandLevel)
  const gainB          = newIslandData
    ? Math.round(newIslandData[2] * ISLAND_WORKER_BONUS * 10) / 10
    : 0
  const totalCostBGold = totalResCostGold
  const amortA = (totalCostAGold > 0 && totalGainA > 0) ? totalCostAGold / (totalGainA * goldPrice) : null
  const amortB = (totalCostBGold > 0 && gainB       > 0) ? totalCostBGold / (gainB       * goldPrice) : null

  const aWins      = amortA !== null && (amortB === null || amortA < amortB)
  const bWins      = amortB !== null && (amortA === null || amortB < amortA)
  const showCompare = amortA !== null || amortB !== null
  const minAmort   = Math.min(amortA ?? Infinity, amortB ?? Infinity)

  return (
    <div className="space-y-5">
      <div className="bg-indigo-50 border border-indigo-200 rounded-xl px-5 py-4 text-sm text-indigo-700 flex items-start gap-3">
        <i className="fa-solid fa-circle-info mt-0.5 flex-shrink-0" />
        <span>{t('colony_desc')}</span>
      </div>

      <Card>
        <CardHeader icon="fa-sliders" title={t('config_title')} />
        <div className="p-5 flex flex-wrap gap-5 items-end">
          <div>
            <p className="text-xs font-medium text-slate-500 mb-2">{t('resource_type')}</p>
            <div className="flex gap-2">
              <button onClick={() => setResType('wood')}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border transition-colors ${resType === 'wood' ? 'bg-green-600 text-white border-green-600' : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'}`}>
                <i className="fa-solid fa-tree" /> {MATERIALS[0][lang]}
              </button>
              <button onClick={() => setResType('marble')}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border transition-colors ${resType === 'marble' ? 'bg-slate-600 text-white border-slate-600' : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'}`}>
                <i className="fa-solid fa-mountain" /> {MATERIALS[2][lang]}
              </button>
            </div>
          </div>
          <div className="text-sm text-slate-600 self-end pb-2">
            <span className="font-medium">{t('n_existing_cities')}:</span>{' '}
            <span className="font-bold text-indigo-700">{numCities}</span>
            <span className="ml-2 text-xs text-slate-400">({t('required_level_lbl', { n: String(requiredLevel) })})</span>
          </div>
          <div className="w-44">
            <NumInput label={<><i className="fa-solid fa-coins text-yellow-500" /> {t('gold_price')}</>}
              value={goldPrice} onChange={setGoldPrice} min={1} />
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">

        {/* Option A */}
        <Card className={aWins ? 'ring-2 ring-emerald-400' : ''}>
          <CardHeader icon="fa-arrow-up" title={t('option_upgrade_lbl')} />
          <div className="p-5 space-y-4">
            <div className="bg-blue-50 border border-blue-200 rounded-lg px-3 py-2 text-xs text-blue-700">
              <i className="fa-solid fa-city mr-1" />
              {t('one_sawmill_note', { n: String(numCities) })}
            </div>
            <div className="flex flex-wrap gap-3">
              <LevelSelect label={t('current_level')} value={upFrom}
                onChange={v => { setUpFrom(v); if (upTo <= v) setUpTo(v + 1) }}
                options={islandLevels.slice(0, -1)} />
              <LevelSelect label={t('target_level')} value={upTo}
                onChange={setUpTo}
                options={islandLevels.filter(r => r[0] > upFrom)} />
            </div>
            <div className="bg-slate-50 border border-slate-200 rounded-lg px-4 py-3 text-sm space-y-1.5">
              <div className="flex justify-between items-center">
                <span className="text-slate-500">{t('gain_per_city_label', { res: resName })}</span>
                <span className={`font-semibold ${isWood ? 'text-green-700' : 'text-slate-600'}`}>
                  <i className={`fa-solid ${resIcon} mr-1`} />{fmt(gainPerCity)} /h
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500">{t('gain_all_islands_lbl', { n: String(numCities) })}</span>
                <span className={`font-bold ${isWood ? 'text-green-700' : 'text-slate-600'}`}>
                  <i className={`fa-solid ${resIcon} mr-1`} />{fmt(totalGainA)} /h
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500">{t('upgrade_cost_label')}</span>
                <span className="font-semibold">
                  <i className="fa-solid fa-tree text-green-500 mr-1" />{fmt(upgradeCost)} {MATERIALS[0][lang]}
                </span>
              </div>
              <div className="text-xs text-slate-400 italic">{t('auto_computed_label')}</div>
            </div>
            <div className={`rounded-xl border-2 p-4 ${aWins ? 'border-emerald-400 bg-emerald-50' : 'border-slate-200 bg-slate-50'}`}>
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-xs text-slate-500 mb-1">{t('total_gain')}</div>
                  <div className="text-2xl font-bold text-slate-800">
                    {fmt(totalGainA)} <span className="text-sm font-normal text-slate-400">{resName}/h</span>
                  </div>
                </div>
                {aWins && <i className="fa-solid fa-trophy text-3xl text-yellow-500" />}
              </div>
              <div className="text-xs text-slate-500 mt-2">{t('equiv_cost', { n: fmt(totalCostAGold) })}</div>
              {amortA !== null && <div className="text-xs font-semibold text-indigo-600 mt-1">{t('amort_lbl')}: {fmtTime(amortA)}</div>}
              {aWins && <div className="text-xs text-emerald-600 font-bold mt-2"><i className="fa-solid fa-check-circle mr-1" />{t('best_option')}</div>}
            </div>
          </div>
        </Card>

        {/* Option B */}
        <Card className={bWins ? 'ring-2 ring-emerald-400' : ''}>
          <CardHeader icon="fa-ship" title={t('option_colony_lbl')} />
          <div className="p-5 space-y-4">
            <div>
              <p className="text-xs font-semibold text-slate-600 mb-2 flex items-center gap-2">
                <i className="fa-solid fa-house text-amber-500" />{t('residence_label')}
                <span className="ml-auto font-normal text-slate-400">{t('required_level_lbl', { n: String(requiredLevel) })}</span>
              </p>
              {costsLoading
                ? <div className="text-xs text-slate-400 py-2">{t('loading')}</div>
                : (
                  <div className="rounded-lg border border-slate-200 overflow-hidden text-xs divide-y divide-slate-100">
                    {cityResidences.map(c => (
                      <div key={c.cityName} className={`flex items-center justify-between px-3 py-1.5 ${c.needsUpgrade ? 'bg-red-50' : 'bg-emerald-50'}`}>
                        <span className="font-medium text-slate-700 truncate mr-2">
                          {c.isPalace ? '🏛 ' : '🏠 '}{c.cityName}
                        </span>
                        <span className="flex items-center gap-2 shrink-0">
                          <span className="text-slate-400">lv {c.currentLevel}</span>
                          {c.needsUpgrade
                            ? <span className="text-red-600 font-semibold">{fmt(c.costGold)} {t('gold_label')}</span>
                            : <i className="fa-solid fa-check-circle text-emerald-500" />
                          }
                        </span>
                      </div>
                    ))}
                    <div className="flex items-center justify-between px-3 py-1.5 bg-blue-50">
                      <span className="font-medium text-blue-700">🏠 {t('new_city_lbl')}</span>
                      <span className="text-blue-600 font-semibold ml-2">{fmt(newCityResGold)} {t('gold_label')}</span>
                    </div>
                  </div>
                )
              }
              {!costsLoading && (
                <div className="bg-slate-50 border border-slate-200 rounded-lg px-4 py-3 text-sm space-y-1 mt-2">
                  {MATERIALS.map((m, i) => totalResCost5[i] > 0 && (
                    <div key={m.en} className="flex justify-between items-center">
                      <span className="text-slate-500 flex items-center gap-1">
                        <i className={`fa-solid ${m.icon} ${m.color}`} /> {m[lang]}
                      </span>
                      <span className="font-semibold text-slate-700">{fmt(totalResCost5[i])}</span>
                    </div>
                  ))}
                  <div className="text-xs text-slate-400 italic pt-1">{t('auto_computed_label')}</div>
                </div>
              )}
            </div>

            <div>
              <p className="text-xs font-semibold text-slate-600 mb-2">
                <i className={`fa-solid ${resIcon} mr-1 ${resColorCls}`} />{islandBldName} — {t('new_island_lbl')}
              </p>
              <div className="flex flex-wrap gap-3 mb-3">
                <LevelSelect label={t('current_level')} value={newIslandLevel}
                  onChange={setNewIslandLevel}
                  options={islandLevels} />
              </div>
              <div className="bg-slate-50 border border-slate-200 rounded-lg px-4 py-2 text-sm">
                <div className="flex justify-between items-center">
                  <span className="text-slate-500">{t('gain_new_island_lbl')}</span>
                  <span className={`font-bold ${isWood ? 'text-green-700' : 'text-slate-600'}`}>
                    <i className={`fa-solid ${resIcon} mr-1`} />{fmt(gainB)} /h
                  </span>
                </div>
              </div>
            </div>

            <div className={`rounded-xl border-2 p-4 ${bWins ? 'border-emerald-400 bg-emerald-50' : 'border-slate-200 bg-slate-50'}`}>
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-xs text-slate-500 mb-1">{t('total_gain')}</div>
                  <div className="text-2xl font-bold text-slate-800">
                    {fmt(gainB)} <span className="text-sm font-normal text-slate-400">{resName}/h</span>
                  </div>
                </div>
                {bWins && <i className="fa-solid fa-trophy text-3xl text-yellow-500" />}
              </div>
              <div className="text-xs text-slate-500 mt-2">{t('equiv_cost', { n: fmt(totalCostBGold) })}</div>
              {amortB !== null && <div className="text-xs font-semibold text-indigo-600 mt-1">{t('amort_lbl')}: {fmtTime(amortB)}</div>}
              {bWins && <div className="text-xs text-emerald-600 font-bold mt-2"><i className="fa-solid fa-check-circle mr-1" />{t('best_option')}</div>}
            </div>
          </div>
        </Card>
      </div>

      {showCompare && (
        <Card>
          <CardHeader icon="fa-scale-balanced" title={t('roi_comparison')} />
          <div className="p-5 space-y-4">
            {[
              { label: t('option_upgrade_lbl'), gain: totalGainA, costGold: totalCostAGold, amort: amortA, wins: aWins },
              { label: t('option_colony_lbl'),  gain: gainB,      costGold: totalCostBGold, amort: amortB, wins: bWins },
            ].map((opt, i) => {
              const barPct = (isFinite(minAmort) && opt.amort !== null) ? Math.round((minAmort / opt.amort) * 100) : 0
              return (
                <div key={i}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-semibold text-slate-700 flex items-center gap-1">
                      {opt.wins && <i className="fa-solid fa-trophy text-yellow-500 text-xs" />}
                      {opt.label}
                    </span>
                    <div className="text-xs text-slate-500 text-right">
                      +{fmt(opt.gain)} {resName}/h &nbsp;|&nbsp; {fmt(opt.costGold)} {t('gold_label')}
                      {opt.amort !== null && <span className="ml-2 font-semibold text-indigo-600">{t('amort_lbl')}: {fmtTime(opt.amort)}</span>}
                    </div>
                  </div>
                  <div className="w-full h-5 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all duration-500 flex items-center justify-end pr-2 text-white text-xs font-bold ${opt.wins ? 'bg-emerald-500' : 'bg-indigo-400'}`}
                      style={{ width: `${Math.max(barPct, 2)}%` }}
                    >
                      {barPct > 15 ? `${barPct}%` : ''}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </Card>
      )}
    </div>
  )
}
