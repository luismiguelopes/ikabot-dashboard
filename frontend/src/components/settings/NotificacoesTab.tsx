import { useState } from 'react'
import { useT } from '../../i18n'
import { Card } from '../ui/Card'
import { Toggle } from '../ui/Toggle'
import { CardTitle } from './shared'
import { TelegramCard } from './TelegramCard'
import { SpyBuildCard } from './SpyBuildCard'
import { CombatAlertsCard } from './CombatAlertsCard'

const NOTIF_ITEMS = [
  'settings_notif_wine_critical',
  'settings_notif_offline',
  'settings_notif_construction',
  'settings_notif_transport_error',
] as const

function BrowserNotifCard({ notifEnabled, onToggleNotif }: {
  notifEnabled: boolean
  onToggleNotif: (v: boolean) => void
}) {
  const t = useT()
  const supported = 'Notification' in window
  const [permission, setPermission] = useState<NotificationPermission>(supported ? Notification.permission : 'denied')

  const handleEnable = async () => {
    if (!supported) return
    const result = await Notification.requestPermission()
    setPermission(result)
    if (result === 'granted') onToggleNotif(true)
  }

  return (
    <Card>
      <div className="px-5 py-4">
        <CardTitle icon="fa-bell text-indigo-500">{t('notif_browser_title')}</CardTitle>
        {!supported ? (
          <p className="text-sm text-slate-400">{t('notif_browser_unsupported')}</p>
        ) : permission === 'denied' ? (
          <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2.5">
            <i className="fa-solid fa-ban shrink-0" />
            {t('notif_browser_denied')}
          </div>
        ) : permission === 'default' ? (
          <button
            onClick={handleEnable}
            className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg transition-colors"
          >
            <i className="fa-solid fa-bell" /> {t('notif_allow_btn')}
          </button>
        ) : (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-emerald-600 font-medium flex items-center gap-1.5">
                <i className="fa-solid fa-circle-check" /> {t('notif_browser_granted')}
              </span>
              <Toggle on={notifEnabled} onChange={onToggleNotif} label={t('notif_browser_title')} />
            </div>
            <div className="space-y-2 pl-1">
              {NOTIF_ITEMS.map(key => (
                <div key={key} className="flex items-center gap-2 text-sm text-slate-500">
                  <i className="fa-solid fa-check text-xs text-indigo-400 w-3" />
                  {t(key)}
                </div>
              ))}
            </div>
            <p className="text-xs text-slate-400">{t('notif_browser_note')}</p>
          </div>
        )}
      </div>
    </Card>
  )
}

export function NotificacoesTab({ notifEnabled, onToggleNotif }: {
  notifEnabled: boolean
  onToggleNotif: (v: boolean) => void
}) {
  return (
    <div className="grid gap-4 max-w-lg">
      <BrowserNotifCard notifEnabled={notifEnabled} onToggleNotif={onToggleNotif} />
      <TelegramCard />
      <SpyBuildCard />
      <CombatAlertsCard />
    </div>
  )
}
