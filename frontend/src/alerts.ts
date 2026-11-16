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
      | 'incoming' | 'offline' | 'subsystem' | 'transport_retry' | 'transport_dropped'
  city?: string
  seconds?: number        // wine: runway left
  material?: (typeof MATERIALS)[number]
  pct?: number            // storage: how full
  value?: number          // gold production / total ships / incoming count / failures / retries
  at?: number             // incoming: first arrival; transport: next try or when it gave up
  name?: string           // subsystem
  error?: string          // subsystem / transport: what went wrong
  origin?: string         // transport
  dest?: string
}

// What the empire data does not carry (P13.58): fetched by App and fed in here, so the Alerts
// page and the sidebar counter still share one definition.
export interface ExtraAlertSources {
  incoming?: { count: number; eta: number | null }
  silentFor?: number | null          // seconds since the bot's last heartbeat (null = unknown)
  offlineAfterSecs?: number
  subsystems?: Array<{ name: string; failures: number; error: string }>
  transportRetrying?: Array<{ origin: string; dest: string; retries: number; error: string; nextTry?: number | null }>
  transportDropped?: Array<{ ts: number; origin: string; dest: string; retries?: number; error: string }>
}

/** Wine level of one city against the configured thresholds, or null when it is fine. */
export function wineLevel(runsOut: number | undefined | null, th: AlertThresholds): 'critical' | 'warning' | null {
  if (runsOut === -1 || runsOut === undefined || runsOut === null) return null
  if (runsOut < th.wineCritical * 3600) return 'critical'
  if (runsOut < th.wineWarning * 3600) return 'warning'
  return null
}

export function computeAlerts(data: ApiData, th: AlertThresholds, extra: ExtraAlertSources = {}): EmpireAlert[] {
  const out: EmpireAlert[] = []
  // the bot itself first: nothing else on this list gets handled while it is down
  if (extra.silentFor != null && extra.silentFor > (extra.offlineAfterSecs ?? 1800))
    out.push({ level: 'critical', kind: 'offline', seconds: extra.silentFor })
  if (extra.incoming && extra.incoming.count > 0)
    out.push({ level: 'critical', kind: 'incoming', value: extra.incoming.count, at: extra.incoming.eta ?? undefined })
  for (const s of extra.subsystems ?? [])
    out.push({ level: s.failures >= 3 ? 'critical' : 'warning', kind: 'subsystem', name: s.name, value: s.failures, error: s.error })
  for (const tr of extra.transportDropped ?? [])
    out.push({ level: 'warning', kind: 'transport_dropped', origin: tr.origin, dest: tr.dest, error: tr.error, at: tr.ts, value: tr.retries })
  for (const tr of extra.transportRetrying ?? [])
    out.push({ level: 'info', kind: 'transport_retry', origin: tr.origin, dest: tr.dest, error: tr.error, value: tr.retries, at: tr.nextTry ?? undefined })
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
