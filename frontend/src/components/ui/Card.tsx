import type { ReactNode } from 'react'

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`bg-white rounded-xl border border-slate-200 shadow-sm ${className}`}>
      {children}
    </div>
  )
}

export function CardHeader({ icon, title }: { icon: string; title: string }) {
  return (
    <div className="px-5 py-4 border-b border-slate-100 flex items-center gap-2">
      <i className={`fa-solid ${icon} text-indigo-400 text-sm`} />
      <h2 className="text-sm font-semibold text-slate-700">{title}</h2>
    </div>
  )
}
