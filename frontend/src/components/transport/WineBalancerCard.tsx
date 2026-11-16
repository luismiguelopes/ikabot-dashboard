import { useT } from '../../i18n'
import { Card, CardHeader } from '../ui/Card'
import { LabeledNumber, SaveRow, ToggleLabel } from './shared'
import type { SettingsState } from '../../hooks/useSettings'
import type { WineSettings } from './types'

// Wine balancer (F9) + the trade-ship reserve for wine against the farm (P11.10).
// The settings object comes from the page: the wine panorama reads the same values.
export function WineBalancerCard({ settings }: { settings: SettingsState<WineSettings> }) {
  const t = useT()
  const { data: wine, set, save, saving, saved } = settings
  const reserveOn = wine?.reserveShipsFromFarm ?? true

  return (
    <Card className="mb-4">
      <CardHeader icon="fa-wine-bottle" title={t('wine_title')} />
      <div className="p-4 space-y-4">
        <p className="text-xs text-slate-500">{t('wine_hint')}</p>
        {wine && (
          <>
            <ToggleLabel on={wine.enabled} onChange={v => set({ enabled: v })} label={t('transport_enabled')} />

            <div className="grid grid-cols-3 gap-3 max-w-xl">
              <LabeledNumber label={t('wine_threshold')} value={wine.thresholdHours} min={1} max={168}
                onCommit={v => set({ thresholdHours: v })} />
              <LabeledNumber label={t('wine_target')} value={wine.targetHours} min={1} max={336}
                onCommit={v => set({ targetHours: v })} />
              <LabeledNumber label={t('wine_donor_reserve')} value={wine.donorReserveHours ?? 96} min={1} max={720}
                onCommit={v => set({ donorReserveHours: v })} />
            </div>

            <div className="border-t border-slate-100 pt-3 space-y-3">
              <ToggleLabel on={reserveOn} onChange={v => set({ reserveShipsFromFarm: v })} label={t('wine_ship_reserve')} />
              <p className="text-xs text-slate-500 max-w-xl">{t('wine_ship_reserve_hint')}</p>
              {reserveOn && (
                <div className="grid grid-cols-2 gap-3 max-w-md">
                  <LabeledNumber label={t('wine_reserve_ships')} value={wine.reserveShips ?? 5} min={0} max={100}
                    onCommit={v => set({ reserveShips: v })} />
                </div>
              )}
            </div>

            <SaveRow onSave={() => save()} saving={saving} saved={saved} />
          </>
        )}
      </div>
    </Card>
  )
}
