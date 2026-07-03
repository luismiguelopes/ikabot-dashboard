import { useState } from 'react'
import { useT } from '../../i18n'
import { loadSpyDefaults } from '../SettingsPage'
import type { WorldScanPlayer, OwnCity } from '../../types'
import type { CitySpyCounts } from './types'

interface SpyModalProps {
  player: WorldScanPlayer
  ownCities: OwnCity[]
  spyCounts: Record<string, CitySpyCounts>
  originCityId: string
  onClose: () => void
  onDispatched: () => void
}

export function SpyModal({ player, ownCities, spyCounts, originCityId: defaultOriginCityId, onClose, onDispatched }: SpyModalProps) {
  const t = useT()
  const [originCityId, setOriginCityId] = useState<string>(
    defaultOriginCityId || (ownCities.length > 0 ? String(ownCities[0].cityId) : '')
  )
  const [numAgents, setNumAgents] = useState(loadSpyDefaults().numAgents)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const hasIslandId = !!player.cityId && !!player.islandId

  async function handleSend() {
    if (!originCityId || !hasIslandId) return
    setSending(true)
    setError(null)
    try {
      const res = await fetch('/api/espionage/dispatch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          originCityId,
          targetCityId: player.cityId,
          islandId: player.islandId,
          targetPlayerName: player.playerName,
          targetCityName: player.cityName,
          islandX: player.islandX,
          islandY: player.islandY,
          numAgents,
          numDecoys: 0,
        }),
      })
      const data = await res.json()
      if (!res.ok) { setError(data.error || 'Erro desconhecido'); return }
      onDispatched()
      onClose()
    } catch (e) {
      setError(String(e))
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-sm mx-4" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold text-slate-800">
            {t('spy_modal_title')} — <span className="text-indigo-600">{player.playerName}</span>
          </h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 text-lg leading-none">✕</button>
        </div>

        <div className="text-xs text-slate-500 mb-4 space-y-0.5">
          <div><span className="font-medium text-slate-700">{t('col_island')}:</span> {player.islandName} ({player.islandX},{player.islandY})</div>
          <div><span className="font-medium text-slate-700">{t('col_city')}:</span> {player.cityName}</div>
        </div>

        {!hasIslandId && (
          <div className="mb-4 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-700">
            {t('spy_no_city_id')}
          </div>
        )}

        <div className="space-y-3 mb-5">
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">{t('spy_origin_city')}</label>
            <select
              value={originCityId}
              onChange={e => setOriginCityId(e.target.value)}
              disabled={!hasIslandId}
              className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-400 disabled:opacity-50"
            >
              {ownCities.map(c => {
                const id = String(c.cityId)
                const sc = spyCounts[id]
                let label = c.name
                if (sc) {
                  if (sc.available != null)
                    label = `${c.name} (${sc.available} disponíveis)`
                  else if (sc.inDefense != null && sc.inDefense > 0)
                    label = `${c.name} (${sc.inDefense} em campo)`
                }
                return <option key={c.cityId} value={id}>{label}</option>
              })}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">{t('spy_num_agents')}</label>
            <input
              type="number"
              min={1}
              max={99}
              value={numAgents}
              onChange={e => setNumAgents(Math.max(1, parseInt(e.target.value) || 1))}
              disabled={!hasIslandId}
              className="w-24 text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-400 disabled:opacity-50"
            />
          </div>
        </div>

        {error && (
          <div className="mb-3 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700">{error}</div>
        )}

        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm text-slate-600 hover:text-slate-800 rounded-lg border border-slate-200 hover:bg-slate-50 transition-colors">
            {t('cancel')}
          </button>
          <button
            onClick={handleSend}
            disabled={sending || !hasIslandId || !originCityId}
            className="px-4 py-2 text-sm font-medium bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white rounded-lg transition-colors"
          >
            {sending ? t('spy_sending') : t('spy_send_btn')}
          </button>
        </div>
      </div>
    </div>
  )
}

