import { useState, useEffect } from 'react'
import { useT, useLang } from '../i18n'
import { saveBrowserNotifEnabled } from '../hooks/useNotifications'
import { ALERT_DEFAULTS, MATERIALS } from '../constants'
import { PageHeader } from './ui/PageHeader'
import { Card } from './ui/Card'
import { LogoutButton } from './AuthGate'
import type { AlertThresholds, OwnCity } from '../types'

const SPY_ORIGIN_KEY = 'spy_default_origin_city'
const SPY_AGENTS_KEY = 'spy_default_agents'

export function loadSpyDefaults(): { originCityId: string; numAgents: number } {
  return {
    originCityId: localStorage.getItem(SPY_ORIGIN_KEY) || '',
    numAgents: parseInt(localStorage.getItem(SPY_AGENTS_KEY) || '1') || 1,
  }
}

export function saveSpyDefaults(originCityId: string, numAgents: number) {
  localStorage.setItem(SPY_ORIGIN_KEY, originCityId)
  localStorage.setItem(SPY_AGENTS_KEY, String(numAgents))
}

const NAV_OPTIONS = [
  'home', 'cities', 'buildings', 'movements', 'alerts',
  'history', 'calc', 'construction', 'combate', 'mundo',
] as const
type NavKey = typeof NAV_OPTIONS[number]
const NAV_LABEL_KEYS: Record<NavKey, string> = {
  home: 'nav_home', cities: 'nav_cities', buildings: 'nav_buildings',
  movements: 'nav_movements', alerts: 'nav_alerts', history: 'nav_history',
  calc: 'nav_calculators', construction: 'nav_construction',
  combate: 'nav_combat', mundo: 'nav_world',
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
  const [hoursStart, setHoursStart] = useState(0)
  const [hoursEnd,   setHoursEnd]   = useState(24)
  const [buffer,     setBuffer]     = useState([0, 0, 0, 0, 0])
  const [saved,      setSaved]      = useState(false)
  const [saving,       setSaving]       = useState(false)
  const [loaded,       setLoaded]       = useState(false)

  useEffect(() => {
    fetch('/api/building-queue')
      .then(r => r.json())
      .then(d => {
        if (d.activeHours) { setHoursStart(d.activeHours.start); setHoursEnd(d.activeHours.end) }
        if (d.resourceBuffer?.length === 5) setBuffer(d.resourceBuffer)
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

type ChannelResult = boolean | null
const NOTIFY_LEVELS = ['activity', 'info', 'success', 'warning', 'error', 'critical'] as const
const NOTIFY_CATEGORIES = ['combat', 'farm', 'spy', 'wine', 'transport', 'build', 'system', 'digest'] as const
const INPUT_CLS = 'w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400 font-mono'

interface SpyBuildSettings {
  enabled: boolean; dryRun: boolean; targetPerCity: number; goldFloor: number
  crystalFloor: number; maxPerPass: number; intervalMinutes: number; maxCountsAgeMinutes: number
}
interface SpyBuildOrder { name: string; amount: number; gold: number; crystal: number; reason?: string }
interface SpyBuildStatus {
  at?: number; dryRun?: boolean; preview?: boolean; freeSlots?: number; ordered?: number
  spentGold?: number; spentCrystal?: number; orders?: SpyBuildOrder[]; failed?: SpyBuildOrder[]
  notes?: Record<string, string>
}

function SpyBuildCard() {
  const t = useT()
  const [s, setS] = useState<SpyBuildSettings | null>(null)
  const [st, setSt] = useState<SpyBuildStatus>({})
  const [saved, setSaved] = useState(false)
  const [previewing, setPreviewing] = useState(false)

  const loadStatus = () =>
    fetch('/api/espionage/spy-build/status').then(r => r.json()).then(setSt).catch(() => {})

  useEffect(() => {
    fetch('/api/espionage/spy-build').then(r => r.json()).then(setS).catch(() => {})
    loadStatus()
  }, [])

  if (!s) return null

  const save = (next: SpyBuildSettings) => {
    setS(next)
    fetch('/api/espionage/spy-build', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(next),
    }).then(() => { setSaved(true); setTimeout(() => setSaved(false), 2500) }).catch(() => {})
  }

  const preview = async () => {
    setPreviewing(true)
    const before = st.at || 0
    await fetch('/api/espionage/spy-build/preview', { method: 'POST' }).catch(() => {})
    for (let i = 0; i < 20; i++) {            // the bot picks the flag up within ≤60s
      await new Promise(r => setTimeout(r, 4000))
      const d: SpyBuildStatus = await fetch('/api/espionage/spy-build/status').then(r => r.json()).catch(() => ({}))
      if ((d.at || 0) > before) { setSt(d); break }
    }
    setPreviewing(false)
  }

  const fmt = (n?: number) => (n ?? 0).toLocaleString('pt-PT')
  const Toggle = ({ on, onClick }: { on: boolean; onClick: () => void }) => (
    <button onClick={onClick} className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${on ? 'bg-indigo-600' : 'bg-slate-200'}`}>
      <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${on ? 'translate-x-6' : 'translate-x-1'}`} />
    </button>
  )
  const num = (key: keyof SpyBuildSettings, label: string, min = 0) => (
    <div className="flex items-center justify-between gap-3">
      <span className="text-sm text-slate-600">{label}</span>
      <input type="number" min={min} value={s[key] as number}
        onChange={e => setS({ ...s, [key]: Math.max(min, Number(e.target.value)) })}
        onBlur={() => save(s)}
        className="w-28 border border-slate-200 rounded-lg px-2 py-1.5 text-sm text-right focus:outline-none focus:ring-2 focus:ring-indigo-400" />
    </div>
  )

  return (
    <Card>
      <div className="px-5 py-4">
        <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-4 flex items-center gap-1.5">
          <i className="fa-solid fa-user-secret text-slate-600" /> {t('spybuild_title')}
          {saved && <span className="ml-auto normal-case text-emerald-600 font-medium">✓ {t('settings_telegram_saved')}</span>}
        </p>
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm text-slate-600">{t('spybuild_enabled')}</span>
            <Toggle on={s.enabled} onClick={() => save({ ...s, enabled: !s.enabled })} />
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-slate-600">{t('spybuild_dry')}</span>
            <Toggle on={s.dryRun} onClick={() => save({ ...s, dryRun: !s.dryRun })} />
          </div>
          {!s.dryRun && <p className="text-xs text-amber-600">{t('spybuild_live_warning')}</p>}
          {num('targetPerCity', t('spybuild_target'))}
          {num('goldFloor', t('spybuild_gold_floor'))}
          {num('crystalFloor', t('spybuild_crystal_floor'))}
          {num('maxPerPass', t('spybuild_max_per_pass'), 1)}
          {num('intervalMinutes', t('spybuild_interval'), 15)}
          <p className="text-xs text-slate-400">{t('spybuild_help')}</p>
        </div>
        <div className="mt-4 flex items-center gap-2">
          <button onClick={preview} disabled={previewing}
            className="flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-800 disabled:opacity-40 text-white text-sm font-medium rounded-lg transition-colors">
            {previewing && <i className="fa-solid fa-spinner animate-spin text-xs" />}
            {t('spybuild_preview')}
          </button>
        </div>
        {st.at ? (
          <div className="mt-4 rounded-lg bg-slate-50 border border-slate-200 px-3 py-2 text-xs text-slate-600 space-y-1">
            <p className="font-medium">
              {new Date(st.at * 1000).toLocaleString('pt-PT')} · {st.dryRun ? t('spybuild_status_dry') : t('spybuild_status_live')}
            </p>
            <p>{t('spybuild_status_line')
              .replace('{n}', fmt(st.ordered)).replace('{free}', fmt(st.freeSlots))
              .replace('{gold}', fmt(st.spentGold)).replace('{crystal}', fmt(st.spentCrystal))}</p>
            {(st.orders || []).length > 0 && (
              <p>{(st.orders || []).map(o => `${o.name} ${o.amount}`).join(' · ')}</p>
            )}
            {(st.failed || []).map(o => <p key={o.name} className="text-red-600">✗ {o.name}: {o.reason}</p>)}
            {Object.entries(st.notes || {}).map(([c, n]) => <p key={c} className="text-slate-400">{c}: {n}</p>)}
          </div>
        ) : null}
      </div>
    </Card>
  )
}

function TelegramCard() {
  const t = useT()
  const [token, setToken] = useState('')
  const [chatId, setChatId] = useState('')
  const [webhook, setWebhook] = useState('')
  const [tgMin, setTgMin] = useState('info')
  const [dcMin, setDcMin] = useState('activity')
  const [tgMuted, setTgMuted] = useState<string[]>([])
  const [dcMuted, setDcMuted] = useState<string[]>([])
  const [digest, setDigest] = useState('daily')
  const [digestHour, setDigestHour] = useState(21)
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'invalid' | 'testing' | 'tested'>('idle')
  const [channels, setChannels] = useState<{ telegram: ChannelResult; discord: ChannelResult } | null>(null)

  useEffect(() => {
    fetch('/api/telegram-settings')
      .then(r => r.json())
      .then(d => {
        setToken(d.botToken || ''); setChatId(d.chatId || ''); setWebhook(d.discordWebhook || '')
        setTgMin(d.telegramMinLevel || 'info'); setDcMin(d.discordMinLevel || 'activity')
        setTgMuted(d.telegramMuted || []); setDcMuted(d.discordMuted || [])
        setDigest(d.digest || 'daily'); setDigestHour(d.digestHour ?? 21)
      })
      .catch(() => {})
  }, [])

  const handleSave = () => {
    setStatus('saving')
    fetch('/api/telegram-settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ botToken: token, chatId, discordWebhook: webhook,
                             telegramMinLevel: tgMin, discordMinLevel: dcMin,
                             telegramMuted: tgMuted, discordMuted: dcMuted, digest, digestHour }),
    })
      .then(r => { setStatus(r.ok ? 'saved' : 'invalid'); setTimeout(() => setStatus('idle'), 4000) })
      .catch(() => setStatus('idle'))
  }

  const handleTest = () => {
    setStatus('testing')
    setChannels(null)
    fetch('/api/telegram-settings/test', { method: 'POST' })
      .then(r => r.json())
      .then(d => { setChannels(d.channels || { telegram: false, discord: false }); setStatus('tested') })
      .catch(() => { setChannels({ telegram: false, discord: false }); setStatus('tested') })
  }

  const levelSelect = (value: string, onChange: (v: string) => void) => (
    <div>
      <label className="block text-xs text-slate-500 mb-1">{t('settings_notify_min_level')}</label>
      <select value={value} onChange={e => onChange(e.target.value)}
        className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400">
        {NOTIFY_LEVELS.map(l => <option key={l} value={l}>{t(`settings_notify_level_${l}`)}</option>)}
      </select>
    </div>
  )

  const mutePicker = (muted: string[], setMuted: (v: string[]) => void) => (
    <div>
      <label className="block text-xs text-slate-500 mb-1">{t('settings_notify_categories')}</label>
      <div className="flex flex-wrap gap-1.5">
        {NOTIFY_CATEGORIES.map(c => {
          const on = !muted.includes(c)
          return (
            <button key={c} type="button"
              onClick={() => setMuted(on ? [...muted, c] : muted.filter(x => x !== c))}
              className={`px-2.5 py-1 rounded-full text-xs font-medium border transition-colors ${on
                ? 'bg-indigo-50 border-indigo-300 text-indigo-700'
                : 'bg-white border-slate-200 text-slate-400 line-through'}`}>
              {t(`settings_notify_cat_${c}`)}
            </button>
          )
        })}
      </div>
    </div>
  )

  const badge = (label: string, v: ChannelResult) => {
    if (v === null) return <span className="text-sm text-slate-400">{label}: {t('settings_notify_not_configured')}</span>
    return v
      ? <span className="text-sm text-emerald-600 font-medium">✓ {label}</span>
      : <span className="text-sm text-red-600 font-medium">✗ {label}</span>
  }

  return (
    <Card>
      <div className="px-5 py-4">
        <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-4 flex items-center gap-1.5">
          <i className="fa-solid fa-bell text-indigo-500" /> {t('settings_notify_title')}
        </p>
        <div className="space-y-3">
          <p className="text-xs font-medium text-slate-600 flex items-center gap-1.5">
            <i className="fa-brands fa-telegram text-sky-500" /> Telegram
          </p>
          <div>
            <label className="block text-xs text-slate-500 mb-1">{t('settings_telegram_token')}</label>
            <input type="text" value={token} onChange={e => setToken(e.target.value)}
              placeholder="123456:ABC-DEF…" className={INPUT_CLS} />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">{t('settings_telegram_chatid')}</label>
            <input type="text" value={chatId} onChange={e => setChatId(e.target.value)}
              placeholder="-100123456789" className={INPUT_CLS} />
          </div>
          {levelSelect(tgMin, setTgMin)}
          {mutePicker(tgMuted, setTgMuted)}
          <p className="text-xs text-slate-400">{t('settings_telegram_help')}</p>
          <p className="pt-2 text-xs font-medium text-slate-600 flex items-center gap-1.5">
            <i className="fa-brands fa-discord text-indigo-500" /> Discord
          </p>
          <div>
            <label className="block text-xs text-slate-500 mb-1">{t('settings_discord_webhook')}</label>
            <input type="text" value={webhook} onChange={e => setWebhook(e.target.value)}
              placeholder="https://discord.com/api/webhooks/…" className={INPUT_CLS} />
          </div>
          {levelSelect(dcMin, setDcMin)}
          {mutePicker(dcMuted, setDcMuted)}
          <p className="text-xs text-slate-400">{t('settings_discord_help')}</p>
          <p className="pt-2 text-xs font-medium text-slate-600 flex items-center gap-1.5">
            <i className="fa-solid fa-chart-column text-indigo-500" /> {t('settings_digest_title')}
          </p>
          <div className="flex gap-3">
            <div className="flex-1">
              <label className="block text-xs text-slate-500 mb-1">{t('settings_digest_mode')}</label>
              <select value={digest} onChange={e => setDigest(e.target.value)}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400">
                <option value="off">{t('settings_digest_off')}</option>
                <option value="hourly">{t('settings_digest_hourly')}</option>
                <option value="daily">{t('settings_digest_daily')}</option>
              </select>
            </div>
            {digest === 'daily' && (
              <div className="w-28">
                <label className="block text-xs text-slate-500 mb-1">{t('settings_digest_hour')}</label>
                <select value={digestHour} onChange={e => setDigestHour(Number(e.target.value))}
                  className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400">
                  {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, '0')}:00</option>)}
                </select>
              </div>
            )}
          </div>
          <p className="text-xs text-slate-400">{t('settings_digest_help')}</p>
        </div>
        <div className="mt-4 flex items-center gap-2 flex-wrap">
          <button
            onClick={handleSave}
            disabled={status === 'saving'}
            className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white text-sm font-medium rounded-lg transition-colors"
          >
            {status === 'saving' && <i className="fa-solid fa-spinner animate-spin text-xs" />}
            {t('save')}
          </button>
          <button
            onClick={handleTest}
            disabled={(!(token && chatId) && !webhook) || status === 'testing'}
            className="flex items-center gap-2 px-4 py-2 bg-sky-500 hover:bg-sky-600 disabled:opacity-40 text-white text-sm font-medium rounded-lg transition-colors"
          >
            {status === 'testing' && <i className="fa-solid fa-spinner animate-spin text-xs" />}
            {t('settings_telegram_test_btn')}
          </button>
          {status === 'saved'   && <span className="text-sm text-emerald-600 font-medium">✓ {t('settings_telegram_saved')}</span>}
          {status === 'invalid' && <span className="text-sm text-red-600 font-medium">✗ {t('settings_discord_invalid')}</span>}
          {status === 'tested' && channels && (
            <span className="flex items-center gap-3">
              {badge('Telegram', channels.telegram)}
              {badge('Discord', channels.discord)}
            </span>
          )}
        </div>
        <p className="mt-3 text-xs text-slate-400">{t('settings_notify_save_first')}</p>
      </div>
    </Card>
  )
}

