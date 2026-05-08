import { fmt } from '../utils'

export function StorageBar({ value, capacity }: { value: number; capacity: number }) {
  if (!capacity) return <span className="font-mono text-slate-600">{fmt(value)}</span>
  const pct = Math.min(100, Math.round((value / capacity) * 100))
  const color = pct >= 95 ? 'bg-red-500' : pct >= 80 ? 'bg-yellow-400' : 'bg-indigo-400'
  return (
    <div className="flex flex-col items-center gap-0.5 min-w-[64px]">
      <span className="font-mono text-slate-700 text-xs leading-none">{fmt(value)}</span>
      <div className="w-full h-1.5 bg-slate-200 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-slate-400 text-[10px] leading-none">{pct}%</span>
    </div>
  )
}
