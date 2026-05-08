import { useState, useEffect, useCallback, useMemo } from 'react'
import { LangContext, loadLang } from './i18n'
import { loadThresholds } from './utils'
import { AUTO_REFRESH_SECONDS, MATERIALS } from './constants'
import type { ApiData, AlertThresholds, CityResources } from './types'
import { Sidebar } from './components/ui/Sidebar'
import { HomePage } from './components/HomePage'
import { CitiesPage } from './components/CitiesPage'
import { BuildingsPage } from './components/BuildingsPage'
import { MovementsPage } from './components/MovementsPage'
import { AlertsPage } from './components/AlertsPage'
import { HistoryPage } from './components/HistoryPage'
import { CalculadorasPage } from './components/calculadoras/CalculadorasPage'
import { BuildingQueueTab } from './components/Construction'
import { MundoPage } from './components/mundo/MundoPage'

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
  const toggleLang = useCallback(() => {
    setLang(prev => {
      const next = prev === 'en' ? 'pt' : 'en'
      try { localStorage.setItem('ikabot_lang', next) } catch {}
      return next
    })
  }, [])

  const [page, setPage] = useState('home')
  const [data, setData] = useState<ApiData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [thresholds, setThresholds] = useState<AlertThresholds>(loadThresholds)

  const saveThresholds = useCallback((t: AlertThresholds) => {
    setThresholds(t)
    try { localStorage.setItem('ikabot_alert_thresholds', JSON.stringify(t)) } catch {}
  }, [])

  const fetchData = useCallback(() => {
    fetch('/api/data')
      .then(r => r.json())
      .then((d: ApiData & { error?: string }) => {
        if (d.error) setError(d.error)
        else setData(d)
      })
      .catch(e => setError(e.message))
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  useEffect(() => {
    const es = new EventSource('/api/stream')
    es.addEventListener('update', fetchData)
    const fallback = setInterval(fetchData, AUTO_REFRESH_SECONDS * 1000)
    return () => { es.close(); clearInterval(fallback) }
  }, [fetchData])

  const alertCount = useMemo(() => {
    if (!data) return 0
    let n = 0
    Object.values(data.resourcesData).forEach((city: CityResources) => {
      const wt = city.wineRunsOutIn
      if (wt !== -1 && wt !== undefined && wt < thresholds.wineWarning * 3600) n++
      const cap = city.storageCapacity
      if (cap) MATERIALS.forEach(m => {
        const amount = (city[m.en as keyof CityResources] as number) || 0
        if (amount / cap >= thresholds.storageWarning / 100) n++
      })
    })
    if (data.statusSummary.gold.production < 0) n++
    return n
  }, [data, thresholds])

  const [movCount, setMovCount] = useState(0)
  useEffect(() => {
    fetch('/api/movements')
      .then(r => r.json())
      .then((m: Array<{ isOwn: boolean }>) => setMovCount(m.filter(x => x.isOwn).length))
      .catch(() => {})
  }, [data])

  if (error) return (
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
          lastAlive={data.lastAlive}
          alertCount={alertCount}
          movCount={movCount}
          lang={lang}
          toggleLang={toggleLang}
        />
        <main className="flex-1 overflow-y-auto bg-slate-100 p-6 md:p-8">
          {page === 'home'         && <HomePage      data={data} />}
          {page === 'cities'       && <CitiesPage    data={data} />}
          {page === 'buildings'    && <BuildingsPage data={data} />}
          {page === 'movements'    && <MovementsPage />}
          {page === 'alerts'       && <AlertsPage    data={data} thresholds={thresholds} onSaveThresholds={saveThresholds} />}
          {page === 'history'      && <HistoryPage />}
          {page === 'calc'         && <CalculadorasPage data={data} />}
          {page === 'construction' && <BuildingQueueTab data={data} />}
          {page === 'mundo'        && <MundoPage />}
        </main>
      </div>
    </LangContext.Provider>
  )
}
