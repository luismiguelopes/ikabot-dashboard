import { useState } from 'react'
import { useT } from '../i18n'
import { saveBrowserNotifEnabled } from '../hooks/useNotifications'
import { PageHeader } from './ui/PageHeader'
import { LogoutButton } from './AuthGate'
import { GeralTab } from './settings/GeralTab'
import { AlertasTab } from './settings/AlertasTab'
import { ConstrucaoTab } from './settings/ConstrucaoTab'
import { EspionagemTab } from './settings/EspionagemTab'
import { NotificacoesTab } from './settings/NotificacoesTab'
import type { AlertThresholds } from '../types'


export function SettingsPage({ thresholds, onSaveThresholds, toggleLang, defaultTab, onSaveDefaultTab, notifEnabled, onToggleNotif }: {
  thresholds: AlertThresholds
  onSaveThresholds: (t: AlertThresholds) => void
  toggleLang: () => void
  defaultTab: string
  onSaveDefaultTab: (tab: string) => void
  notifEnabled: boolean
  onToggleNotif: (v: boolean) => void
}) {
  const t = useT()
  const [tab, setTab] = useState('geral')

  const handleToggleNotif = (v: boolean) => {
    onToggleNotif(v)
    saveBrowserNotifEnabled(v)
  }

  const tabs = [
    { key: 'geral',        label: t('settings_tab_general'),       icon: 'fa-sliders'      },
    { key: 'alertas',      label: t('settings_tab_alerts'),        icon: 'fa-bell'         },
    { key: 'construcao',   label: t('nav_construction'),           icon: 'fa-hammer'       },
    { key: 'espionagem',   label: t('settings_tab_espionage'),     icon: 'fa-user-secret'  },
    { key: 'notificacoes', label: t('settings_tab_notifications'), icon: 'fa-paper-plane'  },
  ]

  return (
    <div>
      <PageHeader icon="fa-gear" title={t('settings')} />
      <div className="flex gap-2 mb-6 flex-wrap" role="tablist">
        {tabs.map(tb => (
          <button
            key={tb.key}
            role="tab"
            aria-selected={tab === tb.key}
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

      {tab === 'geral'        && <GeralTab        toggleLang={toggleLang} defaultTab={defaultTab} onSaveDefaultTab={onSaveDefaultTab} />}
      {tab === 'alertas'      && <AlertasTab      thresholds={thresholds} onSaveThresholds={onSaveThresholds} />}
      {tab === 'construcao'   && <ConstrucaoTab />}
      {tab === 'espionagem'   && <EspionagemTab />}
      {tab === 'notificacoes' && <NotificacoesTab notifEnabled={notifEnabled} onToggleNotif={handleToggleNotif} />}

      {tab === 'geral' && (
        <div className="mt-4">
          <LogoutButton />
        </div>
      )}
    </div>
  )
}
