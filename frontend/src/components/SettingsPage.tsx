import { useState, useEffect } from 'react'
import { useT, useLang } from '../i18n'
import { saveBrowserNotifEnabled } from '../hooks/useNotifications'
import { ALERT_DEFAULTS, MATERIALS } from '../constants'
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

function ConstrucaoTab() {
  const t    = useT()
  const lang = useLang() as 'pt' | 'en'
  const [hoursStart,   setHoursStart]   = useState(0)
  const [hoursEnd,     setHoursEnd]     = useState(24)
  const [buffer,       setBuffer]       = useState([0, 0, 0, 0, 0])
  const [wineMinHours, setWineMinHours] = useState(0)
  const [saved,        setSaved]        = useState(false)
  const [saving,       setSaving]       = useState(false)
  const [loaded,       setLoaded]       = useState(false)

  useEffect(() => {
    fetch('/api/building-queue')
      .then(r => r.json())
      .then(d => {
        if (d.activeHours) { setHoursStart(d.activeHours.start); setHoursEnd(d.activeHours.end) }
        if (d.resourceBuffer?.length === 5) setBuffer(d.resourceBuffer)
        if (d.wineMinHours != null) setWineMinHours(d.wineMinHours)
        setLoaded(true)
      })
      .catch(() => setLoaded(true))
  }, [])

  const handleSave = () => {
    setSaving(true)
    fetch('/api/building-queue/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        activeHours: { start: hoursStart, end: hoursEnd },
        resourceBuffer: buffer,
        wineMinHours,
      }),
    })
      .then(() => { setSaved(true); setTimeout(() => setSaved(false), 3000) })
      .catch(() => {})
      .finally(() => setSaving(false))
  }

  if (!loaded) return <div className="text-sm text-slate-400 mt-4">{t('loading')}</div>

  return (
    <div className="grid gap-4 max-w-lg">
      {/* Active Hours */}
      <Card>
        <div className="px-5 py-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1 flex items-center gap-1.5">
            <i className="fa-solid fa-clock text-indigo-400" /> {t('queue_active_hours_title')}
          </p>
          <p className="text-xs text-slate-400 mb-4">{t('queue_active_hours_hint')}</p>
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-sm text-slate-600">{t('queue_active_hours_from')}</span>
            <input
              type="number" min={0} max={23} value={hoursStart}
              onChange={e => setHoursStart(Math.min(23, Math.max(0, Number(e.target.value))))}
              className="w-16 border border-slate-200 rounded-lg px-2 py-1.5 text-sm text-center bg-white font-mono focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
            <span className="text-sm text-slate-400">h</span>
            <span className="text-sm text-slate-600">{t('queue_active_hours_to')}</span>
            <input
              type="number" min={1} max={24} value={hoursEnd}
              onChange={e => setHoursEnd(Math.min(24, Math.max(1, Number(e.target.value))))}
              className="w-16 border border-slate-200 rounded-lg px-2 py-1.5 text-sm text-center bg-white font-mono focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
            <span className="text-sm text-slate-400">h</span>
            <span className="text-xs text-slate-400">(0–24)</span>
          </div>
        </div>
      </Card>

      {/* Resource Buffer */}
      <Card>
        <div className="px-5 py-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1 flex items-center gap-1.5">
            <i className="fa-solid fa-shield-halved text-amber-400" /> {t('queue_buffer_title')}
          </p>
          <p className="text-xs text-slate-400 mb-4">{t('queue_buffer_hint')}</p>
          <div className="space-y-2.5">
            {MATERIALS.map((m, i) => (
              <div key={m.en} className="flex items-center gap-3">
                <span className="flex items-center gap-1.5 w-28 text-sm font-medium text-slate-600 shrink-0">
                  <i className={`fa-solid ${m.icon} ${m.color}`} />
                  {m[lang]}
                </span>
                <input
                  type="number" min={0} step={1000} value={buffer[i]}
                  onChange={e => {
                    const next = [...buffer]
                    next[i] = Math.max(0, Number(e.target.value))
                    setBuffer(next)
                  }}
                  className="w-32 border border-slate-200 rounded-lg px-3 py-1.5 text-sm text-right bg-white font-mono focus:outline-none focus:ring-2 focus:ring-indigo-400"
                />
              </div>
            ))}
          </div>
        </div>
      </Card>

      {/* Wine Minimum */}
      <Card>
        <div className="px-5 py-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1 flex items-center gap-1.5">
            <i className="fa-solid fa-wine-bottle text-red-400" /> {t('queue_wine_min_title')}
          </p>
          <p className="text-xs text-slate-400 mb-4">{t('queue_wine_min_hint')}</p>
          <div className="flex items-center gap-3">
            <input
              type="number" min={0} max={72} value={wineMinHours}
              onChange={e => setWineMinHours(Math.max(0, Math.min(72, Number(e.target.value))))}
              className="w-20 border border-slate-200 rounded-lg px-2 py-1 text-sm text-center bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
            <span className="text-sm text-slate-400">h</span>
            {wineMinHours > 0 && (
              <span className="text-xs text-red-500 font-medium flex items-center gap-1">
                <i className="fa-solid fa-triangle-exclamation" />
                {`< ${wineMinHours}h → skip`}
              </span>
            )}
          </div>
        </div>
      </Card>

      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white text-sm font-medium rounded-lg transition-colors flex items-center gap-2"
        >
          {saving && <i className="fa-solid fa-spinner animate-spin text-xs" />}
          {t('save')}
        </button>
        {saved && <span className="text-sm text-emerald-600 font-medium">✓ {t('queue_settings_saved').replace('✓ ', '')}</span>}
      </div>
    </div>
  )
}

