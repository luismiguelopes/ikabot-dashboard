import { useState, useEffect } from 'react'
import { askConfirm } from '../ui/Modal'
import { apiAction } from '../../api'
import { useT } from '../../i18n'
import { useSettings } from '../../hooks/useSettings'
import { Card } from '../ui/Card'
import { CardTitle, NumberRow, SavedBadge, ToggleRow } from './shared'

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

const fmtN = (n?: number) => (n ?? 0).toLocaleString('pt-PT')

export function SpyBuildCard() {
  const t = useT()
  const { data: s, saveNow, saved } = useSettings<SpyBuildSettings>('/api/espionage/spy-build')
  const [st, setSt] = useState<SpyBuildStatus>({})
  const [previewing, setPreviewing] = useState(false)

  useEffect(() => {
    fetch('/api/espionage/spy-build/status').then(r => r.json()).then(setSt).catch(() => {})
  }, [])

  if (!s) return null

  const preview = async () => {
    setPreviewing(true)
    const before = st.at || 0
    await apiAction('/api/espionage/spy-build/preview', { method: 'POST' }).catch(() => {})
    for (let i = 0; i < 20; i++) {            // the bot picks the flag up within ≤60s
      await new Promise(r => setTimeout(r, 4000))
      const d: SpyBuildStatus = await fetch('/api/espionage/spy-build/status').then(r => r.json()).catch(() => ({}))
      if ((d.at || 0) > before) { setSt(d); break }
    }
    setPreviewing(false)
  }

  const num = (key: keyof SpyBuildSettings, label: string, min = 0) => (
    <NumberRow label={label} value={s[key] as number} min={min} onCommit={v => saveNow({ [key]: v } as Partial<SpyBuildSettings>)} />
  )

  return (
    <Card>
      <div className="px-5 py-4">
        <CardTitle icon="fa-user-secret text-slate-600" right={<SavedBadge show={saved} />}>{t('spybuild_title')}</CardTitle>
        <div className="space-y-3">
          <ToggleRow label={t('spybuild_enabled')} on={s.enabled} onChange={v => saveNow({ enabled: v })} />
          <ToggleRow label={t('spybuild_dry')} on={s.dryRun} onChange={async v => {
            // leaving dry-run spends gold and crystal on the very next pass → ask first
            if (!v && !(await askConfirm(t('spybuild_live_confirm')))) return
            saveNow({ dryRun: v })
          }} />
          {!s.dryRun && (
            <p className="text-xs font-semibold text-red-600 bg-red-50 border border-red-200 rounded-lg px-2 py-1.5">
              <i className="fa-solid fa-triangle-exclamation mr-1" />{t('spybuild_live_warning')}
            </p>
          )}
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
              .replace('{n}', fmtN(st.ordered)).replace('{free}', fmtN(st.freeSlots))
              .replace('{gold}', fmtN(st.spentGold)).replace('{crystal}', fmtN(st.spentCrystal))}</p>
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
