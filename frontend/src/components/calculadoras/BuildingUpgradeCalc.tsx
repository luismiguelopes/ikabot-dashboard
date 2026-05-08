import { useState, useEffect } from 'react'
import { useT, useLang } from '../../i18n'
import { fmt, fmtHours, fmtTs, calcUpgradeTime } from '../../utils'
import { MATERIALS, COST_KEYS } from '../../constants'
import { Card, CardHeader } from '../ui/Card'
import { Th, Td } from '../ui/TableCells'
import type { ApiData, BuildingCostsData } from '../../types'

export function NumInput({ label, value, onChange, min = 0, step = 1 }: {
  label: React.ReactNode; value: number; onChange: (v: number) => void; min?: number; step?: number
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-slate-500 flex items-center gap-1">{label}</label>
      <input
        type="number"
        min={min}
        step={step}
        value={value === 0 ? '' : value}
        onChange={e => onChange(e.target.value === '' ? 0 : Number(e.target.value))}
        placeholder="0"
        className="border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 text-slate-700 w-full font-mono"
      />
    </div>
  )
}

export function BuildingUpgradeCalc({ data }: { data: ApiData }) {
  const t = useT()
  const lang = useLang() as 'pt' | 'en'
  const { statusSummary } = data
  const gold       = statusSummary.gold.total
  const available  = statusSummary.resources.available
  const production = statusSummary.resources.production

  const [needed,    setNeeded]    = useState([0, 0, 0, 0, 0])
  const [goldPrice, setGoldPrice] = useState(15)

  const [costsData,    setCostsData]    = useState<BuildingCostsData | null>(null)
  const [costsLoading, setCostsLoading] = useState(true)
  const [costsError,   setCostsError]   = useState(false)
  const [refreshMsg,   setRefreshMsg]   = useState('')

  const [selCity,        setSelCity]        = useState('')
  const [selBuilding,    setSelBuilding]     = useState('')
  const [selTargetLevel, setSelTargetLevel]  = useState('')

  useEffect(() => {
    fetch('/api/building-costs')
      .then(r => r.ok ? r.json() : Promise.reject())
      .then((d: BuildingCostsData) => { setCostsData(d); setCostsLoading(false) })
      .catch(() => { setCostsLoading(false); setCostsError(true) })
  }, [])

  useEffect(() => { setSelBuilding(''); setSelTargetLevel('') }, [selCity])
  useEffect(() => { setSelTargetLevel(''); setNeeded([0, 0, 0, 0, 0]) }, [selBuilding])

  useEffect(() => {
    if (!costsData || !selCity || !selBuilding || !selTargetLevel) return
    const bData = costsData.cities?.[selCity]?.[selBuilding]
    if (!bData) return
    const target = parseInt(selTargetLevel, 10)
    const totals = [0, 0, 0, 0, 0]
    for (let lv = bData.currentLevel + 1; lv <= target; lv++) {
      const lvCost = bData.costs[String(lv)]
      if (lvCost) COST_KEYS.forEach((k, i) => { totals[i] += lvCost[k] || 0 })
    }
    setNeeded(totals)
  }, [selCity, selBuilding, selTargetLevel, costsData])

  const handleForceRefresh = () => {
    setRefreshMsg('sending')
    fetch('/api/building-costs/refresh', { method: 'POST' })
      .then(r => r.json())
      .then(() => setRefreshMsg('ok'))
      .catch(() => setRefreshMsg('error'))
  }

  const handleClear = () => { setSelCity(''); setSelBuilding(''); setSelTargetLevel(''); setNeeded([0, 0, 0, 0, 0]) }

  const citiesWithData   = costsData ? Object.keys(costsData.cities || {}) : []
  const buildingsForCity = selCity && costsData?.cities?.[selCity] ? Object.keys(costsData.cities[selCity]) : []
  const selBuildingData  = selCity && selBuilding ? costsData?.cities?.[selCity]?.[selBuilding] : null
  const availableLevels  = selBuildingData ? Object.keys(selBuildingData.costs).map(Number).sort((a, b) => a - b) : []
  const autoFilled       = selTargetLevel !== ''

  const setRes = (i: number, v: number) => setNeeded(prev => { const n = [...prev]; n[i] = v; return n })
  const r = calcUpgradeTime(needed, available, production, gold, goldPrice)
  const hasInput = needed.some(n => n > 0)

  const selectCls = "border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 text-slate-700 disabled:opacity-40 disabled:cursor-not-allowed"

  return (
    <div className="space-y-5">
      <div className="bg-indigo-50 border border-indigo-200 rounded-xl px-5 py-4 text-sm text-indigo-700 flex items-start gap-3">
        <i className="fa-solid fa-circle-info mt-0.5 flex-shrink-0" />
        <span>{t('upgrade_desc')}</span>
      </div>

      {costsLoading && (
        <div className="flex items-center gap-2 text-slate-400 text-sm px-1">
          <div className="w-4 h-4 rounded-full border-2 border-slate-300 border-t-indigo-400 animate-spin" />
          {t('loading_costs')}
        </div>
      )}

      {!costsLoading && costsError && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl px-5 py-4 flex items-start justify-between gap-4">
          <div className="flex items-start gap-3 text-sm text-amber-700">
            <i className="fa-solid fa-triangle-exclamation mt-0.5 flex-shrink-0" />
            <span>{t('costs_unavailable')}</span>
          </div>
          <button
            onClick={handleForceRefresh}
            className="flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 bg-amber-600 hover:bg-amber-700 text-white text-xs font-medium rounded-lg transition-colors"
          >
            <i className="fa-solid fa-rotate" /> {t('request_extraction')}
          </button>
        </div>
      )}

      {!costsLoading && costsData && (
        <Card>
          <CardHeader icon="fa-wand-magic-sparkles" title={t('autofill_title')} />
          <div className="p-5">
            <div className="flex flex-wrap gap-4 items-end mb-4">
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-slate-500">{t('label_city')}</label>
                <select className={selectCls} value={selCity} onChange={e => setSelCity(e.target.value)}>
                  <option value="">{t('select_placeholder')}</option>
                  {citiesWithData.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>

              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-slate-500">{t('label_building')}</label>
                <select className={selectCls} value={selBuilding} onChange={e => setSelBuilding(e.target.value)} disabled={!selCity}>
                  <option value="">{t('select_placeholder')}</option>
                  {buildingsForCity.map(b => {
                    const lvl = costsData!.cities[selCity][b].currentLevel
                    return <option key={b} value={b}>{b} ({t('level_label', { n: String(lvl) })})</option>
                  })}
                </select>
              </div>

              {selBuildingData && (
                <div className="flex flex-col gap-1">
                  <label className="text-xs font-medium text-slate-500">
                    {t('current_level_label', { n: String(selBuildingData.currentLevel) })}
                  </label>
                  <select className={selectCls} value={selTargetLevel} onChange={e => setSelTargetLevel(e.target.value)}>
                    <option value="">{t('select_placeholder')}</option>
                    {availableLevels.map(lv => <option key={lv} value={lv}>{lv}</option>)}
                  </select>
                </div>
              )}

              {autoFilled && (
                <button
                  onClick={handleClear}
                  className="flex items-center gap-1.5 px-3 py-2 bg-slate-100 hover:bg-slate-200 text-slate-600 text-sm font-medium rounded-lg transition-colors"
                >
                  <i className="fa-solid fa-xmark" /> {t('clear')}
                </button>
              )}
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 pt-3 border-t border-slate-100">
              <p className="text-xs text-slate-400">
                <i className="fa-regular fa-clock mr-1" />
                {t('last_extraction', { ts: fmtTs(costsData.lastUpdated, lang) })}
                <span className="ml-2 text-slate-300">{t('updates_3d')}</span>
              </p>
              <div className="flex items-center gap-3">
                {refreshMsg === 'sending' && <span className="text-xs text-slate-400">{t('sending_request')}</span>}
                {refreshMsg === 'ok'      && <span className="text-xs text-emerald-600 font-medium">{t('scheduled_ok')}</span>}
                {refreshMsg === 'error'   && <span className="text-xs text-red-500">{t('schedule_error')}</span>}
                <button
                  onClick={handleForceRefresh}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-white text-xs font-medium rounded-lg transition-colors"
                >
                  <i className="fa-solid fa-rotate" /> {t('force_update')}
                </button>
              </div>
            </div>
          </div>
        </Card>
      )}

      <Card>
        <CardHeader icon="fa-boxes-stacked" title={autoFilled
          ? t('resources_for', { building: selBuilding, cur: String(selBuildingData?.currentLevel), target: selTargetLevel })
          : t('resources_needed')
        } />
        <div className="p-5">
          {autoFilled && (
            <div className="mb-4 flex items-center gap-2 text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2">
              <i className="fa-solid fa-circle-check" />
              {t('autofilled_msg')}
            </div>
          )}
          <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-4 mb-5">
            {MATERIALS.map((m, i) => (
              <NumInput
                key={m.en}
                label={<><i className={`fa-solid ${m.icon} ${m.color}`} /> {m[lang]}</>}
                value={needed[i]}
                onChange={v => setRes(i, v)}
              />
            ))}
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

      {hasInput && (
        <Card>
          <CardHeader icon="fa-table-list" title={t('resource_status')} />
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="bg-slate-800 text-white text-xs uppercase tracking-wide">
                  <Th align="text-left" className="px-5">Resource</Th>
                  <Th>{t('col_needed')}</Th>
                  <Th>{t('col_available')}</Th>
                  <Th>{t('col_missing')}</Th>
                  <Th>{t('col_production')}</Th>
                </tr>
              </thead>
              <tbody>
                {MATERIALS.map((m, i) => {
                  const miss = r.missing[i]
                  return (
                    <tr key={m.en} className="border-b border-slate-100 hover:bg-slate-50">
                      <Td className="px-5 font-semibold text-slate-700">
                        <i className={`fa-solid ${m.icon} mr-1.5 ${m.color}`} />{m[lang]}
                      </Td>
                      <Td className="text-center font-mono">{fmt(needed[i])}</Td>
                      <Td className="text-center font-mono">{fmt(available[i])}</Td>
                      <Td className={`text-center font-mono font-bold ${miss > 0 ? 'text-red-500' : 'text-emerald-500'}`}>
                        {miss > 0 ? `−${fmt(miss)}` : <i className="fa-solid fa-check" />}
                      </Td>
                      <Td className="text-center font-mono text-slate-500">{fmt(production[i])}</Td>
                    </tr>
                  )
                })}
                <tr className="bg-slate-800 text-white text-xs font-bold">
                  <td className="px-5 py-2.5 text-left">TOTAL</td>
                  <td className="px-3 py-2.5 text-center font-mono">{fmt(needed.reduce((s,v)=>s+v,0))}</td>
                  <td className="px-3 py-2.5 text-center font-mono">{fmt(available.reduce((s,v)=>s+v,0))}</td>
                  <td className={`px-3 py-2.5 text-center font-mono ${r.totalMissing > 0 ? 'text-red-300' : 'text-emerald-300'}`}>
                    {r.totalMissing > 0 ? `−${fmt(r.totalMissing)}` : <i className="fa-solid fa-check" />}
                  </td>
                  <td className="px-3 py-2.5 text-center font-mono text-slate-300">{fmt(r.totalProduction)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {hasInput && (
        <Card>
          <CardHeader icon="fa-clock" title={t('upgrade_time_title')} />
          <div className="p-5">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className={`rounded-xl border-2 p-4 text-center ${r.timeNoGold === 0 ? 'border-emerald-400 bg-emerald-50' : 'border-slate-200 bg-slate-50'}`}>
                <div className="text-xs text-slate-500 mb-1 font-medium">
                  <i className="fa-solid fa-ban mr-1 text-slate-400" />{t('no_gold_buying')}
                </div>
                <div className={`text-2xl font-bold mt-2 ${r.timeNoGold === 0 ? 'text-emerald-600' : 'text-slate-700'}`}>
                  {r.timeNoGold === 0 ? t('have_everything') : fmtHours(r.timeNoGold, t)}
                </div>
                <div className="text-xs text-slate-400 mt-2">{t('empire_prod_only')}</div>
              </div>

              <div className={`rounded-xl border-2 p-4 text-center ${r.canBuyAll ? 'border-emerald-400 bg-emerald-50' : 'border-indigo-300 bg-indigo-50'}`}>
                <div className="text-xs text-slate-500 mb-1 font-medium">
                  <i className="fa-solid fa-coins mr-1 text-yellow-500" />{t('with_gold')}
                </div>
                <div className="text-xs text-yellow-700 font-semibold mb-2">{fmt(gold)} gold</div>
                <div className={`text-2xl font-bold ${r.canBuyAll ? 'text-emerald-600' : 'text-indigo-600'}`}>
                  {r.canBuyAll ? t('have_everything') : fmtHours(r.timeWithGold, t)}
                </div>
                {!r.canBuyAll && r.timeWithGold < r.timeNoGold && (
                  <div className="text-xs text-indigo-500 mt-2 font-semibold">
                    {t('saves', { t: fmtHours(r.timeNoGold - r.timeWithGold, t) })}
                  </div>
                )}
              </div>

              <div className={`rounded-xl border-2 p-4 text-center ${r.canBuyAll ? 'border-emerald-400 bg-emerald-50' : 'border-yellow-300 bg-yellow-50'}`}>
                <div className="text-xs text-slate-500 mb-1 font-medium">
                  <i className="fa-solid fa-bag-shopping mr-1" />{t('buy_all')}
                </div>
                <div className={`text-2xl font-bold mt-2 ${r.canBuyAll ? 'text-emerald-600' : 'text-yellow-700'}`}>
                  {fmt(r.goldNeededAll)} gold
                </div>
                <div className={`text-xs mt-2 font-semibold ${r.canBuyAll ? 'text-emerald-500' : 'text-red-500'}`}>
                  {r.canBuyAll ? t('have_enough_gold') : t('missing_gold_amount', { n: fmt(Math.round(r.goldNeededAll - gold)) })}
                </div>
              </div>
            </div>
          </div>
        </Card>
      )}
    </div>
  )
}
