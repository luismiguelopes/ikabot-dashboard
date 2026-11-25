import { useT, useLang } from '../../i18n'
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
  toggleLang: () => void
  defaultTab: string
  onSaveDefaultTab: (tab: string) => void
}) {
  const t = useT()
  const lang = useLang()

  return (
    <div className="grid gap-4 max-w-lg">
      <Card>
        <div className="px-5 py-4">
          <CardTitle icon="fa-language">{t('settings_language')}</CardTitle>
          <div className="flex gap-2">
            {(['en', 'pt'] as const).map(l => (
              <button
                key={l}
                onClick={() => { if (l !== lang) toggleLang() }}
                aria-pressed={lang === l}
                className={`flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium border transition-colors ${
                  lang === l
                    ? 'bg-indigo-600 text-white border-indigo-600 shadow'
                    : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
                }`}
              >
                <i className="fa-solid fa-language" />
                {l === 'en' ? 'English' : 'Português'}
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

      <Card>
        <div className="px-5 py-4">
          <CardTitle icon="fa-code-branch">{t('settings_version')}</CardTitle>
          <div className="flex items-center justify-between gap-3 text-sm">
            <code className="px-2 py-1 rounded bg-slate-100 text-slate-700">{__APP_VERSION__}</code>
            <a
              href="https://github.com/luismiguelopes/ikabot-dashboard/releases"
              target="_blank"
              rel="noopener noreferrer"
              className="text-indigo-600 hover:underline"
            >
              {t('settings_version_releases')} <i className="fa-solid fa-arrow-up-right-from-square text-xs" />
            </a>
          </div>
        </div>
      </Card>
    </div>
  )
}