function CombatAlertsCard() {
  const t = useT()
  const [s, setS] = useState<{ incomingEnabled: boolean; returnEnabled: boolean; checkMinutes: number } | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    fetch('/api/alert-settings').then(r => r.json()).then(setS).catch(() => {})
  }, [])

  const save = (next: typeof s) => {
    if (!next) return
    setS(next); setSaved(false)
    fetch('/api/alert-settings', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(next),
    }).then(() => { setSaved(true); setTimeout(() => setSaved(false), 3000) }).catch(() => {})
  }

  if (!s) return null
  const Toggle = ({ on, onClick }: { on: boolean; onClick: () => void }) => (
    <button onClick={onClick} className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${on ? 'bg-indigo-600' : 'bg-slate-200'}`}>
      <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${on ? 'translate-x-6' : 'translate-x-1'}`} />
    </button>
  )

  return (
    <Card>
      <div className="px-5 py-4">
        <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-4 flex items-center gap-1.5">
          <i className="fa-solid fa-tower-observation text-red-500" /> {t('alerts_title')}
        </p>
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm text-slate-600">{t('alerts_incoming')}</span>
            <Toggle on={s.incomingEnabled} onClick={() => save({ ...s, incomingEnabled: !s.incomingEnabled })} />
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-slate-600">{t('alerts_return')}</span>
            <Toggle on={s.returnEnabled} onClick={() => save({ ...s, returnEnabled: !s.returnEnabled })} />
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm text-slate-600">{t('alerts_check')}</span>
            <input
              type="number" min={0} max={120} value={s.checkMinutes}
              onChange={e => setS({ ...s, checkMinutes: Math.max(0, Number(e.target.value)) })}
              onBlur={() => save(s)}
              className="w-20 border border-slate-200 rounded-lg px-2 py-1.5 text-sm text-right focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
          </div>
          <p className="text-xs text-slate-400">{t('alerts_check_hint')}</p>
          {saved && <span className="text-sm text-emerald-600 font-medium">✓ {t('settings_telegram_saved')}</span>}
        </div>
      </div>
    </Card>
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

      <TelegramCard />
      <SpyBuildCard />
      <CombatAlertsCard />
    </div>
  )
}

