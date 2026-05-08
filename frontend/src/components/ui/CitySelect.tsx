import { useT } from '../../i18n'

export function CitySelect({ cities, value, onChange }: { cities: string[]; value: string; onChange: (v: string) => void }) {
  const t = useT()
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      className="border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 text-slate-700"
    >
      <option value="all">{t('all_cities')}</option>
      {cities.map(c => <option key={c} value={c}>{c}</option>)}
    </select>
  )
}
