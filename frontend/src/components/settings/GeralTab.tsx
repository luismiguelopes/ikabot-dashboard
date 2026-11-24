import { useT, useUiLang, LANGS } from '../../i18n'
import { Card } from '../ui/Card'
import { CardTitle, SELECT_CLS } from './shared'

const NAV_OPTIONS = [
  'home', 'cities', 'buildings', 'movements', 'alerts',
  'history', 'calc', 'construction', 'combate', 'mundo',
] as const
type NavKey = typeof NAV_OPTIONS[number]
const NAV_LABEL_KEYS: Record<NavKey, string> = {
  home: 'nav_home', cities: 'nav_cities', buildings: 'nav_buildings',
  movements: 'nav_movements', alerts: 'nav_alerts', history: 'nav_history',
  calc: 'nav_calculators', construction: 'nav_construction',
  combate: 'nav_combat', mundo: 'nav_world',
}

export function GeralTab({ toggleLang, defaultTab, onSaveDefaultTab }: {
  toggleLang: (target?: string) => void
  defaultTab: string
  onSaveDefaultTab: (tab: string) => void
}) {
  const t = useT()
  const lang = useUiLang()

  return (
    <div className="grid gap-4 max-w-lg">
      <Card>
        <div className="px-5 py-4">
          <CardTitle icon="fa-language">{t('settings_language')}</CardTitle>
          <div className="flex gap-2">
            {LANGS.map(l => (
              <button
                key={l}
                onClick={() => { if (l !== lang) toggleLang(l) }}
                aria-pressed={lang === l}
                className={`flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium border transition-colors ${
                  lang === l
                    ? 'bg-indigo-600 text-white border-indigo-600 shadow'
                    : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
                }`}
              >
                <i className="fa-solid fa-language" />
                {l === 'en' ? 'English' : l === 'pt' ? 'Português (PT)' : 'Português (BR)'}
              </button>
            ))}
          </div>
        </div>
      </Card>

      <Card>
        <div className="px-5 py-4">
          <CardTitle icon="fa-house">{t('settings_default_tab')}</CardTitle>
          <select
            value={defaultTab}
            onChange={e => onSaveDefaultTab(e.target.value)}
            aria-label={t('settings_default_tab')}
            className={SELECT_CLS}
          >
            {NAV_OPTIONS.map(key => (
              <option key={key} value={key}>{t(NAV_LABEL_KEYS[key])}</option>
            ))}
          </select>
          <p className="mt-2 text-xs text-slate-400">{t('settings_default_tab_hint')}</p>
        </div>
      </Card>
    </div>
  )
}
