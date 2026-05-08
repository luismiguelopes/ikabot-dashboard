import { useState, useEffect } from 'react'
import { useT, useLang } from '../i18n'
import { fmt, fmtDuration, fmtArrival } from '../utils'
import { Card, CardHeader } from './ui/Card'
import { PageHeader } from './ui/PageHeader'
import type { Movement } from '../types'

export function MovementsPage() {
  const [movements, setMovements] = useState<Movement[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const t = useT()
  const lang = useLang()

  useEffect(() => {
    fetch('/api/movements')
      .then(r => r.json())
      .then(setMovements)
      .catch(e => setError(e.message))
  }, [])

  if (error) return <p className="text-red-500 text-sm">{error}</p>
  if (!movements) return <p className="text-slate-400 text-sm">{t('loading')}</p>

  const own     = movements.filter(m => m.isOwn)
  const hostile = movements.filter(m => m.isHostile)
  const allied  = movements.filter(m => !m.isOwn && !m.isHostile && m.isSameAlliance)
  const other   = movements.filter(m => !m.isOwn && !m.isHostile && !m.isSameAlliance)

  const Section = ({ title, items, color, icon }: { title: string; items: Movement[]; color: string; icon: string }) => {
    if (items.length === 0) return null
    return (
      <Card className="mb-4">
        <CardHeader icon={icon} title={`${title} (${items.length})`} />
        <div className="divide-y divide-slate-100">
          {items.map((m, i) => (
            <div key={i} className="px-5 py-3 flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <div className={`text-sm font-semibold ${color}`}>
                  {m.origin} <span className="font-mono">{m.direction}</span> {m.destination}
                </div>
                <div className="text-xs text-slate-500 mt-0.5">{m.mission}</div>
                {m.resources && m.resources.length > 0 && (
                  <div className="text-xs text-slate-400 mt-1">
                    {m.resources.map((r, j) => <span key={j} className="mr-2">{r.amount} {r.resource}</span>)}
                  </div>
                )}
                {m.troops != null && (
                  <div className="text-xs text-red-400 mt-1">{t('troops')}: {fmt(m.troops)} | {t('fleets')}: {fmt(m.fleets)}</div>
                )}
              </div>
              <div className="text-right flex-shrink-0">
                <div className="text-sm font-mono font-semibold text-slate-700">{fmtDuration(m.timeLeft)}</div>
                <div className="text-xs text-slate-400">{t('arrives_at')} {fmtArrival(m.arrivalTime, lang)}</div>
              </div>
            </div>
          ))}
        </div>
      </Card>
    )
  }

  return (
    <div>
      <PageHeader icon="fa-ship" title={t('movements_title')} />
      {movements.length === 0 ? (
        <Card className="p-8 text-center text-slate-400">
          <i className="fa-solid fa-anchor text-3xl mb-2 block" />
          {t('no_movements')}
        </Card>
      ) : (
        <>
          <Section title={t('section_own')}     items={own}     color="text-indigo-600" icon="fa-flag"             />
          <Section title={t('section_hostile')} items={hostile} color="text-red-600"    icon="fa-skull-crossbones" />
          <Section title={t('section_allied')}  items={allied}  color="text-green-600"  icon="fa-handshake"        />
          <Section title={t('section_other')}   items={other}   color="text-slate-600"  icon="fa-circle-info"      />
        </>
      )}
    </div>
  )
}
