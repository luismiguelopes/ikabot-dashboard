import { useState, useEffect, useCallback, useMemo, lazy, Suspense } from 'react'
import { LangContext, loadLang, useT, baseLang, setUiLang, LANGS } from './i18n'
import { loadThresholds } from './utils'
import { AUTO_REFRESH_SECONDS, MATERIALS } from './constants'
import type { ApiData, AlertThresholds, CityResources } from './types'
import type { IslandPreset } from './components/calculadoras/CalculadorasPage'
import { Sidebar } from './components/ui/Sidebar'
import { ToastHost } from './components/ui/Toast'
import { ConfirmHost } from './components/ui/Modal'
import { ErrorBoundary } from './components/ErrorBoundary'
import { computeAlerts } from './alerts'
import type { ExtraAlertSources } from './alerts'
import { useLiveRefresh } from './hooks/useLiveRefresh'
import { useLiveClock } from './hooks/useLiveClock'
import { setApiLang, pollInterval, clearPoll, emitLive } from './api'
import type { LiveTopic } from './api'
import { useNotifications, loadBrowserNotifEnabled } from './hooks/useNotifications'
import { HomePage } from './components/HomePage'
import { CitiesPage } from './components/CitiesPage'
import { BuildingsPage } from './components/BuildingsPage'
import { MovementsPage } from './components/MovementsPage'
import { AlertsPage } from './components/AlertsPage'
// chart.js (200 KB) is only needed on the History page — load it when that page opens
const HistoryPage = lazy(() => import('./components/HistoryPage').then(m => ({ default: m.HistoryPage })))
import { CalculadorasPage } from './components/calculadoras/CalculadorasPage'
import { BuildingQueueTab } from './components/Construction'
import { MundoPage } from './components/mundo/MundoPage'
import { CombatPage } from './components/CombatPage'
import { SettingsPage } from './components/SettingsPage'
import { LogsPage } from './components/LogsPage'

function PausedBanner() {
  const t = useT()
  return (
    <div className="mb-4 flex items-center gap-2 text-sm text-amber-800 bg-amber-50 border border-amber-300 rounded-lg px-4 py-2.5">
      <i className="fa-solid fa-pause shrink-0" />
      {t('pause_banner')}
    </div>
  )
}

function SubsystemHealthBanner() {
  const t = useT()
  const [down, setDown] = useState<string[]>([])
  const [cfg, setCfg] = useState<string[]>([])
  useEffect(() => {
    let stop = false
    const check = () => {
      fetch('/api/health')
        .then(r => r.json())
        .then((d: { subsystems?: Record<string, { consecutiveFailures?: number }>
                    configWarnings?: Record<string, string[]> }) => {
          if (stop) return
          const subs = d.subsystems || {}
          setDown(Object.keys(subs).filter(k => (subs[k]?.consecutiveFailures ?? 0) >= 3))
          setCfg(Object.keys(d.configWarnings || {}))
        })
        .catch(() => {})
    }
    check()
    const id = pollInterval(check, 60000)
    return () => { stop = true; clearPoll(id) }
  }, [])
  return (
    <>
      {down.length > 0 && (
        <div className="mb-4 flex items-center gap-2 text-sm text-red-800 bg-red-50 border border-red-300 rounded-lg px-4 py-2.5 font-medium">
          <i className="fa-solid fa-heart-crack shrink-0" />
          {t('health_banner')}: <span className="font-mono">{down.join(', ')}</span>
        </div>
      )}
      {cfg.length > 0 && (
        <div className="mb-4 flex items-center gap-2 text-sm text-amber-800 bg-amber-50 border border-amber-300 rounded-lg px-4 py-2.5">
          <i className="fa-solid fa-gear shrink-0" />
          {t('config_banner')}: <span className="font-mono">{cfg.join(', ')}</span>
        </div>
      )}
    </>
  )
}

function IncomingAttackBanner({ count, eta }: { count: number; eta: number | null }) {
  const t = useT()
  const now = Math.floor(Date.now() / 1000)
  const mins = eta ? Math.max(0, Math.round((eta - now) / 60)) : null
  return (
    <div className="mb-4 flex items-center gap-2 text-sm text-red-800 bg-red-50 border border-red-300 rounded-lg px-4 py-2.5 font-medium">
      <i className="fa-solid fa-skull-crossbones shrink-0" />
      {t('incoming_banner', { n: String(count) })}
      {mins !== null && <span className="text-red-600">· {t('incoming_eta', { m: String(mins) })}</span>}
    </div>
  )
}

