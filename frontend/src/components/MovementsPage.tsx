import { useState, useEffect } from 'react'
import { pollInterval, clearPoll } from '../api'
import { useT, useLang } from '../i18n'
import { fmt, fmtDuration, fmtArrival } from '../utils'
import { useLiveClock } from '../hooks/useLiveClock'
import { RefreshButton } from './ui/RefreshButton'
import { Card, CardHeader } from './ui/Card'
import { PageHeader } from './ui/PageHeader'
import { TransportTab } from './TransportTab'
import type { Movement, ResourcesData } from '../types'

// Declared at module level (P13.55): inside MovementsTab it was a new component type on every
// render, so React unmounted and remounted every section each second. The clock now lives only
// in ArrivalCell — the countdown re-renders, the list around it does not.
function ArrivalCell({ arrivalTime }: { arrivalTime: number }) {
  const t    = useT()
  const lang = useLang()
  const now  = useLiveClock()
  const arrived = arrivalTime > 0 && arrivalTime <= now
  return (
    <div className="text-right flex-shrink-0">
      {arrived ? (
        <div className="text-sm font-semibold text-emerald-600">
          <i className="fa-solid fa-circle-check mr-1" />{t('arrived')}
        </div>
      ) : (
        <div className="text-sm font-mono font-semibold text-slate-700">{fmtDuration(Math.max(0, arrivalTime - now))}</div>
      )}
      <div className="text-xs text-slate-400">{t('arrives_at')} {fmtArrival(arrivalTime, lang)}</div>
    </div>
  )
}

function Section({ title, items, color, icon }: { title: string; items: Movement[]; color: string; icon: string }) {
  const t = useT()
  if (items.length === 0) return null
  return (
    <Card className="mb-4">
      <CardHeader icon={icon} title={`${title} (${items.length})`} />
      <div className="divide-y divide-slate-100">
        {items.map((m, i) => (
          <div key={`${m.origin}|${m.destination}|${m.mission}|${m.arrivalTime}|${i}`} className="px-5 py-3 flex items-start justify-between gap-4">
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
            <ArrivalCell arrivalTime={m.arrivalTime} />
          </div>
        ))}
      </div>
    </Card>
  )
}

function MovementsTab() {
  const [movements, setMovements] = useState<Movement[] | null>(null)
  const [error, setError]         = useState<string | null>(null)
  const t    = useT()

  // Only a real list is kept (an error body used to reach `.filter` and blank the page); a
  // failure keeps what is on screen and a later success clears it.
  const fetchMovements = () =>
    fetch('/api/movements')
      .then(r => r.json())
      .then(d => {
        if (!Array.isArray(d)) throw new Error((d && d.error) || 'Resposta inesperada')
        setMovements(d); setError(null)
      })
      .catch(e => setError(e.message))

  const handleRefresh = () => {
    fetch('/api/movements/refresh', { method: 'POST' }).catch(() => {})
    fetchMovements()
  }

  // The list was loaded once, on opening: movements reached "arrived" and stayed there.
  useEffect(() => {
    fetchMovements()
    const id = pollInterval(fetchMovements, 60000)
    return () => clearPoll(id)
  }, [])

  if (error && !movements) return (
    <div className="text-sm">
      <p className="text-red-500">{error}</p>
      <button onClick={fetchMovements} className="mt-2 px-3 py-1.5 rounded-lg border border-slate-200 bg-white text-slate-600 hover:bg-slate-50">
        <i className="fa-solid fa-rotate-right mr-1.5" />{t('refresh_btn')}
      </button>
    </div>
  )
  if (!movements) return <p className="text-slate-400 text-sm">{t('loading')}</p>

  const own     = movements.filter(m => m.isOwn)
  const hostile = movements.filter(m => m.isHostile)
  const allied  = movements.filter(m => !m.isOwn && !m.isHostile && m.isSameAlliance)
  const other   = movements.filter(m => !m.isOwn && !m.isHostile && !m.isSameAlliance)

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

export function MovementsPage({ resourcesData }: { resourcesData: ResourcesData }) {
  const t = useT()
  const [tab, setTab] = useState('movements')

  const tabs = [
    { key: 'movements', label: t('tab_movements'), icon: 'fa-ship'          },
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
      {tab === 'transport' && <TransportTab resourcesData={resourcesData} />}
    </div>
  )
}
