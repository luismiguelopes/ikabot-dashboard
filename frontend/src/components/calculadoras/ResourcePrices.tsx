import { useState } from 'react'
import { useT, useLang } from '../../i18n'
import { MATERIALS } from '../../constants'
import { NumInput } from './BuildingUpgradeCalc'

// Gold value of each resource (P13.54). The calculators had ONE "gold price per unit" that
// multiplied the cost and the gain alike, so it cancelled out of every payback and treated
// marble, crystal and wood as worth the same. Kept in the browser, shared by every calculator.
const KEY = 'ikabot_calc_prices'
const DEFAULT = [15, 15, 15, 15, 15]

function load(): number[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || 'null')
    if (Array.isArray(v) && v.length === 5 && v.every(n => typeof n === 'number' && n > 0)) return v
  } catch { /* storage blocked or bad value */ }
  return [...DEFAULT]
}

export function useResourcePrices(): [number[], (i: number, v: number) => void] {
  const [prices, setPrices] = useState<number[]>(load)
  const set = (i: number, v: number) => setPrices(prev => {
    // 0 is allowed while typing (the field shows empty); only complete prices are remembered
    const next = prev.map((p, j) => (j === i ? Math.max(0, v || 0) : p))
    if (next.every(n => n > 0)) {
      try { localStorage.setItem(KEY, JSON.stringify(next)) } catch { /* not persisted */ }
    }
    return next
  })
  return [prices, set]
}

/** Gold value of a 5-resource cost [wood, wine, marble, crystal, sulfur]. */
export function goldValue(cost5: number[], prices: number[]): number {
  return cost5.reduce((s, v, i) => s + (v || 0) * (prices[i] || 0), 0)
}

export function ResourcePricesInput({ prices, onChange }: { prices: number[]; onChange: (i: number, v: number) => void }) {
  const t = useT()
  const lang = useLang() as 'pt' | 'en'
  return (
    <div className="w-full">
      <p className="text-xs font-medium text-slate-500 mb-2 flex items-center gap-1">
        <i className="fa-solid fa-coins text-yellow-500" /> {t('calc_prices_title')}
      </p>
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        {MATERIALS.map((m, i) => (
          <NumInput key={m.en} label={<><i className={`fa-solid ${m.icon} ${m.color}`} /> {m[lang]}</>}
            value={prices[i]} onChange={v => onChange(i, v)} min={0.01} step={0.5} />
        ))}
      </div>
      <p className="text-[11px] text-slate-400 mt-1.5">{t('calc_prices_hint')}</p>
    </div>
  )
}
