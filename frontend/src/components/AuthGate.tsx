import { useState, useEffect, type ReactNode } from 'react'

type Phase = 'loading' | 'need' | 'ok'

/** "Terminar sessão" — renders only when the dashboard has auth enabled. */
export function LogoutButton() {
  const [enabled, setEnabled] = useState(false)
  useEffect(() => {
    fetch('/api/auth-status').then(r => r.json()).then(d => setEnabled(!!d.enabled)).catch(() => {})
  }, [])
  if (!enabled) return null
  async function logout() {
    try { await fetch('/api/logout', { method: 'POST' }) } catch { /* ignore */ }
    location.reload()
  }
  return (
    <button
      onClick={logout}
      className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium bg-white text-slate-600 border border-slate-200 hover:bg-slate-50 hover:text-red-600 transition-colors"
    >
      <i className="fa-solid fa-arrow-right-from-bracket" /> Terminar sessão
    </button>
  )
}

/**
 * Gates the whole app behind a password when the dashboard has DASHBOARD_PASSWORD set
 * (server reports it via /api/auth-status). With auth disabled it renders through.
 * Only the API is protected server-side; this is the matching login UI.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<Phase>('loading')
  const [pw, setPw] = useState('')
  const [err, setErr] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    fetch('/api/auth-status')
      .then(r => r.json())
      .then(d => setPhase(!d.enabled || d.authed ? 'ok' : 'need'))
      .catch(() => setPhase('ok'))
  }, [])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setErr(false)
    try {
      const r = await fetch('/api/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: pw }),
      })
      if (r.ok) setPhase('ok')
      else { setErr(true); setPw('') }
    } catch { setErr(true) }
    finally { setBusy(false) }
  }

  if (phase === 'ok') return <>{children}</>

  if (phase === 'loading') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <i className="fa-solid fa-spinner fa-spin text-2xl text-slate-300" />
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-100 px-4">
      <form onSubmit={submit}
        className="w-full max-w-sm bg-white border border-slate-200 rounded-2xl shadow-xl p-7 space-y-4">
        <div className="text-center">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-indigo-600 text-white text-xl mb-3">
            <i className="fa-solid fa-shield-halved" />
          </div>
          <h1 className="text-lg font-bold text-slate-800">Painel ikabot</h1>
          <p className="text-sm text-slate-500 mt-0.5">Introduz a palavra-passe para entrar.</p>
        </div>
        <div>
          <input
            id="dashboard-password"
            type="password"
            autoFocus
            autoComplete="current-password"
            value={pw}
            onChange={e => { setPw(e.target.value); setErr(false) }}
            placeholder="Palavra-passe"
            className={`w-full border rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 ${
              err ? 'border-red-400 focus:ring-red-300' : 'border-slate-200 focus:ring-indigo-400'
            }`}
          />
          {err && (
            <div className="mt-2 text-xs text-red-600 flex items-center gap-1.5">
              <i className="fa-solid fa-circle-exclamation" /> Palavra-passe errada.
            </div>
          )}
        </div>
        <button
          type="submit"
          disabled={busy || !pw}
          className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40 transition-colors"
        >
          <i className={`fa-solid ${busy ? 'fa-spinner fa-spin' : 'fa-arrow-right-to-bracket'}`} />
          Entrar
        </button>
      </form>
    </div>
  )
}
