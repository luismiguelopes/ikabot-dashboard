import { useState, useEffect, useCallback } from 'react'
import { useT, useLang, getLocale } from '../../i18n'
import { Card } from '../ui/Card'
import { PageHeader } from '../ui/PageHeader'
import { loadSpyDefaults, saveSpyDefaults } from '../SettingsPage'
import { InactivosTab } from './InactivosTab'
import { IgnoradasTab } from './IgnoradasTab'
import { IlhasTab } from './IlhasTab'
import type { WorldScanData, ScanStatus, OwnCity } from '../../types'
import type { CitySpyCounts } from './types'

export function MundoPage({ onSelectIsland }: { onSelectIsland?: (preset: { resType: 'wood' | 'marble', level: number }) => void }) {
  const t    = useT()
  const lang = useLang()
  const [tab,        setTab]        = useState('inactivos')
  const [scanData,   setScanData]   = useState<WorldScanData | null>(null)
  const [scanStatus, setScanStatus] = useState<ScanStatus | null>(null)
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState<string | null>(null)
  const [ownCities,       setOwnCities]       = useState<OwnCity[]>([])
  const [spyCounts,       setSpyCounts]       = useState<Record<string, CitySpyCounts>>({})
  const [spyOriginCityId, setSpyOriginCityId] = useState<string>(() => loadSpyDefaults().originCityId)
  const [worldScanEnabled,     setWorldScanEnabled]     = useState(true)
  const [spyProcessingEnabled, setSpyProcessingEnabled] = useState(true)
  const [importingReports,     setImportingReports]     = useState(false)
  const [importMsg,            setImportMsg]            = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/own-cities').then(r => r.json()).then((d: OwnCity[]) => {
      if (Array.isArray(d)) {
        setOwnCities(d)
        setSpyOriginCityId(prev => prev || (d.length > 0 ? String(d[0].cityId) : ''))
      }
    }).catch(() => {})
    fetch('/api/espionage/spy-counts').then(r => r.json()).then(d => {
      if (d.counts) {
        const counts: Record<string, CitySpyCounts> = {}
        for (const [id, val] of Object.entries(d.counts)) {
          const v = val as Record<string, number | null>
          counts[id] = { available: v.available ?? null, inDefense: v.inDefense ?? null, inTraining: v.inTraining ?? null, deployed: v.deployed ?? null }
        }
        setSpyCounts(counts)
      }
    }).catch(() => {})
    fetch('/api/world-scan/settings').then(r => r.json())
      .then(d => { if (d.enabled !== undefined) setWorldScanEnabled(d.enabled) }).catch(() => {})
    fetch('/api/espionage/settings').then(r => r.json())
      .then(d => { if (d.processingEnabled !== undefined) setSpyProcessingEnabled(d.processingEnabled) }).catch(() => {})
  }, [])

  const handleSpyCityChange = useCallback((cityId: string) => {
    setSpyOriginCityId(cityId)
    saveSpyDefaults(cityId, loadSpyDefaults().numAgents)
  }, [])

  const handleWorldScanToggle = useCallback(() => {
    const next = !worldScanEnabled
    setWorldScanEnabled(next)
    fetch('/api/world-scan/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: next }),
    }).catch(() => setWorldScanEnabled(!next))
  }, [worldScanEnabled])

  const handleSpyProcessingToggle = useCallback(() => {
    const next = !spyProcessingEnabled
    setSpyProcessingEnabled(next)
    fetch('/api/espionage/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ processingEnabled: next }),
    }).catch(() => setSpyProcessingEnabled(!next))
  }, [spyProcessingEnabled])

  const fetchScan = useCallback(() => {
    fetch('/api/world-scan')
      .then(r => r.ok ? r.json() : r.json().then((e: { error: string }) => Promise.reject(e.error)))
      .then((d: WorldScanData) => {
        setScanData(d)
        setLoading(false)
      })
      .catch((e: unknown) => {
        setError(typeof e === 'string' ? e : 'Error loading scan data')
        setLoading(false)
      })
  }, [])

  const fetchStatus = useCallback(() => {
    fetch('/api/world-scan/status').then(r => r.json()).then(setScanStatus).catch(() => {})
  }, [])

  useEffect(() => { fetchScan(); fetchStatus() }, [fetchScan, fetchStatus])

  // Re-fetch scan data every 60s so auto-marks and new scan results appear without page reload
  useEffect(() => {
    const id = setInterval(fetchScan, 60000)
    return () => clearInterval(id)
  }, [fetchScan])

  useEffect(() => {
    if (scanStatus?.status !== 'running') return
    const timer = setInterval(() => {
      fetchStatus()
      if (scanStatus?.status !== 'running') fetchScan()
    }, 5000)
    return () => clearInterval(timer)
  }, [scanStatus?.status, fetchScan, fetchStatus])

  const handleForceRefresh = () => {
    fetch('/api/world-scan/refresh', { method: 'POST' })
      .then(() => alert(t('scan_scheduled_msg')))
  }

  const handleImportReports = useCallback(() => {
    setImportingReports(true)
    setImportMsg(null)
    fetch('/api/espionage/import-reports', { method: 'POST' })
      .then(r => r.json())
      .then(() => {
        setImportMsg(t('import_reports_ok'))
        setTimeout(() => setImportMsg(null), 5000)
      })
      .catch(() => setImportMsg(null))
      .finally(() => setImportingReports(false))
  }, [t])

  const isRunning      = scanStatus?.status === 'running'
  const lastUpdated    = scanData?.lastUpdated ? new Date(scanData.lastUpdated * 1000).toLocaleString(getLocale(lang)) : null
  const nextScan       = scanData?.lastUpdated ? new Date((scanData.lastUpdated + 7 * 24 * 3600) * 1000).toLocaleDateString(getLocale(lang)) : null
  const inactiveCount  = (scanData?.players || []).filter(p => p.state === 'inactive').length
  const newCount       = (scanData?.players || []).filter(p => p.state === 'inactive' && p.isNew).length

  const ignoredCount = (scanData?.players || []).filter(p => p.mark === 'ignorar').length

  const TABS = [
    { key: 'inactivos', label: t('tab_inactive'),  icon: 'fa-user-slash'        },
    { key: 'ilhas',     label: t('tab_islands'),   icon: 'fa-map'               },
    { key: 'ignoradas', label: `${t('tab_ignored')}${ignoredCount > 0 ? ` (${ignoredCount})` : ''}`, icon: 'fa-ban' },
  ]

  return (
    <div>
      <PageHeader icon="fa-earth-europe" title={t('world_title')} />

      <Card className="mb-4">
        <div className="px-5 py-4 flex flex-wrap items-start gap-4">
          <div className="flex-1 min-w-0 space-y-2">
            {lastUpdated ? (
              <p className="text-sm text-slate-600">
                <i className="fa-regular fa-clock mr-1.5 text-slate-400" />
                {t('last_scan_label')} <span className="font-medium text-slate-800">{lastUpdated}</span>
                {nextScan && <span className="ml-3 text-slate-400 text-xs">{t('next_scan_label')} {nextScan}</span>}
              </p>
            ) : (
              <p className="text-sm text-slate-500">{t('no_scan_yet')}</p>
            )}
            {scanData && (
              <p className="text-xs text-slate-400">
                {t('scan_radius')}: {scanData.scanRadius}
                {' · '}{t('inactive_label')}: <span className="font-semibold text-slate-600">{inactiveCount}</span>
                {newCount > 0 && <span className="ml-1.5 text-emerald-600 font-semibold">{t('new_count_world', { n: newCount })}</span>}
                {scanData.islands && <span>{' · '}{t('islands_count_world')}: <span className="font-semibold text-slate-600">{scanData.islands.length}</span></span>}
              </p>
            )}
            {isRunning && (
              <div>
                <p className="text-xs text-indigo-600 mb-1 flex items-center gap-1.5">
                  <span className="w-3 h-3 rounded-full border-2 border-indigo-300 border-t-indigo-600 animate-spin inline-block" />
                  {scanStatus!.message}
                </p>
                {scanStatus!.total > 0 && (
                  <div className="w-full max-w-xs h-1.5 bg-slate-200 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-indigo-500 rounded-full transition-all"
                      style={{ width: `${Math.round((scanStatus!.progress / scanStatus!.total) * 100)}%` }}
                    />
                  </div>
                )}
              </div>
            )}
            {/* Enable/disable toggles */}
            <div className="flex gap-2 pt-1">
              <button
                onClick={handleWorldScanToggle}
                className={`flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-lg border transition-colors ${
                  worldScanEnabled
                    ? 'bg-indigo-50 text-indigo-700 border-indigo-200 hover:bg-indigo-100'
                    : 'bg-slate-100 text-slate-500 border-slate-200 hover:bg-slate-200'
                }`}
              >
                <i className={`fa-solid ${worldScanEnabled ? 'fa-earth-europe' : 'fa-earth-europe opacity-40'} text-[10px]`} />
                {t('world_scan_toggle')}
                <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-bold ${worldScanEnabled ? 'bg-indigo-200 text-indigo-700' : 'bg-slate-200 text-slate-500'}`}>
                  {worldScanEnabled ? 'ON' : 'OFF'}
                </span>
              </button>
              <button
                onClick={handleSpyProcessingToggle}
                className={`flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-lg border transition-colors ${
                  spyProcessingEnabled
                    ? 'bg-indigo-50 text-indigo-700 border-indigo-200 hover:bg-indigo-100'
                    : 'bg-slate-100 text-slate-500 border-slate-200 hover:bg-slate-200'
                }`}
              >
                <i className={`fa-solid fa-user-secret text-[10px] ${spyProcessingEnabled ? '' : 'opacity-40'}`} />
                {t('spy_processing_toggle')}
                <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-bold ${spyProcessingEnabled ? 'bg-indigo-200 text-indigo-700' : 'bg-slate-200 text-slate-500'}`}>
                  {spyProcessingEnabled ? 'ON' : 'OFF'}
                </span>
              </button>
            </div>
          </div>
          <div className="flex flex-col items-end gap-2 shrink-0">
            <button
              onClick={handleForceRefresh}
              disabled={isRunning}
              className="flex items-center gap-2 px-4 py-2 bg-orange-500 hover:bg-orange-600 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
            >
              <i className="fa-solid fa-rotate" />
              {isRunning ? t('scanning') : t('force_scan')}
            </button>
            <button
              onClick={handleImportReports}
              disabled={importingReports}
              className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
            >
              <i className={`fa-solid ${importingReports ? 'fa-spinner fa-spin' : 'fa-file-import'}`} />
              {t('import_reports_btn')}
            </button>
            {importMsg && (
              <p className="text-xs text-emerald-600 font-medium">{importMsg}</p>
            )}
          </div>
        </div>
      </Card>

      <div className="flex items-center gap-3 mb-4">
        <div className="flex gap-1 bg-white border border-slate-200 rounded-xl p-1 shadow-sm">
          {TABS.map(tb => (
            <button
              key={tb.key}
              onClick={() => setTab(tb.key)}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                tab === tb.key ? 'bg-indigo-600 text-white shadow' : 'text-slate-500 hover:text-slate-700 hover:bg-slate-100'
              }`}
            >
              <i className={`fa-solid ${tb.icon} text-xs`} />{tb.label}
            </button>
          ))}
        </div>
        {ownCities.length > 0 && (
          <div className="flex items-center gap-1.5 bg-white border border-slate-200 rounded-xl px-3 py-1.5 shadow-sm">
            <i className="fa-solid fa-user-secret text-slate-400 text-xs" />
            <select
              value={spyOriginCityId}
              onChange={e => handleSpyCityChange(e.target.value)}
              className="text-sm border-none bg-transparent focus:outline-none text-slate-700 cursor-pointer"
            >
              {ownCities.map(c => {
                const id = String(c.cityId)
                const sc = spyCounts[id]
                const label = sc?.available != null ? `${c.name} (${sc.available})` : c.name
                return <option key={id} value={id}>{label}</option>
              })}
            </select>
          </div>
        )}
      </div>

      <div style={{ display: tab === 'inactivos' ? undefined : 'none' }}>
        <InactivosTab
          scanData={scanData}
          loading={loading}
          error={error}
          onForceRefresh={handleForceRefresh}
          ownCities={ownCities}
          spyCounts={spyCounts}
          spyOriginCityId={spyOriginCityId}
        />
      </div>
      <div style={{ display: tab === 'ilhas' ? undefined : 'none' }}>
        <IlhasTab
          scanData={scanData}
          loading={loading}
          error={error}
          onForceRefresh={handleForceRefresh}
          onSelectIsland={onSelectIsland}
        />
      </div>
      <div style={{ display: tab === 'ignoradas' ? undefined : 'none' }}>
        <IgnoradasTab scanData={scanData} onScanDataChange={setScanData} />
      </div>
    </div>
  )
}
