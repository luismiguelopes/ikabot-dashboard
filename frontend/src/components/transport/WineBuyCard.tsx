import { useState } from 'react'
import { askConfirm } from '../ui/Modal'
import { useT } from '../../i18n'
import { useSettings } from '../../hooks/useSettings'
import { Card, CardHeader } from '../ui/Card'
import { fmtStamp } from '../WinePanorama'
import { LabeledNumber, SaveRow, ToggleLabel } from './shared'
import type { WineBuySettings, WineBuyStatus, WineSettings } from './types'

// Wine market buyer (F10). `status` is shared with the wine panorama, so it lives in the page.
export function WineBuyCard({ wine, status, setStatus }: {
  wine: WineSettings | null
  status: WineBuyStatus | null
  setStatus: (s: WineBuyStatus) => void
}) {
  const t = useT()
  const { data: wb, set, save, saving, saved } = useSettings<WineBuySettings>('/api/transport/wine-buy')
  const [previewing, setPreviewing] = useState(false)

  async function handlePreview() {
    setPreviewing(true)
    try {
      await fetch('/api/transport/wine-buy/preview', { method: 'POST' })
      // the bot runs the dry-run within ~60s; poll the status a few times
      const prevNow = status?.now ?? 0
      for (let i = 0; i < 20; i++) {
        await new Promise(r => setTimeout(r, 4000))
        const d: WineBuyStatus = await fetch('/api/transport/wine-buy/status').then(r => r.json()).catch(() => ({}))
        if (d && d.now && d.now !== prevNow) { setStatus(d); break }
      }
    } catch { /* ignore */ } finally {
      setPreviewing(false)
    }
  }

  async function handleSave() {
    if (await save()) handlePreview()   // B4: refresh the plan against the new settings
  }

  const refill = wb ? Math.min(wb.refillBelowHours ?? 48, wb.targetHours) : 0
  const critical = wb ? Math.min(wb.criticalHours ?? 6, refill) : 0

  const warns: string[] = []
  if (wb?.enabled) {
    if (wine && !wine.enabled) warns.push(t('winebuy_warn_balancer'))
    const donor = wine?.donorReserveHours ?? 96
    if (wine && wine.enabled && wb.targetHours > donor)
      warns.push(`${t('winebuy_warn_target')} (${wb.targetHours}h > ${donor}h)`)
  }

  return (
    <Card className="mb-4">
      <CardHeader icon="fa-cart-shopping" title={t('winebuy_title')} />
      <div className="p-4 space-y-4">
        <p className="text-xs text-slate-500">{t('winebuy_hint')}</p>
        {wb && (
          <>
            <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
              <ToggleLabel on={wb.enabled} onChange={v => set({ enabled: v })} label={t('transport_enabled')} />
              <div className="flex items-center gap-1.5">
                {/* green while it is only a test, red while it spends gold (P13.48) */}
                <ToggleLabel
                  on={wb.dryRun}
                  onClass="bg-emerald-500" offClass="bg-red-500"
                  label={t('winebuy_dryrun')}
                  onChange={async v => {
                    // leaving dry-run means real purchases with gold → ask first
                    if (!v && !(await askConfirm(t('winebuy_live_confirm')))) return
                    set({ dryRun: v })
                  }}
                />
                <i className="fa-solid fa-shield-halved text-amber-500" title={t('winebuy_dryrun_hint')} />
              </div>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 max-w-2xl">
              <LabeledNumber label={t('winebuy_target')} value={wb.targetHours} min={1} max={336}
                onCommit={v => set({ targetHours: v })} />
              <LabeledNumber label={t('winebuy_refill')} value={refill} min={1} max={wb.targetHours}
                onCommit={v => set({ refillBelowHours: v })} />
              <LabeledNumber label={t('winebuy_critical')} value={critical} min={1} max={refill}
                onCommit={v => set({ criticalHours: v })} />
              <LabeledNumber label={t('winebuy_maxprice')} value={wb.maxPricePerUnit} min={1} max={10000}
                onCommit={v => set({ maxPricePerUnit: v })} />
              <LabeledNumber label={t('winebuy_goldfloor')} value={wb.goldFloor} min={0} step={1000}
                onCommit={v => set({ goldFloor: v })} />
              <LabeledNumber label={t('winebuy_maxspend')} value={wb.maxSpendPerCycle} min={0} step={1000}
                onCommit={v => set({ maxSpendPerCycle: v })} />
            </div>

            {/* B3: coherence warnings vs the balancer */}
            {warns.length > 0 && (
              <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2.5 text-sm text-amber-800 space-y-1">
                {warns.map((w, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <i className="fa-solid fa-triangle-exclamation mt-0.5 text-amber-500" /><span>{w}</span>
                  </div>
                ))}
              </div>
            )}

            {status && <WineBuyStatusBox status={status} />}

            <SaveRow onSave={handleSave} saving={saving} saved={saved}>
              <button
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium bg-slate-100 text-slate-700 hover:bg-slate-200 disabled:opacity-40"
                onClick={handlePreview} disabled={previewing}
                title={t('winebuy_preview_hint')}
              >
                <i className={`fa-solid ${previewing ? 'fa-spinner fa-spin' : 'fa-magnifying-glass-chart'}`} />
                {previewing ? t('winebuy_previewing') : t('winebuy_preview')}
              </button>
            </SaveRow>
          </>
        )}
      </div>
    </Card>
  )
}

