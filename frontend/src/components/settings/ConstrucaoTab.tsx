import { useState, useEffect } from 'react'
import { apiAction } from '../../api'
import { useT, useLang } from '../../i18n'
import { MATERIALS } from '../../constants'
import { Card } from '../ui/Card'
import { NumberField } from '../ui/NumberField'
import { CardTitle, SaveButton } from './shared'

export function ConstrucaoTab() {
  const t    = useT()
  const lang = useLang() as 'pt' | 'en'
  const [hoursStart, setHoursStart] = useState(0)
  const [hoursEnd,   setHoursEnd]   = useState(24)
  const [buffer,     setBuffer]     = useState([0, 0, 0, 0, 0])
  const [saved,      setSaved]      = useState(false)
  const [saving,     setSaving]     = useState(false)
  const [loaded,     setLoaded]     = useState(false)

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
    apiAction('/api/building-queue/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        activeHours: { start: hoursStart, end: hoursEnd },
        resourceBuffer: buffer,
      }),
    })
      .then(r => { if (!r) return; setSaved(true); setTimeout(() => setSaved(false), 3000) })
      .catch(() => {})
      .finally(() => setSaving(false))
  }

  if (!loaded) return <div className="text-sm text-slate-400 mt-4">{t('loading')}</div>

  return (
    <div className="grid gap-4 max-w-lg">
      <Card>
        <div className="px-5 py-4">
          <CardTitle icon="fa-clock text-indigo-400" className="mb-1">{t('queue_active_hours_title')}</CardTitle>
          <p className="text-xs text-slate-400 mb-4">{t('queue_active_hours_hint')}</p>
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-sm text-slate-600">{t('queue_active_hours_from')}</span>
            <NumberField value={hoursStart} onCommit={setHoursStart} min={0} max={23}
              label={t('queue_active_hours_from')} align="center" className="w-16 font-mono" />
            <span className="text-sm text-slate-400">h</span>
            <span className="text-sm text-slate-600">{t('queue_active_hours_to')}</span>
            <NumberField value={hoursEnd} onCommit={setHoursEnd} min={1} max={24}
              label={t('queue_active_hours_to')} align="center" className="w-16 font-mono" />
            <span className="text-sm text-slate-400">h</span>
            <span className="text-xs text-slate-400">(0–24)</span>
          </div>
        </div>
      </Card>

      <Card>
        <div className="px-5 py-4">
          <CardTitle icon="fa-shield-halved text-amber-400" className="mb-1">{t('queue_buffer_title')}</CardTitle>
          <p className="text-xs text-slate-400 mb-4">{t('queue_buffer_hint')}</p>
          <div className="space-y-2.5">
            {MATERIALS.map((m, i) => (
              <div key={m.en} className="flex items-center gap-3">
                <span className="flex items-center gap-1.5 w-28 text-sm font-medium text-slate-600 shrink-0">
                  <i className={`fa-solid ${m.icon} ${m.color}`} />
                  {m[lang]}
                </span>
                <NumberField value={buffer[i]} min={0} step={1000} label={m[lang]} size="lg" className="w-32 font-mono"
                  onCommit={v => setBuffer(prev => prev.map((p, j) => (j === i ? v : p)))} />
              </div>
            ))}
          </div>
        </div>
      </Card>

      <div className="flex items-center gap-3">
        <SaveButton onClick={handleSave} saving={saving} />
        {saved && <span className="text-sm text-emerald-600 font-medium">✓ {t('queue_settings_saved').replace('✓ ', '')}</span>}
      </div>
    </div>
  )
}
