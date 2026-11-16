import { useState, useEffect } from 'react'
import { pushToast } from '../ui/Toast'
import { useT } from '../../i18n'
import { Card } from '../ui/Card'
import { CardTitle, SELECT_CLS } from './shared'

type ChannelResult = boolean | null
const NOTIFY_LEVELS = ['activity', 'info', 'success', 'warning', 'error', 'critical'] as const
const NOTIFY_CATEGORIES = ['combat', 'farm', 'spy', 'wine', 'transport', 'build', 'system', 'digest'] as const
const INPUT_CLS = 'w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400 font-mono'

// Telegram + Discord channels and the periodic digest. Not on useSettings: the secrets are never
// sent back by the server, so the form is not a copy of what is stored.
export function TelegramCard() {
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
  const [secretInfo, setSecretInfo] = useState({ token: '', webhook: '' })

  useEffect(() => {
    fetch('/api/telegram-settings')
      .then(r => r.json())
      .then(d => {
        // the server never sends the secrets — only whether each is set, and its last characters
        setToken(''); setChatId(d.chatId || ''); setWebhook('')
        setSecretInfo({ token: d.botTokenSet ? (d.botTokenHint || '••••') : '', webhook: d.discordWebhookSet ? (d.discordWebhookHint || '••••') : '' })
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
      .then(async r => {
        if (r.ok) {
          setSecretInfo(prev => ({ token: token ? '…' + token.slice(-4) : prev.token,
                                   webhook: webhook ? '…' + webhook.slice(-4) : prev.webhook }))
          setToken(''); setWebhook('')
          setStatus('saved')
        } else {
          // only a bad webhook is "invalid webhook" — any other failure says what it was
          const body = await r.json().catch(() => ({}))
          if (body.error === 'invalid_discord_webhook') setStatus('invalid')
          else { pushToast(body.error || t('transport_save_failed'), 'error'); setStatus('idle'); return }
        }
        setTimeout(() => setStatus('idle'), 4000)
      })
      .catch(() => { pushToast(t('transport_save_failed'), 'error'); setStatus('idle') })
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
      <select value={value} onChange={e => onChange(e.target.value)} className={SELECT_CLS}>
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
            <button key={c} type="button" aria-pressed={on}
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
        <CardTitle icon="fa-bell text-indigo-500">{t('settings_notify_title')}</CardTitle>
        <div className="space-y-3">
          <p className="text-xs font-medium text-slate-600 flex items-center gap-1.5">
            <i className="fa-brands fa-telegram text-sky-500" /> Telegram
          </p>
          <div>
            <label className="block text-xs text-slate-500 mb-1">{t('settings_telegram_token')}</label>
            <input type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)}
              placeholder={secretInfo.token ? t('settings_secret_set', { hint: secretInfo.token }) : '123456:ABC-DEF…'} className={INPUT_CLS} />
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
            <input type="password" autoComplete="off" value={webhook} onChange={e => setWebhook(e.target.value)}
              placeholder={secretInfo.webhook ? t('settings_secret_set', { hint: secretInfo.webhook }) : 'https://discord.com/api/webhooks/…'} className={INPUT_CLS} />
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
              <select value={digest} onChange={e => setDigest(e.target.value)} className={SELECT_CLS}>
                <option value="off">{t('settings_digest_off')}</option>
                <option value="hourly">{t('settings_digest_hourly')}</option>
                <option value="daily">{t('settings_digest_daily')}</option>
              </select>
            </div>
            {digest === 'daily' && (
              <div className="w-28">
                <label className="block text-xs text-slate-500 mb-1">{t('settings_digest_hour')}</label>
                <select value={digestHour} onChange={e => setDigestHour(Number(e.target.value))} className={SELECT_CLS}>
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
            // a stored secret counts: the fields stay empty once saved (the server never sends them)
            disabled={(!((token || secretInfo.token) && chatId) && !(webhook || secretInfo.webhook)) || status === 'testing'}
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
