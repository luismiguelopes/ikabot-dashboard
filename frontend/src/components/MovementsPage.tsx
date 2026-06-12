import { useState, useEffect } from 'react'
import { useT, useLang } from '../i18n'
import { fmt, fmtDuration, fmtArrival } from '../utils'
import { useLiveClock } from '../hooks/useLiveClock'
import { RefreshButton } from './ui/RefreshButton'
import { Card, CardHeader } from './ui/Card'
import { PageHeader } from './ui/PageHeader'
import { DispatchTab } from './DispatchTab'
import { TransportTab } from './TransportTab'
import type { Movement } from '../types'

function MovementsTab() {
  const [movements, setMovements] = useState<Movement[] | null>(null)
  const [error, setError]         = useState<string | null>(null)
  const t    = useT()
  const lang = useLang()
  const now  = useLiveClock()

  const fetchMovements = () =>
    fetch('/api/movements')
      .then(r => r.json())
      .then(setMovements)
      .catch(e => setError(e.message))

  const handleRefresh = () => {
    fetch('/api/movements/refresh', { method: 'POST' }).catch(() => {})
    fetchMovements()
  }

  useEffect(() => { fetchMovements() }, [])

  if (error)      return <p className="text-red-500 text-sm">{error}</p>
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
          {items.map((m, i) => {
            const timeLeft = Math.max(0, m.arrivalTime - now)
            const arrived  = m.arrivalTime > 0 && m.arrivalTime <= now
            return (
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
                  {arrived ? (
                    <div className="text-sm font-semibold text-emerald-600">
                      <i className="fa-solid fa-circle-check mr-1" />{t('arrived')}
                    </div>
                  ) : (
                    <div className="text-sm font-mono font-semibold text-slate-700">{fmtDuration(timeLeft)}</div>
                  )}
                  <div className="text-xs text-slate-400">{t('arrives_at')} {fmtArrival(m.arrivalTime, lang)}</div>
                </div>
              </div>
            )
          })}
        </div>
      </Card>
    )
  }

  return (
    <div>
      <div className="flex justify-end mb-4">
        <RefreshButton onRefresh={handleRefresh} />
      </div>
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

export function MovementsPage() {
  const t = useT()
  const [tab, setTab] = useState('movements')

  const tabs = [
    { key: 'movements', label: t('tab_movements'), icon: 'fa-ship'          },
    { key: 'dispatch',  label: t('tab_dispatch'),  icon: 'fa-crosshairs'    },
    { key: 'transport', label: t('tab_transport'), icon: 'fa-boxes-stacked' },
  ]

  return (
    <div>
      <PageHeader icon="fa-ship" title={t('movements_title')} />
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
      {tab === 'movements' && <MovementsTab />}
      {tab === 'dispatch'  && <DispatchTab />}
      {tab === 'transport' && <TransportTab />}
    </div>
  )
}
