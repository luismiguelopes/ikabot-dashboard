import { useState } from 'react'
import { useT } from '../i18n'
import { PageHeader } from './ui/PageHeader'
import { DispatchTab } from './DispatchTab'

// P6.10: combat got its own sidebar page — dispatch/farm/history used to live as extra
// tabs inside MundoPage, mixing two unrelated concerns (world scan vs combat).
export function CombatPage() {
  const t = useT()
  const [tab, setTab] = useState<'dispatch' | 'farm' | 'historico'>('dispatch')
  const TABS = [
    { key: 'dispatch',  label: t('tab_dispatch'),  icon: 'fa-crosshairs'        },
    { key: 'farm',      label: t('tab_farm'),      icon: 'fa-seedling'          },
    { key: 'historico', label: t('tab_historico'), icon: 'fa-clock-rotate-left' },
  ] as const

  return (
    <div>
      <PageHeader icon="fa-crosshairs" title={t('combat_title')} />
      <div className="flex gap-1 bg-white border border-slate-200 rounded-xl p-1 shadow-sm w-fit mb-4">
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
      <DispatchTab view={tab} />
    </div>
  )
}
