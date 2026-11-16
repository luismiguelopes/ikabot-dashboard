import { useT } from '../../i18n'
import { useSettings } from '../../hooks/useSettings'
import { Card } from '../ui/Card'
import { CardTitle, NumberRow, SavedBadge, ToggleRow } from './shared'

interface WatchlistSettings { enabled: boolean; intervalHours: number }

export function WatchlistCard() {
  const t = useT()
  const { data: s, saveNow, saved } = useSettings<WatchlistSettings>('/api/watchlist')
  if (!s) return null
  return (
    <Card>
      <div className="px-5 py-4">
        <CardTitle icon="fa-binoculars text-indigo-500" className="mb-3" right={<SavedBadge show={saved} />}>{t('watchlist_title')}</CardTitle>
        <p className="text-xs text-slate-400 mb-3">{t('watchlist_hint')}</p>
        <div className="space-y-3">
          <ToggleRow label={t('transport_enabled')} on={s.enabled} onChange={v => saveNow({ enabled: v })} />
          <NumberRow label={t('watchlist_interval')} value={s.intervalHours} min={1} max={168} width="w-20"
            onCommit={v => saveNow({ intervalHours: v })} />
        </div>
      </div>
    </Card>
  )
}
