import { useState } from 'react'
import { useT, useLang } from '../i18n'
import { ALERT_DEFAULTS } from '../constants'
import { PageHeader } from './ui/PageHeader'
import { Card } from './ui/Card'
import type { AlertThresholds } from '../types'

const NAV_OPTIONS = [
  'home', 'cities', 'buildings', 'movements', 'alerts',
  'history', 'calc', 'construction', 'mundo',
] as const
type NavKey = typeof NAV_OPTIONS[number]
const NAV_LABEL_KEYS: Record<NavKey, string> = {
  home: 'nav_home', cities: 'nav_cities', buildings: 'nav_buildings',
  movements: 'nav_movements', alerts: 'nav_alerts', history: 'nav_history',
  calc: 'nav_calculators', construction: 'nav_construction', mundo: 'nav_world',
}

function ThresholdRow({ label, value, onChange, min, max, unit }: {
  label: string; value: number; onChange: (v: number) => void; min: number; max: number; unit: string
}) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-slate-100 last:border-0">
      <span className="text-sm text-slate-600">{label}</span>
      <div className="flex items-center gap-2">
        <input
          type="number"
          min={min} max={max}
          value={value}
          onChange={e => onChange(Math.max(min, Math.min(max, Number(e.target.value))))}
          className="w-20 border border-slate-200 rounded-lg px-2 py-1 text-sm text-center bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400"
        />
        <span className="text-sm text-slate-400 w-4">{unit}</span>
      </div>
    </div>
  )
}

function GeralTab({ toggleLang, defaultTab, onSaveDefaultTab }: {
  toggleLang: () => void
  defaultTab: string
  onSaveDefaultTab: (tab: string) => void
}) {
  const t = useT()
  const lang = useLang()

  return (
    <div className="grid gap-4 max-w-lg">
      <Card>
        <div className="px-5 py-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-4">{t('settings_language')}</p>
          <div className="flex gap-2">
            {(['en', 'pt'] as const).map(l => (
              <button
                key={l}
                onClick={() => { if (l !== lang) toggleLang() }}
                className={`flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium border transition-colors ${
                  lang === l
                    ? 'bg-indigo-600 text-white border-indigo-600 shadow'
                    : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
                }`}
              >
                <i className="fa-solid fa-language" />
                {l === 'en' ? 'English' : 'Português'}
              </button>
            ))}
          </div>
        </div>
      </Card>

      <Card>
        <div className="px-5 py-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-4">{t('settings_default_tab')}</p>
          <select
            value={defaultTab}
            onChange={e => onSaveDefaultTab(e.target.value)}
            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400"
          >
            {NAV_OPTIONS.map(key => (
              <option key={key} value={key}>{t(NAV_LABEL_KEYS[key])}</option>
            ))}
          </select>
          <p className="mt-2 text-xs text-slate-400">Guardado no browser. Activo na próxima vez que abrires o dashboard.</p>
        </div>
      </Card>
    </div>
  )
}

