import { useState } from 'react'
import { useT, useLang } from '../../i18n'
import { fmt, fmtTime } from '../../utils'
import { MATERIALS } from '../../constants'
import { Card, CardHeader } from '../ui/Card'
import { NumInput } from './BuildingUpgradeCalc'
import { sawmillLevels, quarryLevels, forestWardenLevels, stoneMasonLevels, ISLAND_WORKER_BONUS } from '../../data/buildingData'
import type { ApiData } from '../../types'

export function ROICalc({ data: _data }: { data: ApiData }) {
  const t    = useT()
  const lang = useLang() as 'pt' | 'en'
  const [resType,    setResType]    = useState('wood')
  const [numCities,  setNumCities]  = useState(2)
  const [goldPrice,  setGoldPrice]  = useState(15)
  const [sawmillFrom, setSawmillFrom] = useState(1)
  const [sawmillTo,   setSawmillTo]   = useState(2)
  const [quarryFrom,  setQuarryFrom]  = useState(1)
  const [quarryTo,    setQuarryTo]    = useState(2)
  const [fwFrom,      setFwFrom]      = useState(1)
  const [fwTo,        setFwTo]        = useState(2)
  const [stonFrom,    setStonFrom]    = useState(1)
  const [stonTo,      setStonTo]      = useState(2)

  const isWood = resType === 'wood'

  const smFrom = sawmillLevels.find(r => r[0] === sawmillFrom)
  const smTo   = sawmillLevels.find(r => r[0] === sawmillTo)
  const qFrom  = quarryLevels.find(r => r[0] === quarryFrom)
  const qTo    = quarryLevels.find(r => r[0] === quarryTo)
  const effGainIsland = isWood
    ? (smFrom && smTo && sawmillTo > sawmillFrom ? Math.round((smTo[2] - smFrom[2]) * ISLAND_WORKER_BONUS * 10) / 10 : 0)
    : (qFrom  && qTo  && quarryTo  > quarryFrom  ? Math.round((qTo[2]  - qFrom[2])  * ISLAND_WORKER_BONUS * 10) / 10 : 0)
  const effCostIsland = isWood
    ? [sawmillLevels.filter(r => r[0] > sawmillFrom && r[0] <= sawmillTo).reduce((s, r) => s + r[1], 0), 0, 0, 0, 0]
    : [quarryLevels.filter(r => r[0] > quarryFrom && r[0] <= quarryTo).reduce((s, r) => s + r[1], 0), 0, 0, 0, 0]
  const islandBldName = isWood ? t('wood_island_bld') : t('marble_island_bld')
  const cityBldName   = isWood ? t('wood_city_bld')   : t('marble_city_bld')
  const resIcon       = isWood ? 'fa-tree' : 'fa-mountain'
  const resName       = isWood ? MATERIALS[0][lang] : MATERIALS[2][lang]

  const fwInRange   = forestWardenLevels.filter(r => r[0] > fwFrom   && r[0] <= fwTo)
  const stonInRange = stoneMasonLevels.filter(r => r[0] > stonFrom && r[0] <= stonTo)
  const effGainCity = isWood
    ? (smFrom && fwTo > fwFrom   ? Math.round((fwTo   - fwFrom)   * 0.02 * smFrom[2] * ISLAND_WORKER_BONUS * 10) / 10 : 0)
    : (qFrom  && stonTo > stonFrom ? Math.round((stonTo - stonFrom) * 0.02 * qFrom[2]  * ISLAND_WORKER_BONUS * 10) / 10 : 0)
  const effCostCity = isWood
    ? [fwInRange.reduce((s, r) => s + r[1], 0),   0, fwInRange.reduce((s, r) => s + r[2], 0),   0, 0]
    : [stonInRange.reduce((s, r) => s + r[1], 0), 0, stonInRange.reduce((s, r) => s + r[2], 0), 0, 0]

  const totalIslandGain = effGainIsland * numCities
  const totalCityGain   = effGainCity

  const costIslandGold = effCostIsland.reduce((s, v) => s + v * goldPrice, 0)
  const costCityGold   = effCostCity.reduce((s, v) => s + v * goldPrice, 0)

  const amortIsland = (costIslandGold > 0 && totalIslandGain > 0) ? costIslandGold / (totalIslandGain * goldPrice) : null
  const amortCity   = (costCityGold   > 0 && totalCityGain   > 0) ? costCityGold   / (totalCityGain   * goldPrice) : null

  const islandWins = amortIsland !== null && (amortCity === null || amortIsland < amortCity)
  const cityWins   = amortCity   !== null && (amortIsland === null || amortCity < amortIsland)
  const showCompare = (totalIslandGain > 0 || totalCityGain > 0) && (costIslandGold > 0 || costCityGold > 0)
  const minAmort = Math.min(amortIsland ?? Infinity, amortCity ?? Infinity)

  const selectCls = "border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 text-slate-700"

  return (
    <div className="space-y-5">
      <div className="bg-indigo-50 border border-indigo-200 rounded-xl px-5 py-4 text-sm text-indigo-700 flex items-start gap-3">
        <i className="fa-solid fa-circle-info mt-0.5 flex-shrink-0" />
        <span>{t('roi_desc')}</span>
      </div>

      <Card>
        <CardHeader icon="fa-sliders" title={t('config_title')} />
        <div className="p-5 flex flex-wrap gap-5 items-end">
          <div>
            <p className="text-xs font-medium text-slate-500 mb-2">{t('resource_type')}</p>
            <div className="flex gap-2">
              <button
                onClick={() => setResType('wood')}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border transition-colors ${resType === 'wood' ? 'bg-green-600 text-white border-green-600' : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'}`}
              >
                <i className="fa-solid fa-tree" /> {MATERIALS[0][lang]}
              </button>
              <button
                onClick={() => setResType('marble')}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border transition-colors ${resType === 'marble' ? 'bg-slate-600 text-white border-slate-600' : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'}`}
              >
                <i className="fa-solid fa-mountain" /> {MATERIALS[2][lang]}
              </button>
            </div>
          </div>
          <div className="w-36">
            <NumInput label={t('cities_on_island')} value={numCities} onChange={setNumCities} min={1} />
          </div>
          <div className="w-44">
            <NumInput
              label={<><i className="fa-solid fa-coins text-yellow-500" /> {t('gold_price')}</>}
              value={goldPrice}
              onChange={setGoldPrice}
              min={1}
            />
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        <Card className={islandWins ? 'ring-2 ring-emerald-400' : ''}>
          <CardHeader icon="fa-globe" title={`${islandBldName} ${t('island_label')}`} />
          <div className="p-5 space-y-4">
            <div className="bg-blue-50 border border-blue-200 rounded-lg px-3 py-2 text-xs text-blue-700">
              <i className="fa-solid fa-city mr-1" />
              {t('benefits_all_cities', { n: String(numCities) })}
            </div>
            {(() => {
              const levels  = isWood ? sawmillLevels : quarryLevels
              const fromVal = isWood ? sawmillFrom : quarryFrom
              const toVal   = isWood ? sawmillTo   : quarryTo
              const setFrom = isWood
                ? (v: number) => { setSawmillFrom(v); if (sawmillTo <= v) setSawmillTo(v + 1) }
                : (v: number) => { setQuarryFrom(v);  if (quarryTo  <= v) setQuarryTo(v + 1)  }
              const setTo = isWood ? setSawmillTo : setQuarryTo
              return (
                <>
                  <div className="flex flex-wrap gap-3">
                    <div className="flex flex-col gap-1">
                      <label className="text-xs font-medium text-slate-500">{t('current_level')}</label>
                      <select value={fromVal} onChange={e => setFrom(+e.target.value)} className={selectCls}>
                        {levels.slice(0, -1).map(r => <option key={r[0]} value={r[0]}>{r[0]}</option>)}
                      </select>
                    </div>
                    <div className="flex flex-col gap-1">
                      <label className="text-xs font-medium text-slate-500">{t('target_level')}</label>
                      <select value={toVal} onChange={e => setTo(+e.target.value)} className={selectCls}>
                        {levels.filter(r => r[0] > fromVal).map(r => <option key={r[0]} value={r[0]}>{r[0]}</option>)}
                      </select>
                    </div>
                  </div>
                  <div className="bg-slate-50 border border-slate-200 rounded-lg px-4 py-3 text-sm space-y-1.5">
                    <div className="flex justify-between items-center">
                      <span className="text-slate-500">{t('gain_per_city_label', { res: resName })}</span>
                      <span className={`font-semibold ${isWood ? 'text-green-700' : 'text-slate-600'}`}>
                        <i className={`fa-solid ${resIcon} mr-1`} />{fmt(effGainIsland)} /h
                      </span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-500">{t('upgrade_cost_label')}</span>
                      <span className="font-semibold"><i className="fa-solid fa-tree text-green-500 mr-1" />{fmt(effCostIsland[0])} {MATERIALS[0][lang]}</span>
                    </div>
                    <div className="text-xs text-slate-400 italic">{t('auto_computed_label')}</div>
                  </div>
                </>
              )
            })()}
            <div className={`rounded-xl border-2 p-4 ${islandWins ? 'border-emerald-400 bg-emerald-50' : 'border-slate-200 bg-slate-50'}`}>
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-xs text-slate-500 mb-1">{t('total_gain')}</div>
                  <div className="text-2xl font-bold text-slate-800">
                    {fmt(totalIslandGain)} <span className="text-sm font-normal text-slate-400">{resName}/h</span>
                  </div>
                </div>
                {islandWins && <i className="fa-solid fa-trophy text-3xl text-yellow-500" />}
              </div>
              <div className="text-xs text-slate-500 mt-2">{t('equiv_cost', { n: fmt(costIslandGold) })}</div>
              {amortIsland !== null && (
                <div className="text-xs font-semibold text-indigo-600 mt-1">
                  {t('amort_lbl')}: {fmtTime(amortIsland)}
                </div>
              )}
              {islandWins && (
                <div className="text-xs text-emerald-600 font-bold mt-2">
                  <i className="fa-solid fa-check-circle mr-1" />{t('best_option')}
                </div>
              )}
            </div>
          </div>
        </Card>

        <Card className={cityWins ? 'ring-2 ring-emerald-400' : ''}>
          <CardHeader icon="fa-house" title={`${cityBldName} ${t('city_building_label')}`} />
          <div className="p-5 space-y-4">
            <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-xs text-amber-700">
              <i className="fa-solid fa-house mr-1" />
              {t('benefits_only_city')}
            </div>
            {isWood ? (
              <>
                <div className="flex flex-wrap gap-3">
                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-slate-500">{t('current_level')}</label>
                    <select value={fwFrom} onChange={e => { const v = +e.target.value; setFwFrom(v); if (fwTo <= v) setFwTo(v + 1) }} className={selectCls}>
                      {forestWardenLevels.slice(0, -1).map(r => <option key={r[0]} value={r[0]}>{r[0]}</option>)}
                    </select>
                  </div>
                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-slate-500">{t('target_level')}</label>
                    <select value={fwTo} onChange={e => setFwTo(+e.target.value)} className={selectCls}>
                      {forestWardenLevels.filter(r => r[0] > fwFrom).map(r => <option key={r[0]} value={r[0]}>{r[0]}</option>)}
                    </select>
                  </div>
                </div>
                <div className="bg-slate-50 border border-slate-200 rounded-lg px-4 py-3 text-sm space-y-1.5">
                  <div className="flex justify-between items-center">
                    <span className="text-slate-500">{t('gain_this_city_label', { res: resName })}</span>
                    <span className="font-semibold text-green-700">
                      <i className="fa-solid fa-tree mr-1" />{fmt(effGainCity)} /h
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-slate-500">{t('upgrade_cost_label')}</span>
                    <span className="font-semibold">
                      <i className="fa-solid fa-tree text-green-500 mr-1" />{fmt(effCostCity[0])} {MATERIALS[0][lang]}
                      {effCostCity[2] > 0 && <span className="ml-2"><i className="fa-solid fa-mountain text-slate-400 mr-1" />{fmt(effCostCity[2])} {MATERIALS[2][lang]}</span>}
                    </span>
                  </div>
                  <div className="text-xs text-slate-400 italic">{t('auto_computed_label')}</div>
                </div>
              </>
            ) : (
              <>
                <div className="flex flex-wrap gap-3">
                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-slate-500">{t('current_level')}</label>
                    <select value={stonFrom} onChange={e => { const v = +e.target.value; setStonFrom(v); if (stonTo <= v) setStonTo(v + 1) }} className={selectCls}>
                      {stoneMasonLevels.slice(0, -1).map(r => <option key={r[0]} value={r[0]}>{r[0]}</option>)}
                    </select>
                  </div>
                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-slate-500">{t('target_level')}</label>
                    <select value={stonTo} onChange={e => setStonTo(+e.target.value)} className={selectCls}>
                      {stoneMasonLevels.filter(r => r[0] > stonFrom).map(r => <option key={r[0]} value={r[0]}>{r[0]}</option>)}
                    </select>
                  </div>
                </div>
                <div className="bg-slate-50 border border-slate-200 rounded-lg px-4 py-3 text-sm space-y-1.5">
                  <div className="flex justify-between items-center">
                    <span className="text-slate-500">{t('gain_this_city_label', { res: resName })}</span>
                    <span className="font-semibold text-slate-600">
                      <i className="fa-solid fa-mountain mr-1" />{fmt(effGainCity)} /h
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-slate-500">{t('upgrade_cost_label')}</span>
                    <span className="font-semibold">
                      <i className="fa-solid fa-tree text-green-500 mr-1" />{fmt(effCostCity[0])} {MATERIALS[0][lang]}
                      {effCostCity[2] > 0 && <span className="ml-2"><i className="fa-solid fa-mountain text-slate-400 mr-1" />{fmt(effCostCity[2])} {MATERIALS[2][lang]}</span>}
                    </span>
                  </div>
                  <div className="text-xs text-slate-400 italic">{t('auto_computed_label')}</div>
                </div>
              </>
            )}
            <div className={`rounded-xl border-2 p-4 ${cityWins ? 'border-emerald-400 bg-emerald-50' : 'border-slate-200 bg-slate-50'}`}>
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-xs text-slate-500 mb-1">{t('total_gain')}</div>
                  <div className="text-2xl font-bold text-slate-800">
                    {fmt(totalCityGain)} <span className="text-sm font-normal text-slate-400">{resName}/h</span>
                  </div>
                </div>
                {cityWins && <i className="fa-solid fa-trophy text-3xl text-yellow-500" />}
              </div>
              <div className="text-xs text-slate-500 mt-2">{t('equiv_cost', { n: fmt(costCityGold) })}</div>
              {amortCity !== null && (
                <div className="text-xs font-semibold text-indigo-600 mt-1">
                  {t('amort_lbl')}: {fmtTime(amortCity)}
                </div>
              )}
              {cityWins && (
                <div className="text-xs text-emerald-600 font-bold mt-2">
                  <i className="fa-solid fa-check-circle mr-1" />{t('best_option')}
                </div>
              )}
            </div>
          </div>
        </Card>
      </div>

      {showCompare && (
        <Card>
          <CardHeader icon="fa-scale-balanced" title={t('roi_comparison')} />
          <div className="p-5 space-y-4">
            {[
              { label: `${islandBldName} ${t('island_label')}`,     gain: totalIslandGain, costGold: costIslandGold, amort: amortIsland, wins: islandWins },
              { label: `${cityBldName} ${t('city_building_label')}`, gain: totalCityGain,   costGold: costCityGold,   amort: amortCity,   wins: cityWins   },
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
            {(islandWins || cityWins) && (
              <div className="bg-emerald-50 border border-emerald-200 rounded-xl px-4 py-3 text-sm text-emerald-800 font-medium">
                <i className="fa-solid fa-lightbulb mr-2 text-yellow-500" />
                {islandWins
                  ? t('island_better', { name: islandBldName, n: String(numCities) })
                  : t('city_better_roi', { name: cityBldName })
                }
              </div>
            )}
          </div>
        </Card>
      )}
    </div>
  )
}