function LoadingScreen() {
  return (
    <div className="flex items-center justify-center h-screen bg-slate-100">
      <div className="text-center">
        <div className="w-12 h-12 rounded-full border-4 border-indigo-200 border-t-indigo-600 animate-spin mx-auto mb-4" />
        <p className="text-slate-500 text-sm">A carregar dados do império…</p>
      </div>
    </div>
  )
}

function ErrorScreen({ message }: { message: string }) {
  return (
    <div className="flex items-center justify-center h-screen bg-slate-100">
      <div className="bg-white rounded-xl border border-red-200 shadow p-8 text-center max-w-sm">
        <div className="w-12 h-12 rounded-full bg-red-50 flex items-center justify-center mx-auto mb-4">
          <i className="fa-solid fa-triangle-exclamation text-red-400 text-xl" />
        </div>
        <h2 className="text-slate-800 font-semibold mb-2">Erro ao carregar dados</h2>
        <p className="text-red-500 text-sm">{message}</p>
        <button
          onClick={() => window.location.reload()}
          className="mt-4 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm rounded-lg transition-colors"
        >
          Tentar novamente
        </button>
      </div>
    </div>
  )
}

export default function App() {
  const [lang, setLang] = useState(loadLang)
  // Keep the (non-React) apiAction helper's default error text in the active language.
  useEffect(() => { setApiLang(baseLang(lang) as 'pt' | 'en'); setUiLang(lang) }, [lang])
  const toggleLang = useCallback((target?: string) => {
    setLang(prev => {
      const i = LANGS.indexOf(prev as typeof LANGS[number])
      const next = target ?? LANGS[(i + 1) % LANGS.length]
      try { localStorage.setItem('ikabot_lang', next) } catch {}
      return next
    })
  }, [])

  const [defaultTab, setDefaultTab] = useState(() => {
    try { return localStorage.getItem('ikabot_default_tab') || 'home' } catch { return 'home' }
  })
  const saveDefaultTab = useCallback((tab: string) => {
    setDefaultTab(tab)
    try { localStorage.setItem('ikabot_default_tab', tab) } catch {}
  }, [])

  const [page, setPage] = useState(() => {
    try { return localStorage.getItem('ikabot_default_tab') || 'home' } catch { return 'home' }
  })
  const [data, setData] = useState<ApiData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [thresholds, setThresholds] = useState<AlertThresholds>(loadThresholds)

  const saveThresholds = useCallback((t: AlertThresholds) => {
    setThresholds(t)
    try { localStorage.setItem('ikabot_alert_thresholds', JSON.stringify(t)) } catch {}
    fetch('/api/alert-thresholds', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(t),
    }).catch(() => {})
  }, [])

  // P6.4: thresholds live on the server (same values on every device); localStorage is only
  // a fast-start cache. First load after the migration pushes the local values up once.
  useEffect(() => {
    fetch('/api/alert-thresholds')
      .then(r => r.json())
      .then((d: { configured: boolean; wineWarning: number; wineCritical: number; storageWarning: number }) => {
        if (d.configured) {
          const t = { wineWarning: d.wineWarning, wineCritical: d.wineCritical, storageWarning: d.storageWarning }
          setThresholds(t)
          try { localStorage.setItem('ikabot_alert_thresholds', JSON.stringify(t)) } catch {}
        } else {
          fetch('/api/alert-thresholds', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(loadThresholds()),
          }).catch(() => {})
        }
      })
      .catch(() => {})
  }, [])

  const [notifEnabled, setNotifEnabled] = useState(loadBrowserNotifEnabled)
  useNotifications(data, thresholds, notifEnabled)

  const [calcIslandPreset, setCalcIslandPreset] = useState<IslandPreset | null>(null)
  const handleSelectIsland = useCallback((preset: IslandPreset) => {
    setCalcIslandPreset(preset)
    setPage('calc')
  }, [])

  const fetchData = useCallback(() => {
    fetch('/api/data')
      .then(r => r.json())
      .then((d: ApiData & { error?: string }) => {
        if (d?.error) setError(d.error)
        // only a body with the parts every page reads (P13.56): anything else would reach
        // the Home page and blank it on `statusSummary.resources`
        else if (!d || typeof d.statusSummary !== 'object' || !d.statusSummary?.resources
                 || typeof d.resourcesData !== 'object' || typeof d.empireData !== 'object') setError('unexpected response')
        else { setData(d); setError(null) }   // a later success clears an earlier failure
      })
      .catch(e => setError(e.message))
  }, [])

  // While there is nothing to show yet, keep trying: a passing failure (dashboard restarting)
  // used to leave the error screen up until the page was reloaded by hand.
  useEffect(() => {
    if (!error || data) return
    const id = setInterval(fetchData, 5000)
    return () => clearInterval(id)
  }, [error, data, fetchData])

  useEffect(() => { fetchData() }, [fetchData])


  // Global pause (F11) — fetched from the bot, toggled from the sidebar
  const [paused, setPaused] = useState(false)
  const refreshPause = useCallback(() => {
    fetch('/api/pause').then(r => r.json()).then((d: { paused?: boolean }) => setPaused(!!d.paused)).catch(() => {})
  }, [])
  useEffect(() => { refreshPause() }, [refreshPause])
  const togglePause = useCallback(() => {
    const next = !paused
    setPaused(next)  // optimistic
    fetch('/api/pause', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paused: next }),
    }).then(r => r.json()).then((d: { paused?: boolean }) => setPaused(!!d.paused)).catch(refreshPause)
  }, [paused, refreshPause])

  const [sseConnected, setSseConnected] = useState(true)
  const [liveAlive, setLiveAlive] = useState<number | null>(null)

  useEffect(() => {
    const es = new EventSource('/api/stream')
    es.onopen = () => setSseConnected(true)
    es.onerror = () => setSseConnected(false)
    // the empire data reloads here; everything else listens through useLiveRefresh (P13.40)
    es.addEventListener('update', () => { fetchData(); emitLive(['empire']) })
    es.addEventListener('change', (e: MessageEvent) => {
      const known: LiveTopic[] = ['db', 'spy', 'military']
      emitLive(String(e.data).split(',').filter((x): x is LiveTopic => known.includes(x as LiveTopic)))
    })
    // the bot's heartbeat: just the timestamp, no reload of the empire data
    es.addEventListener('alive', (e: MessageEvent) => {
      const ts = Number(e.data)
      if (ts > 0) setLiveAlive(ts)
    })
    const fallback = pollInterval(fetchData, AUTO_REFRESH_SECONDS * 1000)
    return () => { es.close(); clearPoll(fallback) }
  }, [fetchData])

  const [movCount, setMovCount] = useState(0)
  const [incomingAttacks, setIncomingAttacks] = useState<{ count: number; eta: number | null }>({ count: 0, eta: null })
  const [sidebarOpen, setSidebarOpen] = useState(false)   // mobile drawer (desktop: always open)
  useEffect(() => {
    fetch('/api/movements')
      .then(r => r.json())
      .then((m: Array<{ isOwn: boolean; isHostile: boolean; direction: string; arrivalTime: number }>) => {
        setMovCount(m.filter(x => x.isOwn).length)
        const inc = m.filter(x => x.isHostile && x.direction === '->')
        setIncomingAttacks({ count: inc.length, eta: inc.length ? Math.min(...inc.map(x => x.arrivalTime)) : null })
      })
      .catch(() => {})
  }, [data])

  // Alerts beyond the empire data (P13.58): failing subsystems and transports, from the bot.
  const [extraRemote, setExtraRemote] = useState<Pick<ExtraAlertSources, 'subsystems' | 'transportRetrying' | 'transportDropped'>>({})
  const loadExtra = useCallback(() => {
    fetch('/api/alerts/extra').then(r => { if (!r.ok) throw new Error(); return r.json() }).then(d => {
      if (d && Array.isArray(d.subsystems) && Array.isArray(d.transportRetrying) && Array.isArray(d.transportDropped))
        setExtraRemote({ subsystems: d.subsystems, transportRetrying: d.transportRetrying, transportDropped: d.transportDropped })
    }).catch(() => {})
  }, [])
  useEffect(() => { loadExtra() }, [loadExtra])
  // health.json is not watched by the SSE: a slow poll covers the subsystems
  useLiveRefresh(loadExtra, ['db', 'empire'], { fallbackMs: 60000, minGapMs: 10000 })
  const minuteClock = useLiveClock(60000)
  const heartbeat = Math.max(liveAlive ?? 0, data?.lastAlive ?? 0) || null
  const extraAlerts = useMemo<ExtraAlertSources>(() => ({
    ...extraRemote,
    incoming: incomingAttacks,
    silentFor: heartbeat ? minuteClock - heartbeat : null,
    offlineAfterSecs: data?.offlineAfterSecs,
  }), [extraRemote, incomingAttacks, heartbeat, minuteClock, data?.offlineAfterSecs])

  // same list the Alerts page shows — the two used to count differently
  const alertCount = useMemo(() => (data ? computeAlerts(data, thresholds, extraAlerts).length : 0), [data, thresholds, extraAlerts])

  // Only when there is no data at all: a refresh that fails keeps showing what we have.
  if (error && !data) return (
    <LangContext.Provider value={lang}>
      <ErrorScreen message={error} />
    </LangContext.Provider>
  )
  if (!data) return (
    <LangContext.Provider value={lang}>
      <LoadingScreen />
    </LangContext.Provider>
  )

  return (
    <LangContext.Provider value={lang}>
      <div className="flex h-screen overflow-hidden">
        <Sidebar
          active={page}
          setActive={setPage}
          lastUpdated={data.lastUpdated}
          lastUpdatedTs={data.lastUpdatedTs}
          nextCycleAt={data.nextCycleAt}
          lastAlive={Math.max(liveAlive ?? 0, data.lastAlive ?? 0) || null}
          offlineAfterSecs={data.offlineAfterSecs}
          alertCount={alertCount}
          movCount={movCount}
          sseConnected={sseConnected}
          paused={paused}
          onTogglePause={togglePause}
          open={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
        />
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Mobile top bar — hidden on desktop (md+), where the sidebar is always visible */}
          <header className="md:hidden flex items-center gap-3 h-14 px-4 bg-slate-900 flex-shrink-0">
            <button
              onClick={() => setSidebarOpen(true)}
              aria-label="Menu"
              className="text-slate-200 hover:text-white w-9 h-9 flex items-center justify-center rounded-lg hover:bg-slate-700 transition-colors"
            >
              <i className="fa-solid fa-bars text-lg" />
            </button>
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-lg bg-indigo-600 flex items-center justify-center">
                <i className="fa-solid fa-globe text-white text-xs" />
              </div>
              <span className="text-white font-bold tracking-tight">Ikabot</span>
            </div>
          </header>
          <main className="flex-1 overflow-y-auto bg-slate-100 p-4 md:p-8">
            {incomingAttacks.count > 0 && <IncomingAttackBanner count={incomingAttacks.count} eta={incomingAttacks.eta} />}
            {paused && <PausedBanner />}
            <SubsystemHealthBanner />
            <ErrorBoundary key={page} label={page}>
              {page === 'home'         && <HomePage      data={data} thresholds={thresholds} paused={paused}
                                                       lastAlive={Math.max(liveAlive ?? 0, data.lastAlive ?? 0) || null} />}
              {page === 'cities'       && <CitiesPage    data={data} onRefresh={fetchData} thresholds={thresholds} />}
              {page === 'buildings'    && <BuildingsPage data={data} onRefresh={fetchData} />}
              {page === 'movements'    && <MovementsPage resourcesData={data.resourcesData} />}
              {page === 'alerts'       && <AlertsPage    data={data} thresholds={thresholds} extra={extraAlerts} />}
              {page === 'history'      && <Suspense fallback={null}><HistoryPage data={data} /></Suspense>}
              {page === 'calc'         && <CalculadorasPage data={data} islandPreset={calcIslandPreset} />}
              {page === 'construction' && <BuildingQueueTab data={data} />}
              {page === 'mundo'        && <MundoPage onSelectIsland={handleSelectIsland} />}
              {page === 'combate'      && <CombatPage />}
              {page === 'logs'         && <LogsPage />}
              {page === 'settings'     && <SettingsPage thresholds={thresholds} onSaveThresholds={saveThresholds} toggleLang={toggleLang} defaultTab={defaultTab} onSaveDefaultTab={saveDefaultTab} notifEnabled={notifEnabled} onToggleNotif={setNotifEnabled} />}
            </ErrorBoundary>
          </main>
        </div>
      </div>
      <ToastHost />
      <ConfirmHost />
    </LangContext.Provider>
  )
}
