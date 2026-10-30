import { DispatchPanel } from './dispatch/DispatchPanel'
import { HistoryPanel } from './dispatch/HistoryPanel'

// Thin router (P11.5 split): the combat area used to live in one oversized component.
// It now switches on `view` and renders the matching focused panel. The farm tab was
// retired in P11.6 phase C — farm management lives in the unified Targets page now.
export function DispatchTab({ view = 'dispatch' }: { view?: 'dispatch' | 'historico' }) {
  if (view === 'historico') return <HistoryPanel />
  return <DispatchPanel />
}