// Preview / last run of the buyer.
function WineBuyStatusBox({ status: s }: { status: WineBuyStatus }) {
  const t = useT()
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm space-y-1.5">
      <div className="flex items-center gap-2 text-slate-600">
        <i className={`fa-solid ${s.dryRun ? 'fa-flask text-amber-500' : 'fa-check text-emerald-600'}`} />
        <span className="font-medium">{s.dryRun ? t('winebuy_plan') : t('winebuy_bought')}</span>
        <span className="text-slate-400">· {s.note}</span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
        <div><span className="text-slate-400">{t('winebuy_deficit')}: </span><b>{(s.deficit ?? 0).toLocaleString()}</b></div>
        <div><span className="text-slate-400">{t('winebuy_bought')}: </span><b>{(s.bought ?? 0).toLocaleString()}</b></div>
        <div><span className="text-slate-400">{t('winebuy_spent')}: </span><b>{(s.spent ?? 0).toLocaleString()}</b> <i className="fa-solid fa-coins text-amber-400" /></div>
        <div><span className="text-slate-400">{t('winebuy_avgprice')}: </span><b>{s.avgPrice ?? 0}</b>{s.cheapest != null && <span className="text-slate-400"> ({t('winebuy_cheapest')} {s.cheapest})</span>}</div>
      </div>
      {s.lastPurchase && (s.dryRun || s.lastPurchase.at !== s.now) && (
        <div className="text-xs text-slate-600 pt-1 border-t border-slate-200">
          <i className="fa-solid fa-receipt text-emerald-600 mr-1.5" />
          <span className="font-medium">{t('winebuy_last_real')}: </span>
          {t('winebuy_last_real_line', {
            n: s.lastPurchase.bought.toLocaleString(),
            g: s.lastPurchase.spent.toLocaleString(),
            p: s.lastPurchase.avgPrice,
            at: fmtStamp(s.lastPurchase.at),
          })}
        </div>
      )}
      {s.topCities && s.topCities.length > 0 && (
        <div className="text-xs text-slate-500 pt-1">
          {s.topCities.slice(0, 6).map(([n, d]) => (
            <span key={n} className="inline-block mr-2 mb-1 px-1.5 py-0.5 rounded bg-white border border-slate-200">
              {n}: <b>{d.toLocaleString()}</b>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
