// The on/off switch used across the settings cards (P13.53). It was written out by hand nine
// times, none with a role or a label for screen readers.
export function Toggle({ on, onChange, label, size = 'md', onClass = 'bg-indigo-600', offClass = 'bg-slate-300', disabled = false }: {
  on: boolean
  onChange: (next: boolean) => void
  /** Accessible name — the visible text next to the switch. */
  label: string
  size?: 'sm' | 'md'
  /** Track colour when on / off (e.g. the wine buyer: green while safe, red while live). */
  onClass?: string
  offClass?: string
  disabled?: boolean
}) {
  const track = size === 'sm' ? 'h-5 w-9' : 'h-6 w-11'
  const knobOn = size === 'sm' ? 'translate-x-4' : 'translate-x-6'
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className={`relative inline-flex ${track} shrink-0 items-center rounded-full transition-colors disabled:opacity-40 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 ${on ? onClass : offClass}`}
    >
      <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${on ? knobOn : 'translate-x-1'}`} />
    </button>
  )
}
