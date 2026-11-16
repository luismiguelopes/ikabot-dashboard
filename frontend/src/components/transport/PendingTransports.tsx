import { useT, useLang } from '../../i18n'
import { fmt, fmtDuration, fmtArrival } from '../../utils'
import { useLiveClock } from '../../hooks/useLiveClock'
import { MATERIALS } from '../../constants'
import { Card, CardHeader } from '../ui/Card'
import type { PendingTransport } from './types'

// The 1s clock lives here only (P13.53): at the top of the transport page it re-rendered every
// card and form each second.
function Countdown({ at }: { at: number }) {
  const t    = useT()
  const lang = useLang() as 'pt' | 'en'
  const now  = useLiveClock()
  if (at <= now) {
    return (
      <div className="text-xs text-emerald-600 font-semibold">
        <i className="fa-solid fa-check mr-1" />{t('dispatch_dispatching')}
      </div>
    )
  }
  return (
    <>
      <div className="text-sm font-mono font-semibold text-slate-700">{fmtDuration(at - now)}</div>
      <div className="text-xs text-slate-400">{fmtArrival(at, lang)}</div>
    </>
  )
}

export function PendingTransports({ pending, onCancel }: {
  pending: PendingTransport[]
  onCancel: (id: string) => void
}) {
  const t = useT()
  if (pending.length === 0) return null
  return (
    <Card>
      <CardHeader icon="fa-clock" title={`${t('transport_pending')} (${pending.length})`} />
      <div className="divide-y divide-slate-100">
        {pending.map(item => (
          <div key={item.id} className="px-5 py-3 flex items-center gap-4">
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold text-slate-700">
                <span className="text-indigo-600">{item.originCityName}</span>
                <span className="mx-1.5 text-slate-400">→</span>
                <span className="text-emerald-600">{item.destCityName}</span>
              </div>
              <div className="text-xs text-slate-400 mt-0.5 flex items-center gap-2 flex-wrap">
                {MATERIALS.map((m, i) => (item.resources?.[i] ?? 0) > 0 && (
                  <span key={m.en}>
                    <i className={`fa-solid ${m.icon} mr-1 ${m.color}`} />{fmt(item.resources[i])}
                  </span>
                ))}
                <span>·</span>
                <span>
                  <i className={`fa-solid ${item.shipType === 'freighters' ? 'fa-ferry' : 'fa-sailboat'} mr-1`} />
                  {fmt(item.ships)} {t(item.shipType === 'freighters' ? 'transport_ship_type_freighters' : 'transport_ship_type_transporters')}
                </span>
              </div>
            </div>
            <div className="text-right flex-shrink-0">
              <Countdown at={item.dispatchAfter} />
            </div>
            <button
              onClick={() => onCancel(item.id)}
              className="inline-flex items-center px-3 py-1.5 rounded-lg text-sm font-medium bg-red-500 text-white hover:bg-red-600"
              title={t('cancel')}
              aria-label={t('cancel')}
            >
              <i className="fa-solid fa-xmark" />
            </button>
          </div>
        ))}
      </div>
    </Card>
  )
}