function NotificacoesTab({ notifEnabled, onToggleNotif }: {
  notifEnabled: boolean
  onToggleNotif: (v: boolean) => void
}) {
  const t = useT()
  const [permission, setPermission] = useState<NotificationPermission>(
    'Notification' in window ? Notification.permission : 'denied'
  )

  const handleEnable = async () => {
    if (!('Notification' in window)) return
    const result = await Notification.requestPermission()
    setPermission(result)
    if (result === 'granted') onToggleNotif(true)
  }

  const notifItems = [
    'settings_notif_wine_critical',
    'settings_notif_offline',
    'settings_notif_construction',
    'settings_notif_transport_error',
  ] as const

  return (
    <div className="grid gap-4 max-w-lg">
      {/* Browser notifications */}
      <Card>
        <div className="px-5 py-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-4 flex items-center gap-1.5">
            <i className="fa-solid fa-bell text-indigo-500" /> {t('notif_browser_title')}
          </p>

          {!('Notification' in window) ? (
            <p className="text-sm text-slate-400">Não suportado neste browser.</p>
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
                <button
                  onClick={() => onToggleNotif(!notifEnabled)}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${notifEnabled ? 'bg-indigo-600' : 'bg-slate-200'}`}
                >
                  <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${notifEnabled ? 'translate-x-6' : 'translate-x-1'}`} />
                </button>
              </div>
              <div className="space-y-2 pl-1">
                {notifItems.map(key => (
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

      {/* Telegram skeleton */}
      <Card>
        <div className="px-5 py-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-4 flex items-center gap-1.5">
            <i className="fa-brands fa-telegram text-sky-500" /> {t('settings_telegram_title')}
          </p>
          <div className="space-y-3 opacity-50 pointer-events-none">
            <div>
              <label className="block text-xs text-slate-500 mb-1">{t('settings_telegram_token')}</label>
              <input type="text" disabled placeholder="123456:ABC-DEF…"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white" />
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1">{t('settings_telegram_chatid')}</label>
              <input type="text" disabled placeholder="-100123456789"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white" />
            </div>
          </div>
          <div className="mt-3 flex items-center gap-2 text-sm text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
            <i className="fa-solid fa-clock shrink-0" /> {t('settings_telegram_note')}
          </div>
        </div>
      </Card>
    </div>
  )
}

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
    { key: 'notificacoes', label: t('settings_tab_notifications'), icon: 'fa-paper-plane'  },
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
      {tab === 'construcao'   && <ConstrucaoTab />}
      {tab === 'notificacoes' && <NotificacoesTab notifEnabled={notifEnabled} onToggleNotif={handleToggleNotif} />}
    </div>
  )
}
