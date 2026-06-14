import { getLocale } from './i18n'

export function fmt(n: number | string | null | undefined): string {
  const num = Number(n)
  if (n === null || n === undefined || isNaN(num)) return '—'
  return Math.round(num).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
}

export function fmtTime(hours: number | null): string {
  if (hours === null || !isFinite(hours) || hours <= 0) return '—'
  if (hours < 1/60) return '<1m'
  if (hours < 1)    return `${Math.round(hours * 60)}m`
  if (hours < 24)   return `${Math.floor(hours)}h ${Math.round((hours % 1) * 60)}m`
  const days = Math.floor(hours / 24)
  const h    = Math.round(hours % 24)
  if (days < 365) return `${days}d ${h}h`
  const years = Math.floor(days / 365)
  return `${years}y ${Math.floor(days % 365)}d`
}

export function fmtDuration(seconds: number): string {
  if (seconds < 0 || seconds === -1) return '∞'
  if (seconds === 0) return '0s'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

export function fmtCountdown(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export function fmtArrival(ts: number | null | undefined, lang = 'en'): string {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString(getLocale(lang), { hour: '2-digit', minute: '2-digit' })
}

export function fmtScore(s: string | undefined | null, lang = 'en'): string {
  const n = parseInt(String(s || '').replace(/[,.\s ]/g, ''), 10) || 0
  if (!n) return '—'
  return n.toLocaleString(getLocale(lang))
}

export function fmtHours(hours: number, t?: (key: string) => string): string {
  if (!isFinite(hours) || hours > 1e9) return '∞'
  if (hours <= 0) return t ? t('available_now') : 'Available now!'
  const totalMins = Math.round(hours * 60)
  const d = Math.floor(totalMins / 1440)
  const h = Math.floor((totalMins % 1440) / 60)
  const m = totalMins % 60
  if (d > 0) return `${d}d ${h}h ${m}m`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

export function fmtTs(ts: number | undefined | null, lang = 'en'): string {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString(getLocale(lang), {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

// Forecast wall-clock: time only when it lands today, day+month+time otherwise.
export function fmtForecast(ts: number | null | undefined, lang = 'en'): string {
  if (!ts || !isFinite(ts) || ts > 1e12) return '∞'
  const d = new Date(ts * 1000)
  const now = new Date()
  const sameDay = d.getDate() === now.getDate() && d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear()
  return d.toLocaleString(getLocale(lang), sameDay
    ? { hour: '2-digit', minute: '2-digit' }
    : { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

export function calcUpgradeTime(
  needed: number[],
  available: number[],
  production: number[],
  gold: number,
  goldPrice: number
) {
  const gp      = goldPrice || 15
  const missing = needed.map((n, i) => Math.max(0, n - (available[i] || 0)))

  const totalNeeded     = needed.reduce((s, n) => s + n, 0)
  const totalAvailable  = available.reduce((s, a) => s + (a || 0), 0)
  const totalMissing    = Math.max(0, totalNeeded - totalAvailable)
  const totalProduction = production.reduce((s, p) => s + (p || 0), 0)
  const goldNeededAll   = totalMissing * gp
  const canBuyAll       = gold >= goldNeededAll

  const timeNoGold = totalProduction > 0
    ? totalMissing / totalProduction
    : (totalMissing > 0 ? Infinity : 0)

  let timeWithGold = canBuyAll ? 0 : timeNoGold
  if (!canBuyAll && gold > 0) {
    const goldBuysUnits = gold / gp
    const stillMissing  = Math.max(0, totalMissing - goldBuysUnits)
    timeWithGold = totalProduction > 0
      ? stillMissing / totalProduction
      : (stillMissing > 0 ? Infinity : 0)
  }

  return { missing, totalMissing, totalProduction, timeNoGold, timeWithGold, goldNeededAll, canBuyAll }
}

export function exportCsv(filename: string, rows: (string | number)[][]): void {
  const csv = rows.map(r => r.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(',')).join('\n')
  const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
}

export function loadThresholds() {
  try {
    const stored = localStorage.getItem('ikabot_alert_thresholds')
    return stored ? { wineWarning: 8, wineCritical: 2, storageWarning: 95, ...JSON.parse(stored) } : { wineWarning: 8, wineCritical: 2, storageWarning: 95 }
  } catch { return { wineWarning: 8, wineCritical: 2, storageWarning: 95 } }
}
