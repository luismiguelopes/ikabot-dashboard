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
