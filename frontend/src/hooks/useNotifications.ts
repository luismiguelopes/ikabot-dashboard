import { useEffect, useRef } from 'react'
import { fmtDuration } from '../utils'
import type { ApiData, AlertThresholds } from '../types'

export const NOTIF_STORAGE_KEY = 'ikabot_notif_browser'

export function loadBrowserNotifEnabled(): boolean {
  try { return localStorage.getItem(NOTIF_STORAGE_KEY) === 'true' } catch { return false }
}

export function saveBrowserNotifEnabled(v: boolean) {
  try { localStorage.setItem(NOTIF_STORAGE_KEY, String(v)) } catch {}
}

export function useNotifications(data: ApiData | null, thresholds: AlertThresholds, enabled: boolean) {
  const sentRef = useRef<Set<string>>(new Set())

  useEffect(() => {
    if (!enabled || !data || !('Notification' in window) || Notification.permission !== 'granted') return

    const now = Math.floor(Date.now() / 1000)
    const sent = sentRef.current

    // Wine critical per city
    Object.entries(data.resourcesData).forEach(([city, d]) => {
      const wine = d.wineRunsOutIn
      const critical = wine !== -1 && wine !== undefined && wine >= 0 && wine < thresholds.wineCritical * 3600
      const key = `wine_${city}`
      if (critical && !sent.has(key)) {
        sent.add(key)
        new Notification(`Vinho crítico — ${city}`, { body: `Acaba em ${fmtDuration(wine)}` })
      } else if (!critical) {
        sent.delete(key)
      }
    })

    // Bot offline
    const offline = !!(data.lastAlive && now - data.lastAlive > 90 * 60)
    if (offline && !sent.has('bot_offline')) {
      sent.add('bot_offline')
      new Notification('Bot offline', { body: 'O bot não responde há mais de 90 min.' })
    } else if (!offline) {
      sent.delete('bot_offline')
    }

  }, [data, thresholds, enabled])
}
