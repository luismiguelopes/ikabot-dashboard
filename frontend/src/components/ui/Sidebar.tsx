import { useState, useEffect } from 'react'
import { useT } from '../../i18n'
import { fmtCountdown } from '../../utils'

function NavItem({ icon, label, active, onClick, badge }: {
  icon: string; label: string; active: boolean; onClick: () => void; badge?: number
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium transition-all duration-150 ${
        active
          ? 'bg-indigo-600 text-white shadow'
          : 'text-slate-400 hover:bg-slate-700 hover:text-slate-100'
      }`}
    >
      <i className={`fa-solid ${icon} w-4 text-center text-sm`} />
      <span className="flex-1 text-left">{label}</span>
      {(badge ?? 0) > 0 && (
        <span className="bg-red-500 text-white text-xs font-bold rounded-full w-5 h-5 flex items-center justify-center">
          {badge}
        </span>
      )}
    </button>
  )
}

interface SidebarProps {
  active: string
  setActive: (p: string) => void
  lastUpdated: string
  lastUpdatedTs: number
  nextCycleAt: number | null
  lastAlive: number | null
  alertCount: number
  movCount: number
  sseConnected: boolean
}

export function Sidebar({ active, setActive, lastUpdated, lastUpdatedTs, nextCycleAt, lastAlive, alertCount, movCount, sseConnected }: SidebarProps) {
  const t = useT()
  const isStale = lastUpdatedTs && (Date.now() / 1000 - lastUpdatedTs) > 70 * 60
  const isBotOffline = lastAlive && (Date.now() / 1000 - lastAlive) > 90 * 60

  const [, setTick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setTick(p => p + 1), 1000)
    return () => clearInterval(id)
  }, [])

  const secsUntilUpdate = nextCycleAt
    ? Math.max(0, nextCycleAt - Math.floor(Date.now() / 1000))
    : null

  return (
    <aside className="w-56 flex-shrink-0 bg-slate-900 flex flex-col h-screen">
      <div className="px-5 py-6 border-b border-slate-700/60">
        <div className="flex items-center gap-2 mb-1">
          <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center">
            <i className="fa-solid fa-globe text-white text-sm" />
          </div>
          <span className="text-white font-bold text-base tracking-tight">Ikabot</span>
        </div>
        <p className="text-slate-500 text-xs pl-10">Empire Dashboard</p>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        <NavItem icon="fa-house"                label={t('nav_home')}         active={active === 'home'}         onClick={() => setActive('home')}         />
        <NavItem icon="fa-city"                 label={t('nav_cities')}       active={active === 'cities'}       onClick={() => setActive('cities')}       />
        <NavItem icon="fa-landmark"             label={t('nav_buildings')}    active={active === 'buildings'}    onClick={() => setActive('buildings')}    />
        <NavItem icon="fa-ship"                 label={t('nav_movements')}    active={active === 'movements'}    onClick={() => setActive('movements')}    badge={movCount} />
        <NavItem icon="fa-triangle-exclamation" label={t('nav_alerts')}       active={active === 'alerts'}       onClick={() => setActive('alerts')}       badge={alertCount} />
        <NavItem icon="fa-chart-line"           label={t('nav_history')}      active={active === 'history'}      onClick={() => setActive('history')}      />
        <NavItem icon="fa-calculator"           label={t('nav_calculators')}  active={active === 'calc'}         onClick={() => setActive('calc')}         />
        <NavItem icon="fa-list-check"           label={t('nav_construction')} active={active === 'construction'} onClick={() => setActive('construction')} />
        <NavItem icon="fa-earth-europe"         label={t('nav_world')}        active={active === 'mundo'}        onClick={() => setActive('mundo')}        />
        <NavItem icon="fa-crosshairs"           label={t('nav_dispatch')}     active={active === 'dispatch'}     onClick={() => setActive('dispatch')}     />
      </nav>

      {/* Settings — visually separated, above status footer */}
      <div className="px-3 py-2 border-t border-slate-700/60">
        <NavItem icon="fa-gear" label={t('settings')} active={active === 'settings'} onClick={() => setActive('settings')} />
      </div>

      <div className="px-4 py-4 border-t border-slate-700/60 space-y-2">
        {!sseConnected && (
          <div className="flex items-center gap-1.5 text-orange-400 text-xs">
            <i className="fa-solid fa-plug-circle-xmark" />
            {t('sse_offline')}
          </div>
        )}
        {isBotOffline && (
          <div className="flex items-center gap-1.5 text-red-400 text-xs font-semibold">
            <i className="fa-solid fa-circle-xmark" />
            {t('bot_offline')}
          </div>
        )}
        {isStale && !isBotOffline && (
          <div className="flex items-center gap-1.5 text-yellow-400 text-xs">
            <i className="fa-solid fa-triangle-exclamation" />
            {t('stale_data')}
          </div>
        )}
        <p className={`text-xs leading-tight ${isStale ? 'text-yellow-500' : 'text-slate-600'}`}>
          <i className="fa-regular fa-clock mr-1" />
          {lastUpdated}
        </p>
        {secsUntilUpdate !== null && (
          <p className="text-slate-600 text-xs">
            <i className="fa-solid fa-arrows-rotate mr-1" />
            {t('refresh_in', { t: fmtCountdown(secsUntilUpdate) })}
          </p>
        )}
      </div>
    </aside>
  )
}
