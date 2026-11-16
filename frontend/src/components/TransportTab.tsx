import { useState, useEffect, useCallback } from 'react'
import { apiAction } from '../api'
import { useT } from '../i18n'
import { useSettings } from '../hooks/useSettings'
import { useLiveRefresh } from '../hooks/useLiveRefresh'
import { PageHeader } from './ui/PageHeader'
import { WinePanorama } from './WinePanorama'
import { ManualTransportCard } from './transport/ManualTransportCard'
import { ConsolidateCard } from './transport/ConsolidateCard'
import { WineBalancerCard } from './transport/WineBalancerCard'
import { WineBuyCard } from './transport/WineBuyCard'
import { PendingTransports } from './transport/PendingTransports'
import type { PendingTransport, WineBuyStatus, WineSettings } from './transport/types'
import type { OwnCity, ResourcesData } from '../types'

// Page shell (P13.53): the cards live in ./transport/. The city resources come from the App's
// /api/data (it used to fetch the whole thing again); the pending list follows the bot's queue.
export function TransportTab({ resourcesData }: { resourcesData: ResourcesData }) {
  const t = useT()
  const [ownCities, setOwnCities] = useState<OwnCity[]>([])
  const [pending,   setPending]   = useState<PendingTransport[]>([])
  const [buyStatus, setBuyStatus] = useState<WineBuyStatus | null>(null)
  const wine = useSettings<WineSettings>('/api/transport/wine')

  const loadPending = useCallback(() => {
    fetch('/api/transport/queue').then(r => r.json())
      .then((d: any) => setPending(Array.isArray(d?.pending) ? d.pending : []))
      .catch(() => {})
  }, [])

  useEffect(() => {
    fetch('/api/own-cities').then(r => r.json())
      .then((d: unknown) => { if (Array.isArray(d)) setOwnCities(d as OwnCity[]) }).catch(() => {})
    fetch('/api/transport/wine-buy/status').then(r => r.json())
      .then((d: WineBuyStatus) => { if (d && d.now) setBuyStatus(d) }).catch(() => {})
    loadPending()
  }, [loadPending])

  // the transport queue is in SQLite: refresh when the bot dispatches or drops an item
  useLiveRefresh(loadPending, ['db'])

  async function handleCancel(id: string) {
    await apiAction('/api/transport/queue/cancel', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ id }),
    })
    loadPending()
  }

  return (
    <div>
      <PageHeader icon="fa-boxes-stacked" title={t('transport_title')} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
        <ManualTransportCard ownCities={ownCities} resourcesData={resourcesData} onQueued={loadPending} />
        <ConsolidateCard ownCities={ownCities} />
      </div>

      <WinePanorama resourcesData={resourcesData} wine={wine.data} buyStatus={buyStatus} />
      <WineBalancerCard settings={wine} />
      <WineBuyCard wine={wine.data} status={buyStatus} setStatus={setBuyStatus} />
      <PendingTransports pending={pending} onCancel={handleCancel} />
    </div>
  )
}
