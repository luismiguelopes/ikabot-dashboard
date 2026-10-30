import { DispatchPanel } from './dispatch/DispatchPanel'
import { FarmPanel } from './dispatch/FarmPanel'
import { HistoryPanel } from './dispatch/HistoryPanel'

// Thin router (P11.5 split): the combat area used to live in one oversized component.
// It now switches on `view` and renders the matching focused panel; the public prop
// contract is unchanged so CombatPage needs no edits.
export function DispatchTab({ view = 'dispatch' }: { view?: 'dispatch' | 'farm' | 'historico' }) {
  if (view === 'farm')      return <FarmPanel />
  if (view === 'historico') return <HistoryPanel />
  return <DispatchPanel />
}