const DEFAULT_GARRISON_TOTAL = 50000

function EspionagemTab() {
  const t = useT()
  const [ownCities, setOwnCities]         = useState<OwnCity[]>([])
  const defaults = loadSpyDefaults()
  const [originCityId, setOriginCityId]   = useState(defaults.originCityId)
  const [numAgents, setNumAgents]         = useState(defaults.numAgents)
  const [saved, setSaved]                 = useState(false)
  const [thresholdTotal, setThresholdTotal] = useState(DEFAULT_GARRISON_TOTAL)
  const [minLootTotal, setMinLootTotal]   = useState(50000)
  const [ignoreExpiryDays, setIgnoreExpiryDays]         = useState(30)
  const [ignorePermanentAfter, setIgnorePermanentAfter] = useState(4)
  const [farmLoots, setFarmLoots]         = useState<number[]>([])
  const [thSaved, setThSaved]             = useState(false)

  useEffect(() => {
    fetch('/api/own-cities')
      .then(r => r.json())
      .then(d => {
        const cities: OwnCity[] = Array.isArray(d) ? d : (d.cities || [])
        setOwnCities(cities)
        if (!originCityId && cities.length > 0) setOriginCityId(String(cities[0].cityId))
      })
      .catch(() => {})
    fetch('/api/farm')
      .then(r => r.json())
      .then((d: Array<{ enabled: boolean; min_loot: number }>) => {
        if (Array.isArray(d)) setFarmLoots(d.filter(f => f.enabled).map(f => f.min_loot || 0))
      })
      .catch(() => {})
    fetch('/api/espionage/settings')
      .then(r => r.json())
      .then(d => {
        if (d.garrisonThresholdTotal != null) setThresholdTotal(d.garrisonThresholdTotal)
        if (d.minLootTotal != null) setMinLootTotal(d.minLootTotal)
        if (d.ignoreExpiryDays != null) setIgnoreExpiryDays(d.ignoreExpiryDays)
        if (d.ignorePermanentAfter != null) setIgnorePermanentAfter(d.ignorePermanentAfter)
      })
      .catch(() => {})
  }, [])

  const handleSave = () => {
    saveSpyDefaults(originCityId, numAgents)
    setSaved(true)
    setTimeout(() => setSaved(false), 3000)
  }

  const handleSaveThresholds = () => {
    fetch('/api/espionage/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ garrisonThresholdTotal: thresholdTotal, minLootTotal, ignoreExpiryDays, ignorePermanentAfter }),
    }).then(() => {
      setThSaved(true)
      setTimeout(() => setThSaved(false), 3000)
    }).catch(() => {})
  }

  return (
    <div className="grid gap-4 max-w-lg">
      <Card>
        <div className="px-5 py-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1 flex items-center gap-1.5">
            <i className="fa-solid fa-user-secret text-indigo-400" /> {t('settings_spy_title')}
          </p>
          <p className="text-xs text-slate-400 mb-4">{t('settings_spy_hint')}</p>
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">{t('spy_origin_city')}</label>
              <select
                value={originCityId}
                onChange={e => setOriginCityId(e.target.value)}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400"
              >
                {ownCities.map(c => (
                  <option key={c.cityId} value={String(c.cityId)}>{c.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">{t('spy_num_agents')}</label>
              <input
                type="number" min={1} max={99} value={numAgents}
                onChange={e => setNumAgents(Math.max(1, parseInt(e.target.value) || 1))}
                className="w-24 border border-slate-200 rounded-lg px-3 py-2 text-sm text-center bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400"
              />
            </div>
          </div>
        </div>
      </Card>
      <div className="flex items-center gap-3">
        <button onClick={handleSave} className="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg transition-colors">
          {t('save')}
        </button>
        {saved && <span className="text-sm text-emerald-600 font-medium">✓ {t('settings_telegram_saved')}</span>}
      </div>

      <Card>
        <div className="px-5 py-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1 flex items-center gap-1.5">
            <i className="fa-solid fa-shield-halved text-amber-400" /> {t('spy_garrison_threshold_title')}
          </p>
          <p className="text-xs text-slate-400 mb-4">{t('spy_garrison_threshold_desc')}</p>
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <label className="text-xs font-medium text-slate-600 whitespace-nowrap">{t('spy_garrison_threshold_label')}</label>
              <input
                type="number" min={0} step={5000}
                value={thresholdTotal}
                onChange={e => setThresholdTotal(Math.max(0, parseInt(e.target.value) || 0))}
                className="w-36 border border-slate-200 rounded-lg px-3 py-2 text-sm text-right bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400"
              />
            </div>
            <div className="flex items-center gap-3">
              <label className="text-xs font-medium text-slate-600 whitespace-nowrap">{t('spy_min_loot_label')}</label>
              <input
                type="number" min={0} step={5000}
                value={minLootTotal}
                onChange={e => setMinLootTotal(Math.max(0, parseInt(e.target.value) || 0))}
                className="w-36 border border-slate-200 rounded-lg px-3 py-2 text-sm text-right bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400"
              />
              <span className="text-[10px] text-slate-400">{t('spy_min_loot_hint')}</span>
            </div>
            <div className="flex items-center gap-3 flex-wrap pt-1 border-t border-slate-100">
              <label className="text-xs font-medium text-slate-600 whitespace-nowrap">{t('ignore_expiry_label')}</label>
              <input
                type="number" min={1} max={365}
                value={ignoreExpiryDays}
                onChange={e => setIgnoreExpiryDays(Math.max(1, parseInt(e.target.value) || 1))}
                className="w-20 border border-slate-200 rounded-lg px-3 py-2 text-sm text-right bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400"
              />
              <label className="text-xs font-medium text-slate-600 whitespace-nowrap">{t('ignore_permanent_label')}</label>
              <input
                type="number" min={1} max={20}
                value={ignorePermanentAfter}
                onChange={e => setIgnorePermanentAfter(Math.max(1, parseInt(e.target.value) || 1))}
                className="w-20 border border-slate-200 rounded-lg px-3 py-2 text-sm text-right bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400"
              />
            </div>
            <p className="text-[10px] text-slate-400 -mt-1">{t('ignore_policy_hint')}</p>
            <div className="bg-slate-50 rounded-lg px-3 py-2.5 space-y-1">
              <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wide">{t('threshold_funnel_title')}</p>
              <p className="text-[11px] text-slate-500">1. {t('threshold_funnel_1', { n: thresholdTotal.toLocaleString() })}</p>
              <p className="text-[11px] text-slate-500">2. {t('threshold_funnel_2', { n: minLootTotal.toLocaleString() })}</p>
              <p className="text-[11px] text-slate-500">
                3. {farmLoots.length > 0
                  ? t('threshold_funnel_3', {
                      c: String(farmLoots.length),
                      min: Math.min(...farmLoots).toLocaleString(),
                      max: Math.max(...farmLoots).toLocaleString(),
                    })
                  : t('threshold_funnel_3_empty')}
              </p>
            </div>
          </div>
        </div>
      </Card>
      <div className="flex items-center gap-3">
        <button onClick={handleSaveThresholds} className="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg transition-colors">
          {t('save')}
        </button>
        {thSaved && <span className="text-sm text-emerald-600 font-medium">✓ {t('settings_telegram_saved')}</span>}
      </div>

      <WatchlistCard />
    </div>
  )
}

function WatchlistCard() {
  const t = useT()
  const [s, setS] = useState<{ enabled: boolean; intervalHours: number } | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => { fetch('/api/watchlist').then(r => r.json()).then(setS).catch(() => {}) }, [])

  const save = (next: typeof s) => {
    if (!next) return
    setS(next); setSaved(false)
    fetch('/api/watchlist', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(next),
    }).then(() => { setSaved(true); setTimeout(() => setSaved(false), 3000) }).catch(() => {})
  }

  if (!s) return null
  return (
    <Card>
      <div className="px-5 py-4">
        <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3 flex items-center gap-1.5">
          <i className="fa-solid fa-binoculars text-indigo-500" /> {t('watchlist_title')}
        </p>
        <p className="text-xs text-slate-400 mb-3">{t('watchlist_hint')}</p>
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm text-slate-600">{t('transport_enabled')}</span>
            <button onClick={() => save({ ...s, enabled: !s.enabled })}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${s.enabled ? 'bg-indigo-600' : 'bg-slate-200'}`}>
              <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${s.enabled ? 'translate-x-6' : 'translate-x-1'}`} />
            </button>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm text-slate-600">{t('watchlist_interval')}</span>
            <input type="number" min={1} max={168} value={s.intervalHours}
              onChange={e => setS({ ...s, intervalHours: Math.max(1, Number(e.target.value)) })}
              onBlur={() => save(s)}
              className="w-20 border border-slate-200 rounded-lg px-2 py-1.5 text-sm text-right focus:outline-none focus:ring-2 focus:ring-indigo-400" />
          </div>
          {saved && <span className="text-sm text-emerald-600 font-medium">✓ {t('settings_telegram_saved')}</span>}
        </div>
      </div>
    </Card>
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
    { key: 'espionagem',   label: t('settings_tab_espionage'),     icon: 'fa-user-secret'  },
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
