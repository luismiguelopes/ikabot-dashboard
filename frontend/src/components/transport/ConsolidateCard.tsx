import { useT, useLang } from '../../i18n'
import { fmt, fmtArrival } from '../../utils'
import { useSettings } from '../../hooks/useSettings'
import { Card, CardHeader } from '../ui/Card'
import { LabeledNumber, SaveRow, ToggleLabel } from './shared'
import { LABEL_CLS, SELECT_CLS } from './types'
import type { ConsolidateSettings } from './types'
import type { OwnCity } from '../../types'

const SHIP_ICON = { transporters: 'fa-sailboat', freighters: 'fa-ferry', both: 'fa-layer-group' } as const
const SHIP_LABEL = {
  transporters: 'transport_ship_type_transporters',
  freighters: 'transport_ship_type_freighters',
  both: 'transport_ship_type_both',
} as const

// Periodic consolidation of resources into one city.
export function ConsolidateCard({ ownCities }: { ownCities: OwnCity[] }) {
  const t    = useT()
  const lang = useLang() as 'pt' | 'en'
  const { data: c, set, save, saving, saved } = useSettings<ConsolidateSettings>('/api/transport/consolidate')

  return (
    <Card>
      <CardHeader icon="fa-warehouse" title={t('transport_consolidate')} />
      <div className="p-4 space-y-4">
        <p className="text-xs text-slate-500">{t('transport_consolidate_hint')}</p>
        {c && (
          <>
            <ToggleLabel on={c.enabled} onChange={v => set({ enabled: v })} label={t('transport_enabled')} />

            <label className="block">
              <span className={LABEL_CLS}>{t('transport_dest')}</span>
              <select
                className={SELECT_CLS}
                value={c.destCityId}
                onChange={e => {
                  const city = ownCities.find(x => String(x.cityId) === e.target.value)
                  set({ destCityId: e.target.value, destCityName: city?.name ?? '' })
                }}
              >
                <option value="">—</option>
                {ownCities.map(city => (
                  <option key={city.cityId} value={String(city.cityId)}>{city.name}</option>
                ))}
              </select>
            </label>

            <div className="grid grid-cols-2 gap-3">
              <LabeledNumber label={t('transport_interval')} value={c.intervalHours} min={1} max={48}
                onCommit={v => set({ intervalHours: v })} />
              <LabeledNumber label={t('transport_min_send')} value={c.minSendTotal} min={0} step={500}
                onCommit={v => set({ minSendTotal: v })} />
            </div>

            <div>
              <span className={LABEL_CLS}>{t('transport_consolidate_ships')}</span>
              <div className="flex gap-2">
                {(['transporters', 'freighters', 'both'] as const).map(st => (
                  <button
                    key={st}
                    onClick={() => set({ shipType: st })}
                    aria-pressed={c.shipType === st}
                    className={`flex-1 py-2 rounded-lg text-xs font-medium border transition-colors ${
                      c.shipType === st
                        ? 'bg-indigo-600 text-white border-indigo-600'
                        : 'bg-white text-slate-600 border-slate-200 hover:border-indigo-300'
                    }`}
                  >
                    <i className={`fa-solid ${SHIP_ICON[st]} mr-1`} />
                    {t(SHIP_LABEL[st])}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <span className={LABEL_CLS}>{t('transport_consolidate_ignore')}</span>
              <p className="text-xs text-slate-400 mb-2">{t('transport_consolidate_ignore_hint')}</p>
              <div className="flex flex-wrap gap-2">
                {ownCities
                  .filter(city => String(city.cityId) !== c.destCityId)
                  .map(city => {
                    const id = String(city.cityId)
                    const cur = c.ignoreCityIds || []
                    const on = cur.includes(id)
                    return (
                      <button
                        key={city.cityId}
                        aria-pressed={on}
                        onClick={() => set({ ignoreCityIds: on ? cur.filter(x => x !== id) : [...cur, id] })}
                        className={`px-2.5 py-1 rounded-full text-xs font-medium border transition-colors ${
                          on
                            ? 'bg-amber-500 text-white border-amber-500'
                            : 'bg-white text-slate-600 border-slate-200 hover:border-amber-300'
                        }`}
                      >
                        {on && <i className="fa-solid fa-ban mr-1" />}
                        {city.name}
                      </button>
                    )
                  })}
              </div>
            </div>

            <div className="text-xs text-slate-400">
              {t('transport_last_run')}: {c.lastRun ? fmtArrival(c.lastRun, lang) : t('transport_never')}
              {c.lastSent && Object.keys(c.lastSent).length > 0 && (
                <span className="ml-2">
                  ({Object.entries(c.lastSent).map(([city, v]) => `${city}: ${fmt(v)}`).join(', ')})
                </span>
              )}
            </div>

            <SaveRow onSave={() => save()} saving={saving} saved={saved} />
          </>
        )}
      </div>
    </Card>
  )
}
