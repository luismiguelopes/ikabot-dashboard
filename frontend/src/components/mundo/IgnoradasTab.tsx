import { useCallback, useMemo } from 'react'
import { useT } from '../../i18n'
import { Card } from '../ui/Card'
import type { WorldScanData } from '../../types'

interface IgnoradasTabProps {
  scanData: WorldScanData | null
  onScanDataChange: (data: WorldScanData) => void
}

export function IgnoradasTab({ scanData, onScanDataChange }: IgnoradasTabProps) {
  const t = useT()

  const ignored = useMemo(() => {
    if (!scanData?.players) return []
    const seen = new Set<string>()
    return scanData.players
      .filter(p => p.mark === 'ignorar')
      .filter(p => {
        const key = `${p.playerId}_${p.islandX}_${p.islandY}`
        if (seen.has(key)) return false
        seen.add(key)
        return true
      })
      .sort((a, b) => (b.markUpdatedAt || 0) - (a.markUpdatedAt || 0))
  }, [scanData])

  const handleUnignore = useCallback((p: { playerId: string; islandX: number; islandY: number }) => {
    fetch('/api/world-scan/mark', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ playerId: p.playerId, islandX: p.islandX, islandY: p.islandY, status: 'novo', note: '' }),
    })
      .then(() => fetch('/api/world-scan'))
      .then(r => r.json())
      .then(d => { if (d.players) onScanDataChange(d) })
      .catch(() => {})
  }, [onScanDataChange])

  if (!ignored.length) {
    return <Card className="p-8 text-center text-slate-400 text-sm">{t('ignored_tab_empty')}</Card>
  }

  return (
    <Card className="overflow-hidden">
      <table className="w-full">
        <thead>
          <tr className="border-b border-slate-200 bg-slate-50 text-xs text-slate-500 uppercase tracking-wide">
            <th className="px-3 py-3 text-left">{t('col_city')}</th>
            <th className="px-3 py-3 text-left">{t('col_player')}</th>
            <th className="px-3 py-3 text-left">{t('ignored_reason')}</th>
            <th className="px-3 py-3 text-left">{t('ignored_date')}</th>
            <th className="px-3 py-3" />
          </tr>
        </thead>
        <tbody>
          {ignored.map((p, idx) => (
            <tr key={`${p.playerId}_${p.islandX}_${p.islandY}`}
              className={`border-b border-slate-100 ${idx % 2 ? 'bg-slate-50/40' : ''}`}>
              <td className="px-3 py-2">
                <div className="text-sm font-medium text-slate-700">{p.cityName}</div>
                <div className="text-xs text-slate-400">{p.islandName} ({p.islandX},{p.islandY})</div>
              </td>
              <td className="px-3 py-2 text-sm text-slate-700">{p.playerName}</td>
              <td className="px-3 py-2 text-xs text-slate-500">{p.markNote || t('reason_manual')}</td>
              <td className="px-3 py-2 text-xs text-slate-400">
                {p.markUpdatedAt ? new Date(p.markUpdatedAt * 1000).toLocaleDateString() : '—'}
              </td>
              <td className="px-3 py-2 text-right">
                <button
                  onClick={() => handleUnignore(p)}
                  className="px-2 py-1 text-xs bg-slate-100 hover:bg-slate-200 text-slate-600 rounded transition-colors"
                >
                  <i className="fa-solid fa-rotate-left mr-1" />{t('btn_unignore')}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  )
}


// ── IlhasTab ──────────────────────────────────────────────────────────────────

