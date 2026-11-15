import { pushToast } from './components/ui/Toast'

// Default error text for failed user actions. Kept bilingual + inline (rather than in
// i18n) so apiAction can run outside React without threading `t()` through every caller.
let _lang: 'pt' | 'en' = 'pt'
export function setApiLang(l: 'pt' | 'en') { _lang = l }

const NETWORK = { pt: 'Erro de rede', en: 'Network error' }
const FAILED = { pt: 'O pedido falhou', en: 'Request failed' }

export interface ApiOpts {
  errorMsg?: string      // overrides the default toast text on failure
  successMsg?: string    // when set, a success toast is shown on a 2xx response
  silent?: boolean       // suppress the failure toast (e.g. background polling)
}

// Fire-and-check helper for user-initiated actions (button clicks that POST). On a
// network error or non-2xx response it surfaces a toast — the server's `error` field
// when present, otherwise a generic message — instead of failing silently. Returns the
// parsed JSON body on success, or null on any failure, so callers can branch on null.
export async function apiAction(
  url: string,
  init?: RequestInit,
  opts: ApiOpts = {},
): Promise<Record<string, unknown> | null> {
  try {
    const res = await fetch(url, init)
    let body: Record<string, unknown> | null = null
    try { body = await res.json() } catch { /* no/empty body */ }
    if (!res.ok) {
      if (!opts.silent)
        pushToast(opts.errorMsg || (body?.error as string) || FAILED[_lang], 'error')
      return null
    }
    if (opts.successMsg) pushToast(opts.successMsg, 'ok')
    return body ?? {}
  } catch {
    if (!opts.silent) pushToast(opts.errorMsg || NETWORK[_lang], 'error')
    return null
  }
}


// ── Expired session ───────────────────────────────────────────────────────────
// The app has ~100 plain fetch() calls and none of them handled a 401: when the session
// expired mid-use every page filled with failing requests (or crashed on the error body).
// One interceptor on fetch itself covers them all: any API call answered 401 announces it,
// and the AuthGate puts the login screen back.
export const AUTH_EXPIRED_EVENT = 'ikabot:auth-expired'

let _fetchPatched = false
export function installAuthInterceptor() {
  if (_fetchPatched) return
  _fetchPatched = true
  const original = window.fetch.bind(window)
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const res = await original(input, init)
    if (res.status === 401) {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.pathname : input.url
      if (url.includes('/api/') && !url.includes('/api/login') && !url.includes('/api/auth-status'))
        window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT))
    }
    return res
  }
}


// ── Polling that rests while the tab is hidden ───────────────────────────────
// Every poll in the app kept firing with the tab in the background (a dozen requests every
// 15–60s for nobody). Drop-in for setInterval: same arguments, same id for clearInterval; the
// callback is skipped while the document is hidden and runs once when it becomes visible again.
export function pollInterval(fn: () => void, ms: number): ReturnType<typeof setInterval> {
  const id = setInterval(() => { if (!document.hidden) fn() }, ms)
  const onVisible = () => { if (!document.hidden) fn() }
  document.addEventListener('visibilitychange', onVisible)
  _pollCleanup.set(id, onVisible)
  return id
}
const _pollCleanup = new Map<ReturnType<typeof setInterval>, () => void>()
export function clearPoll(id: ReturnType<typeof setInterval>) {
  clearInterval(id)
  const h = _pollCleanup.get(id)
  if (h) { document.removeEventListener('visibilitychange', h); _pollCleanup.delete(id) }
}
