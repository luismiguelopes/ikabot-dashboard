import { MATERIALS } from './constants'
import type { ApiData, AlertThresholds } from './types'

// One definition of "what is an alert" (P13.58). The Alerts page and the sidebar counter each
// had their own copy and differed (the page also counted idle ships; the counter ignored the
// critical wine level), and the Cities page coloured wine by fixed 4h/12h instead of the
// thresholds set in Settings.
export type AlertLevel = 'critical' | 'warning' | 'info'
export interface EmpireAlert {
  level: AlertLevel
  kind: 'wine' | 'storage' | 'gold' | 'ships'
  city?: string
  seconds?: number        // wine: runway left
  material?: (typeof MATERIALS)[number]
  pct?: number            // storage: how full
  value?: number          // gold production / total ships
}

/** Wine level of one city against the configured thresholds, or null when it is fine. */
export function wineLevel(runsOut: number | undefined | null, th: AlertThresholds): 'critical' | 'warning' | null {
  if (runsOut === -1 || runsOut === undefined || runsOut === null) return null
  if (runsOut < th.wineCritical * 3600) return 'critical'
  if (runsOut < th.wineWarning * 3600) return 'warning'
  return null
}

export function computeAlerts(data: ApiData, th: AlertThresholds): EmpireAlert[] {
  const out: EmpireAlert[] = []
  const { resourcesData, statusSummary: s } = data
  for (const [city, d] of Object.entries(resourcesData)) {
    const level = wineLevel(d.wineRunsOutIn, th)
    if (level) out.push({ level, kind: 'wine', city, seconds: d.wineRunsOutIn })
  }
  for (const [city, d] of Object.entries(resourcesData)) {
    const cap = d.storageCapacity
    if (!cap) continue
    for (const m of MATERIALS) {
      const val = d[m.en as keyof typeof d] as number
      if (val != null && val / cap >= th.storageWarning / 100)
        out.push({ level: 'warning', kind: 'storage', city, material: m, pct: Math.round(val / cap * 100) })
    }
  }
  if (s.gold.production < 0) out.push({ level: 'critical', kind: 'gold', value: s.gold.production })
  if (s.ships.available === 0 && s.ships.total > 0) out.push({ level: 'info', kind: 'ships', value: s.ships.total })
  const order: Record<AlertLevel, number> = { critical: 0, warning: 1, info: 2 }
  return out.sort((a, b) => order[a.level] - order[b.level])
}
