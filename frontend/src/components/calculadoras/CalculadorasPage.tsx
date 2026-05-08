import { useState } from 'react'
import { useT } from '../../i18n'
import { PageHeader } from '../ui/PageHeader'
import { BuildingUpgradeCalc } from './BuildingUpgradeCalc'
import { ROICalc } from './ROICalc'
import { ColonyROICalc } from './ColonyROICalc'
import type { ApiData } from '../../types'

export function CalculadorasPage({ data }: { data: ApiData | null }) {
  const t = useT()
  const [tab, setTab] = useState('upgrade')
  const tabs = [
    { key: 'upgrade', label: t('tab_upgrade'), icon: 'fa-building-columns' },
    { key: 'roi',     label: t('tab_roi'),     icon: 'fa-scale-balanced'   },
    { key: 'colony',  label: t('tab_colony'),  icon: 'fa-ship'             },
  ]
  return (
    <div>
      <PageHeader icon="fa-calculator" title={t('calc_title')} />
      <div className="flex gap-2 mb-6 flex-wrap">
        {tabs.map(tb => (
          <button
            key={tb.key}
            onClick={() => setTab(tb.key)}
            className={`flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg border transition-colors ${
              tab === tb.key
                ? 'bg-indigo-600 text-white border-indigo-600 shadow'
                : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
            }`}
          >
            <i className={`fa-solid ${tb.icon}`} />
            {tb.label}
          </button>
        ))}
      </div>
      {tab === 'upgrade' && data && <BuildingUpgradeCalc data={data} />}
      {tab === 'roi'     && data && <ROICalc data={data} />}
      {tab === 'colony'  && data && <ColonyROICalc data={data} />}
    </div>
  )
}
