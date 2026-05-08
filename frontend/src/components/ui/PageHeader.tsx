import type { ReactNode } from 'react'

export function PageHeader({ icon, title, children }: { icon: string; title: string; children?: ReactNode }) {
  return (
    <div className="flex items-center justify-between mb-6">
      <h1 className="text-xl font-bold text-slate-800 flex items-center gap-2">
        <i className={`fa-solid ${icon} text-indigo-500`} />
        {title}
      </h1>
      {children}
    </div>
  )
}
