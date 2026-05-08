import type { ReactNode } from 'react'

export function Th({ children, align = 'text-center', className = '' }: { children: ReactNode; align?: string; className?: string }) {
  return <th className={`px-3 py-3 font-semibold ${align} ${className} whitespace-nowrap`}>{children}</th>
}

export function Td({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <td className={`px-3 py-2.5 text-sm ${className}`}>{children}</td>
}