function AlertasTab({ thresholds, onSaveThresholds }: {
  thresholds: AlertThresholds
  onSaveThresholds: (t: AlertThresholds) => void
}) {
  const t = useT()
  const [draft, setDraft] = useState(thresholds)
  const isDirty = JSON.stringify(draft) !== JSON.stringify(thresholds)

  return (
    <div className="grid gap-4 max-w-lg">
      <Card>
        <div className="px-5 py-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1 flex items-center gap-1.5">
            <i className="fa-solid fa-wine-bottle text-red-400" /> {t('wine_group')}
          </p>
          <ThresholdRow label={t('warning_below')}  value={draft.wineWarning}   onChange={v => setDraft(d => ({ ...d, wineWarning: v }))}   min={1}  max={72} unit="h" />
          <ThresholdRow label={t('critical_below')} value={draft.wineCritical}  onChange={v => setDraft(d => ({ ...d, wineCritical: v }))}  min={1}  max={24} unit="h" />
        </div>
      </Card>

      <Card>
        <div className="px-5 py-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1 flex items-center gap-1.5">
            <i className="fa-solid fa-warehouse text-slate-400" /> {t('storage_group')}
          </p>
          <ThresholdRow label={t('warning_above')} value={draft.storageWarning} onChange={v => setDraft(d => ({ ...d, storageWarning: v }))} min={50} max={99} unit="%" />
        </div>
      </Card>

      <div className="flex gap-2">
        <button
          onClick={() => onSaveThresholds(draft)}
          disabled={!isDirty}
          className="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white text-sm font-medium rounded-lg transition-colors"
        >
          {t('save')}
        </button>
        <button
          onClick={() => setDraft({ ...ALERT_DEFAULTS })}
          className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700 bg-white hover:bg-slate-50 border border-slate-200 rounded-lg transition-colors"
        >
          {t('reset')}
        </button>
      </div>
      <p className="text-xs text-slate-400">
        {t('thresholds_note', { ww: String(ALERT_DEFAULTS.wineWarning), wc: String(ALERT_DEFAULTS.wineCritical), sw: String(ALERT_DEFAULTS.storageWarning) })}
      </p>
    </div>
  )
}

function NotificacoesTab() {
  const t = useT()
  const notifItems = [
    'settings_notif_offline',
    'settings_notif_construction',
    'settings_notif_transport_error',
    'settings_notif_wine_critical',
  ] as const

  return (
    <div className="grid gap-4 max-w-lg">
      <Card>
        <div className="px-5 py-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-4 flex items-center gap-1.5">
            <i className="fa-brands fa-telegram text-sky-500" /> {t('settings_telegram_title')}
          </p>
          <div className="space-y-3 opacity-50 pointer-events-none">
            <div>
              <label className="block text-xs text-slate-500 mb-1">{t('settings_telegram_token')}</label>
              <input
                type="text"
                disabled
                placeholder="123456:ABC-DEF…"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1">{t('settings_telegram_chatid')}</label>
              <input
                type="text"
                disabled
                placeholder="-100123456789"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white"
              />
            </div>
          </div>
        </div>
      </Card>

      <Card>
        <div className="px-5 py-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">Alertas</p>
          <div className="space-y-3 opacity-50 pointer-events-none">
            {notifItems.map(key => (
              <label key={key} className="flex items-center gap-3">
                <input type="checkbox" disabled className="rounded accent-indigo-600 w-4 h-4" />
                <span className="text-sm text-slate-600">{t(key)}</span>
              </label>
            ))}
          </div>
        </div>
      </Card>

      <div className="flex items-center gap-2 text-sm text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
        <i className="fa-solid fa-clock flex-shrink-0" />
        {t('settings_telegram_note')}
      </div>
    </div>
  )
}

export function SettingsPage({ thresholds, onSaveThresholds, toggleLang, defaultTab, onSaveDefaultTab }: {
  thresholds: AlertThresholds
  onSaveThresholds: (t: AlertThresholds) => void
  toggleLang: () => void
  defaultTab: string
  onSaveDefaultTab: (tab: string) => void
}) {
  const t = useT()
  const [tab, setTab] = useState('geral')

  const tabs = [
    { key: 'geral',        label: t('settings_tab_general'),       icon: 'fa-sliders'    },
    { key: 'alertas',      label: t('settings_tab_alerts'),        icon: 'fa-bell'       },
    { key: 'notificacoes', label: t('settings_tab_notifications'), icon: 'fa-paper-plane' },
  ]

  return (
    <div>
      <PageHeader icon="fa-gear" title={t('settings')} />
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

      {tab === 'geral'        && <GeralTab        toggleLang={toggleLang} defaultTab={defaultTab} onSaveDefaultTab={onSaveDefaultTab} />}
      {tab === 'alertas'      && <AlertasTab      thresholds={thresholds} onSaveThresholds={onSaveThresholds} />}
      {tab === 'notificacoes' && <NotificacoesTab />}
    </div>
  )
}
