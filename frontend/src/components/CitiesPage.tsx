import { useState } from 'react'
import { useT, useLang } from '../i18n'
import { fmt, fmtDuration, exportCsv } from '../utils'
import { MATERIALS } from '../constants'
import { Card } from './ui/Card'
import { PageHeader } from './ui/PageHeader'
import { Th, Td } from './ui/TableCells'
import { CitySelect } from './ui/CitySelect'
import { StorageBar } from './StorageBar'
import { RefreshButton } from './ui/RefreshButton'
import type { ApiData } from '../types'

export function CitiesPage({ data, onRefresh }: { data: ApiData; onRefresh?: () => void }) {
  const t = useT()
  const lang = useLang() as 'pt' | 'en'
  const { resourcesData } = data
  const cities = Object.keys(resourcesData)
  const [filter, setFilter] = useState('all')
  const visible = filter === 'all' ? cities : cities.filter(c => c === filter)

  const handleExport = () => {
    const header = [t('col_city'), ...MATERIALS.map(m => m[lang]), t('col_warehouse'), t('csv_wine_prod'), t('csv_wine_cons'), t('csv_wine_ends')]
    const rows = [header, ...visible.map(city => {
      const d = resourcesData[city]
      const wineRunsOut = d.wineRunsOutIn === -1 ? '∞' : fmtDuration(d.wineRunsOutIn)
      return [
        city,
        ...MATERIALS.map(m => d[m.en as keyof typeof d] ?? ''),
        d.storageCapacity ?? '',
        d.wineProductionPerHour ?? '',
        d.wineConsumptionPerHour ?? '',
        wineRunsOut,
      ]
    })]
    exportCsv(`resources_${new Date().toISOString().slice(0,10)}.csv`, rows as (string | number)[][])
  }

  return (
    <div>
      <PageHeader icon="fa-city" title={t('cities_title')}>
        <div className="flex items-center gap-2">
          {onRefresh && <RefreshButton onRefresh={onRefresh} />}
          <CitySelect cities={cities} value={filter} onChange={setFilter} />
          <button
            onClick={handleExport}
            className="flex items-center gap-1.5 px-3 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-medium rounded-lg transition-colors"
          >
            <i className="fa-solid fa-file-csv" /> CSV
          </button>
        </div>
      </PageHeader>

      <Card>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="bg-slate-800 text-white text-xs uppercase tracking-wide">
                <Th align="text-left" className="px-5">{t('col_city')}</Th>
                {MATERIALS.map(m => (
                  <Th key={m.en}>
                    <i className={`fa-solid ${m.icon} mr-1 ${m.color}`} /> {m[lang]}
                  </Th>
                ))}
                <Th><i className="fa-solid fa-wine-glass mr-1 text-red-400" /> {t('col_wine')}</Th>
                <Th>{t('col_warehouse')}</Th>
              </tr>
            </thead>
            <tbody>
              {visible.map((city, i) => {
                const d = resourcesData[city]
                const cap = d.storageCapacity || 0
                const wineRunsOut = d.wineRunsOutIn
                const wineUrgent = wineRunsOut !== -1 && wineRunsOut !== undefined && wineRunsOut < 4 * 3600
                const wineWarning = wineRunsOut !== -1 && wineRunsOut !== undefined && wineRunsOut < 12 * 3600

                return (
                  <tr key={city} className={`border-b border-slate-100 hover:bg-indigo-50/60 transition-colors ${i % 2 ? 'bg-slate-50/50' : ''}`}>
                    <Td className="px-5 font-semibold text-slate-700">{city}</Td>
                    {MATERIALS.map(m => (
                      <Td key={m.en} className="text-center">
                        <StorageBar value={d[m.en as keyof typeof d] as number} capacity={cap} />
                      </Td>
                    ))}
                    <Td className={`text-center font-mono text-xs ${wineUrgent ? 'text-red-600 font-bold' : wineWarning ? 'text-yellow-600 font-semibold' : 'text-slate-500'}`}>
                      {wineUrgent && <i className="fa-solid fa-triangle-exclamation mr-1" />}
                      {fmtDuration(wineRunsOut)}
                      <div className="text-[10px] text-slate-400">
                        {fmt(d.wineProductionPerHour)}/{fmt(d.wineConsumptionPerHour)} /h
                      </div>
                    </Td>
                    <Td className="text-center text-xs font-mono text-slate-500">
                      {fmt(cap)}
                    </Td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Card>
      <p className="text-xs text-slate-400 mt-2">{t('resources_note')}</p>
    </div>
  )
}
