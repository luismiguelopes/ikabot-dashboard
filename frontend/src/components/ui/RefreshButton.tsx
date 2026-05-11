import { useState } from 'react'
import { useT } from '../../i18n'

export function RefreshButton({ onRefresh }: { onRefresh: () => void }) {
  const t = useT()
  const [state, setState] = useState<'idle' | 'loading' | 'done'>('idle')

  const handleClick = () => {
    setState('loading')
    onRefresh()
    setTimeout(() => setState('done'), 1200)
    setTimeout(() => setState('idle'), 2800)
  }

  return (
    <button
      onClick={handleClick}
      disabled={state === 'loading'}
      className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg border transition-colors disabled:opacity-60 ${
        state === 'done'
          ? 'bg-emerald-50 text-emerald-600 border-emerald-200'
          : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
      }`}
    >
      <i className={`fa-solid fa-arrows-rotate ${state === 'loading' ? 'animate-spin' : ''}`} />
      {state === 'done' ? t('refresh_btn_done') : t('refresh_btn')}
    </button>
  )
}
