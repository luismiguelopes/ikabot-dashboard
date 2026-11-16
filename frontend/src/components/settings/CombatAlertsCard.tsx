import { useT } from '../../i18n'
import { useSettings } from '../../hooks/useSettings'
import { Card } from '../ui/Card'
import { CardTitle, NumberRow, SavedBadge, ToggleRow } from './shared'

interface CombatAlertSettings { incomingEnabled: boolean; returnEnabled: boolean; checkMinutes: number }

export function CombatAlertsCard() {
  const t = useT()
  // This card used a plain fetch and said "saved" even on a 400/500 — now through useSettings.
  const { data: s, saveNow, saved } = useSettings<CombatAlertSettings>('/api/alert-settings')
  if (!s) return null

  return (
    <Card>
      <div className="px-5 py-4">
        <CardTitle icon="fa-tower-observation text-red-500" right={<SavedBadge show={saved} />}>{t('alerts_title')}</CardTitle>
        <div className="space-y-3">
          <ToggleRow label={t('alerts_incoming')} on={s.incomingEnabled} onChange={v => saveNow({ incomingEnabled: v })} />
          <ToggleRow label={t('alerts_return')}   on={s.returnEnabled}   onChange={v => saveNow({ returnEnabled: v })} />
          <NumberRow label={t('alerts_check')} value={s.checkMinutes} min={0} max={120} width="w-20"
            onCommit={v => saveNow({ checkMinutes: v })} />
          <p className="text-xs text-slate-400">{t('alerts_check_hint')}</p>
        </div>
      </div>
    </Card>
  )
}
