import { useState, useEffect } from 'react'
import { useT } from '../../i18n'
import type { WorldScanPlayer, OwnCity } from '../../types'

interface MilitaryUnit { name: string; amount: number }
interface CityMilitary { cityId: string; troops: Record<string, MilitaryUnit>; fleet: Record<string, MilitaryUnit> }
interface MilitaryData { lastUpdated: number; byCityName: Record<string, CityMilitary> }

interface AttackModalProps {
  player: WorldScanPlayer
  ownCities: OwnCity[]
  defaultOriginCityId: string
  onClose: () => void
  onQueued: (playerName: string) => void
}

export function AttackModal({ player, ownCities, defaultOriginCityId, onClose, onQueued }: AttackModalProps) {
  const t = useT()
  const [originCityId, setOriginCityId] = useState(
    defaultOriginCityId || (ownCities.length > 0 ? String(ownCities[0].cityId) : '')
  )
  const [military, setMilitary] = useState<MilitaryData | null>(null)
  const [unitInputs, setUnitInputs] = useState<Record<string, number>>({})
  const [transporters, setTransporters] = useState(0)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/military').then(r => r.json()).then((d: MilitaryData) => setMilitary(d)).catch(() => {})
  }, [])

  const originCityName = ownCities.find(c => String(c.cityId) === originCityId)?.name || ''
  const units = military?.byCityName[originCityName]?.troops || {}
  const hasUnits = Object.values(unitInputs).some(v => v > 0)

  async function handleConfirm() {
    if (!hasUnits) { setError(t('attack_no_units')); return }
    if (!player.cityId || !player.islandId) { setError(t('spy_no_city_id')); return }
    setSending(true)
    setError(null)
    try {
      const res = await fetch('/api/espionage/attack-queue/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          originCityId,
          originCityName,
          targetCityId: player.cityId,
          targetCityName: player.cityName,
          targetPlayerName: player.playerName,
          islandX: player.islandX,
          islandY: player.islandY,
          islandId: player.islandId,
          units: unitInputs,
          transporters,
        }),
      })
      const data = await res.json()
      if (!res.ok) { setError(data.error || 'Erro desconhecido'); return }
      onQueued(player.playerName)
      onClose()
    } catch (e) {
      setError(String(e))
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-md mx-4 max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold text-slate-800 flex items-center gap-2">
            <i className="fa-solid fa-crosshairs text-red-500" />
            {t('attack_modal_title')} — <span className="text-red-600">{player.playerName}</span>
          </h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 text-lg leading-none">✕</button>
        </div>

        <div className="text-xs text-slate-500 mb-4 space-y-0.5">
          <div><span className="font-medium text-slate-700">{t('col_island')}:</span> {player.islandName} ({player.islandX},{player.islandY})</div>
          <div><span className="font-medium text-slate-700">{t('col_city')}:</span> {player.cityName}</div>
        </div>

        <div className="mb-4">
          <label className="block text-xs font-medium text-slate-600 mb-1">{t('attack_origin_city')}</label>
          <select
            value={originCityId}
            onChange={e => { setOriginCityId(e.target.value); setUnitInputs({}) }}
            className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-red-400"
          >
            {ownCities.map(c => (
              <option key={c.cityId} value={String(c.cityId)}>{c.name}</option>
            ))}
          </select>
        </div>

        <div className="mb-4">
          <p className="text-xs font-medium text-slate-600 mb-2">{t('attack_troops_table')}</p>
          {!military || Object.keys(units).length === 0 ? (
            <p className="text-xs text-slate-400 italic">{t('attack_no_military')}</p>
          ) : (
            <div className="border border-slate-200 rounded-lg overflow-hidden">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-slate-50 border-b border-slate-200">
                    <th className="text-left px-3 py-2 font-medium text-slate-600">Unidade</th>
                    <th className="text-center px-3 py-2 font-medium text-slate-600">{t('attack_available')}</th>
                    <th className="text-center px-3 py-2 font-medium text-slate-600">{t('attack_send_count')}</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(units).map(([uid, unit]) => (
                    <tr key={uid} className="border-b border-slate-100 last:border-0">
                      <td className="px-3 py-2 text-slate-700">{unit.name}</td>
                      <td className="px-3 py-2 text-center text-slate-500 font-mono">{unit.amount.toLocaleString()}</td>
                      <td className="px-3 py-2 text-center">
                        <input
                          type="number" min={0} max={unit.amount}
                          value={unitInputs[uid] ?? 0}
                          onChange={e => {
                            const n = Math.max(0, Math.min(unit.amount, parseInt(e.target.value) || 0))
                            setUnitInputs(prev => ({ ...prev, [uid]: n }))
                          }}
                          className="w-20 text-xs border border-slate-200 rounded px-2 py-1 text-center focus:outline-none focus:ring-1 focus:ring-red-400"
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="mb-5">
          <label className="block text-xs font-medium text-slate-600 mb-1">{t('attack_ships')}</label>
          <input
            type="number" min={0} value={transporters}
            onChange={e => setTransporters(Math.max(0, parseInt(e.target.value) || 0))}
            className="w-24 text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-red-400"
          />
        </div>

        {error && (
          <div className="mb-3 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700">{error}</div>
        )}

        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm text-slate-600 hover:text-slate-800 rounded-lg border border-slate-200 hover:bg-slate-50 transition-colors">
            {t('cancel')}
          </button>
          <button
            onClick={handleConfirm}
            disabled={sending || !hasUnits || !player.cityId || !player.islandId}
            className="px-4 py-2 text-sm font-medium bg-red-600 hover:bg-red-700 disabled:opacity-40 text-white rounded-lg transition-colors flex items-center gap-2"
          >
            {sending
              ? <><i className="fa-solid fa-spinner fa-spin" /> {t('spy_sending')}</>
              : <><i className="fa-solid fa-crosshairs" /> {t('attack_confirm')}</>
            }
          </button>
        </div>
      </div>
    </div>
  )
}

