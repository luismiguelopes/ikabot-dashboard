import { useState, useEffect } from 'react'
import { useT, useLang } from '../../i18n'
import { fmt } from '../../utils'
import { MATERIALS } from '../../constants'
import { Card, CardHeader } from '../ui/Card'
import { NumberField } from '../ui/NumberField'
import { LABEL_CLS, SELECT_CLS } from './types'
import type { OwnCity, ResourcesData } from '../../types'

const AMOUNT_CLS = 'border border-slate-200 rounded-lg px-2 py-1 text-sm text-right focus:outline-none focus:ring-2 focus:ring-indigo-400'

function segmentCls(active: boolean) {
  return `flex-1 rounded-lg text-xs font-medium border transition-colors ${active
    ? 'bg-indigo-600 text-white border-indigo-600'
    : 'bg-white text-slate-600 border-slate-200 hover:border-indigo-300'}`
}

// One-off scheduled transport between two own cities.
export function ManualTransportCard({ ownCities, resourcesData, onQueued }: {
  ownCities: OwnCity[]
  resourcesData: ResourcesData
  onQueued: () => void
}) {
  const t    = useT()
  const lang = useLang() as 'pt' | 'en'

  const [originName,   setOriginName]   = useState('')
  const [destName,     setDestName]     = useState('')
  const [amounts,      setAmounts]      = useState<number[]>([0, 0, 0, 0, 0])
  const [ships,        setShips]        = useState(0)
  const [shipType,     setShipType]     = useState<'transporters' | 'freighters'>('transporters')
  const [scheduleType, setScheduleType] = useState<'now' | 'delay' | 'at'>('now')
  const [delayMinutes, setDelayMinutes] = useState(30)
  const [atTime,       setAtTime]       = useState('')
  const [submitting,   setSubmitting]   = useState(false)
  const [feedback,     setFeedback]     = useState<{ ok: boolean; msg: string } | null>(null)

  useEffect(() => {
    if (ownCities.length === 0) return
    setOriginName(prev => prev || ownCities[0].name)
    setDestName(prev => prev || (ownCities[1]?.name ?? ownCities[0].name))
  }, [ownCities])

  const origin = ownCities.find(c => c.name === originName)
  const dest   = ownCities.find(c => c.name === destName)
  const originRes = (resourcesData[originName] ?? {}) as unknown as Record<string, unknown>

  function computeDispatchAfter(): number {
    const base = Math.floor(Date.now() / 1000)
    if (scheduleType === 'delay') return base + delayMinutes * 60
    if (scheduleType === 'at' && atTime) {
      const [h, m] = atTime.split(':').map(Number)
      const d = new Date()
      d.setHours(h, m, 0, 0)
      if (d.getTime() / 1000 <= base) d.setDate(d.getDate() + 1)
      return Math.floor(d.getTime() / 1000)
    }
    return base + 10
  }

  async function handleSubmit() {
    if (!origin || !dest) return
    if (amounts.every(a => a <= 0)) {
      setFeedback({ ok: false, msg: t('transport_select_resource') })
      return
    }
    if (scheduleType === 'at' && !atTime) {          // an empty time used to mean "send now"
      setFeedback({ ok: false, msg: t('schedule_time_missing') })
      return
    }
    setSubmitting(true)
    setFeedback(null)
    try {
      const res = await fetch('/api/transport/queue/add', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          originCityId:   String(origin.cityId),
          originCityName: origin.name,
          destCityId:     String(dest.cityId),
          destCityName:   dest.name,
          islandId:       String(dest.islandId ?? ''),
          resources:      amounts,
          ships,
          shipType,
          scheduleType,
          delayMinutes,
          dispatchAfter:  computeDispatchAfter(),
        }),
      })
      const json = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(json.error ?? t('transport_save_failed'))
      setFeedback({ ok: true, msg: `${origin.name} → ${dest.name}` })
      setAmounts([0, 0, 0, 0, 0])
      onQueued()
    } catch (e: any) {
      setFeedback({ ok: false, msg: e.message })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card>
      <CardHeader icon="fa-ship" title={t('transport_manual')} />
      <div className="p-4 space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className={LABEL_CLS}>{t('transport_origin')}</span>
            <select className={SELECT_CLS} value={originName} onChange={e => {
              const next = e.target.value
              setOriginName(next)
              // Picking the destination as origin swaps the two (the old origin becomes the destination).
              if (next === destName) setDestName(originName && originName !== next
                ? originName : (ownCities.find(c => c.name !== next)?.name ?? ''))
            }}>
              {ownCities.map(c => <option key={c.cityId} value={c.name}>{c.name}</option>)}
            </select>
          </label>
          <label className="block">
            <span className={LABEL_CLS}>{t('transport_dest')}</span>
            <select className={SELECT_CLS} value={destName} onChange={e => setDestName(e.target.value)}>
              {ownCities.filter(c => c.name !== originName).map(c => (
                <option key={c.cityId} value={c.name}>{c.name}</option>
              ))}
            </select>
          </label>
        </div>

        <div>
          <span className={LABEL_CLS}>{t('transport_resources')}</span>
          <div className="space-y-2">
            {MATERIALS.map((m, i) => {
              const avail = Number(originRes[m.en] ?? 0)
              return (
                <div key={m.en} className="flex items-center gap-3">
                  <span className={`w-5 text-center ${m.color}`}><i className={`fa-solid ${m.icon}`} /></span>
                  <span className="flex-1 text-sm text-slate-700">{m[lang]}</span>
                  <span className="text-xs text-slate-400 w-20 text-right">{fmt(avail)}</span>
                  <input
                    type="number" min={0} inputMode="numeric" aria-label={m[lang]}
                    value={amounts[i]}
                    onChange={e => {
                      const v = Math.max(0, Number(e.target.value) || 0)
                      setAmounts(prev => prev.map((p, j) => (j === i ? v : p)))
                    }}
                    className={`w-28 ${AMOUNT_CLS}`}
                  />
                  <button
                    className="text-xs text-indigo-500 hover:text-indigo-700 font-medium"
                    onClick={() => setAmounts(prev => prev.map((p, j) => (j === i ? avail : p)))}
                  >
                    Max
                  </button>
                </div>
              )
            })}
          </div>
        </div>

        <div className="flex items-end gap-3">
          <label className="block">
            <span className={LABEL_CLS}>{t('transport_ships')}</span>
            {/* the send button depends on it, so it updates as you type (min 0 cannot fight the keys) */}
            <input
              type="number" min={0} inputMode="numeric" value={ships}
              onChange={e => setShips(Math.max(0, Number(e.target.value) || 0))}
              className={`w-24 ${AMOUNT_CLS} py-1.5`}
            />
          </label>
          <div className="flex gap-2 flex-1">
            {(['transporters', 'freighters'] as const).map(st => (
              <button key={st} onClick={() => setShipType(st)} aria-pressed={shipType === st} className={`py-2 ${segmentCls(shipType === st)}`}>
                <i className={`fa-solid ${st === 'transporters' ? 'fa-sailboat' : 'fa-ferry'} mr-1`} />
                {t(st === 'transporters' ? 'transport_ship_type_transporters' : 'transport_ship_type_freighters')}
              </button>
            ))}
          </div>
        </div>

        <div>
          <span className={LABEL_CLS}>{t('dispatch_schedule')}</span>
          <div className="flex gap-2 mb-2">
            {(['now', 'delay', 'at'] as const).map(st => (
              <button key={st} onClick={() => setScheduleType(st)} aria-pressed={scheduleType === st} className={`py-1.5 ${segmentCls(scheduleType === st)}`}>
                {t(st === 'now' ? 'dispatch_sched_now' : st === 'delay' ? 'dispatch_sched_delay' : 'dispatch_sched_at')}
              </button>
            ))}
          </div>
          {scheduleType === 'delay' && (
            <div className="flex items-center gap-2">
              <NumberField value={delayMinutes} onCommit={setDelayMinutes} min={1} max={480}
                label={t('dispatch_minutes')} size="lg" className="w-24" />
              <span className="text-sm text-slate-500">{t('dispatch_minutes')}</span>
            </div>
          )}
          {scheduleType === 'at' && (
            <input
              type="time" value={atTime} onChange={e => setAtTime(e.target.value)}
              className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
          )}
        </div>

        {feedback && (
          <div className={`rounded-lg px-3 py-2 text-sm ${feedback.ok ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-600'}`}>
            <i className={`fa-solid ${feedback.ok ? 'fa-circle-check' : 'fa-circle-xmark'} mr-1.5`} />
            {feedback.msg}
          </div>
        )}

        <button
          className="inline-flex items-center gap-1.5 px-3 py-2.5 rounded-lg text-sm font-medium bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40 w-full justify-center"
          onClick={handleSubmit}
          disabled={submitting || !origin || !dest || ships <= 0}
        >
          {submitting
            ? <><i className="fa-solid fa-spinner fa-spin" /> {t('dispatch_sending')}</>
            : <><i className="fa-solid fa-paper-plane" /> {t('transport_send')}</>}
        </button>
      </div>
    </Card>
  )
}
