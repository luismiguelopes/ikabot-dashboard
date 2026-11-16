import { useState, useEffect, useRef, useMemo } from 'react'
import { useT, useLang, getLocale } from '../i18n'
import { MATERIALS } from '../constants'
import { Card } from './ui/Card'
import { PageHeader } from './ui/PageHeader'
import Chart from 'chart.js/auto'
import type { ApiData } from '../types'

interface Props {
  data: ApiData
}

export function HistoryPage({ data }: Props) {
  const t    = useT()
  const lang = useLang()
  const cityNames = Object.keys(data.empireData).sort()

  const [history, setHistory]   = useState<any[] | null>(null)
  const [metric,  setMetric]    = useState('gold')
  const [city,    setCity]      = useState('')   // '' = empire-wide
  const [range,   setRange]     = useState<number>(7)   // days; 0 = everything stored
  const chartRef      = useRef<HTMLCanvasElement | null>(null)
  const chartInstance = useRef<Chart | null>(null)

  // Fetch history whenever city changes; reset metric when switching to per-city
  useEffect(() => {
    setHistory(null)
    // the most the server keeps (2160 points); the range is cut in the browser by time
    const url = city ? `/api/history?limit=2160&city=${encodeURIComponent(city)}` : '/api/history?limit=2160'
    // `current` guards against an older, slower answer landing after a newer one when the
    // city is switched quickly (it could also crash the chart: empire rows vs city rows).
    let current = true
    fetch(url)
      .then(r => r.json())
      .then(d => { if (current) setHistory(Array.isArray(d) ? d : []) })
      .catch(() => { if (current) setHistory([]) })
    if (city && metric !== 'resources' && metric !== 'wine_timer') setMetric('resources')
    if (!city && (metric === 'wine_timer')) setMetric('gold')
    return () => { current = false }
  }, [city])

  // The chart was never destroyed when leaving the page.
  useEffect(() => () => { chartInstance.current?.destroy(); chartInstance.current = null }, [])

  // The selected range, cut by time rather than by number of points.
  const shown = useMemo(() => {
    if (!history) return null
    if (!range) return history
    const cut = Date.now() / 1000 - range * 86400
    return history.filter(h => h.timestamp >= cut)
  }, [history, range])

  useEffect(() => {
    if (!shown || shown.length === 0 || !chartRef.current) return
    if (chartInstance.current) chartInstance.current.destroy()

    const locale = getLocale(lang)
    // A real time axis (P13.59): the old category axis gave every point the same width, so a
    // night with the bot offline took as much room as one hour. Points carry their time; a
    // silence longer than GAP breaks the line instead of drawing a slope across it.
    const GAP = 3 * 3600
    const series = (get: (h: any) => number | null) => {
      const pts: Array<{ x: number; y: number | null }> = []
      shown.forEach((h, i) => {
        const prev = shown[i - 1]
        if (prev && h.timestamp - prev.timestamp > GAP)
          pts.push({ x: (prev.timestamp + h.timestamp) / 2 * 1000, y: null })
        pts.push({ x: h.timestamp * 1000, y: get(h) })
      })
      return pts
    }

    const datasets: any[] = []
    const line = (label: string, color: string, get: (h: any) => number | null, extra: object = {}) =>
      datasets.push({ label, data: series(get), borderColor: color, backgroundColor: color + '22',
                      tension: 0.3, fill: false, spanGaps: false, pointRadius: shown.length > 200 ? 0 : 2, ...extra })
    const GOLD = '#facc15', INDIGO = '#6366f1', EMERALD = '#22c55e', SKY = '#38bdf8', PURPLE = '#a855f7'

    if (metric === 'gold') {
      line(t('chart_gold'), GOLD, h => h.gold.total, { fill: true })
      line(t('chart_gold_prod'), EMERALD, h => h.gold.production, { yAxisID: 'y2' })
    } else if (metric === 'resources') {
      // same colours as everywhere else in the app (wine was green and crystal red here)
      MATERIALS.forEach((m, i) => line(m[lang as 'pt' | 'en'], m.hex, h => h.resources.available[i] ?? 0))
    } else if (metric === 'wine_timer') {
      line(t('metric_wine_timer'), MATERIALS[1].hex,
           h => h.wineRunsOutIn != null && h.wineRunsOutIn >= 0 ? +(h.wineRunsOutIn / 3600).toFixed(1) : null,
           { fill: true })
    } else if (metric === 'ships') {
      line(t('chart_ships_avail'), SKY, h => h.ships.available)
      line(t('chart_ships_total'), INDIGO, h => h.ships.total)
    } else if (metric === 'citizens') {
      line(t('chart_citizens'), PURPLE, h => h.housing.citizens)
      line(t('chart_housing'), INDIGO, h => h.housing.space)
    }

    const spanDays = (shown[shown.length - 1].timestamp - shown[0].timestamp) / 86400
    const tickFmt: Intl.DateTimeFormatOptions = spanDays > 2
      ? { month: 'short', day: 'numeric' }
      : { weekday: 'short', hour: '2-digit', minute: '2-digit' }
    const scales: any = {
      y: { ticks: { color: '#94a3b8' }, grid: { color: '#e2e8f020' } },
      x: { type: 'linear',
           min: shown[0].timestamp * 1000, max: shown[shown.length - 1].timestamp * 1000,
           ticks: { color: '#94a3b8', maxTicksLimit: 10,
                    callback: (v: number) => new Date(v).toLocaleString(locale, tickFmt) },
           grid: { color: '#e2e8f020' } },
    }
    if (metric === 'gold') {
      scales.y2 = { position: 'right', ticks: { color: '#94a3b8' }, grid: { drawOnChartArea: false } }
    }
    if (metric === 'wine_timer') {
      scales.y.ticks = { ...scales.y.ticks, callback: (v: number) => `${v}h` }
    }

    chartInstance.current = new Chart(chartRef.current, {
      type: 'line',
      data: { datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'nearest', axis: 'x', intersect: false },
        plugins: {
          legend: { labels: { color: '#cbd5e1', font: { size: 12 } } },
          tooltip: { callbacks: {
            title: (items: any[]) => items.length
              ? new Date(items[0].parsed.x).toLocaleString(locale, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
              : '',
          } },
        },
        scales,
      },
    })
  }, [shown, metric, lang])

  const RANGES = [
    { days: 1, label: t('range_24h') }, { days: 7, label: t('range_7d') },
    { days: 30, label: t('range_30d') }, { days: 0, label: t('range_all') },
  ]

  // Metrics available differ by view mode
  const METRICS = city
    ? [
        { key: 'resources',   label: t('metric_resources')   },
        { key: 'wine_timer',  label: t('metric_wine_timer')  },
      ]
    : [
        { key: 'gold',      label: t('metric_gold')      },
        { key: 'resources', label: t('metric_resources') },
        { key: 'ships',     label: t('metric_ships')     },
        { key: 'citizens',  label: t('metric_citizens')  },
      ]

  return (
    <div>
      <PageHeader icon="fa-chart-line" title={t('history_title')}>
        <div className="flex items-center gap-2 flex-wrap">
          {/* City selector */}
          <div className="flex items-center gap-1.5">
            <i className="fa-solid fa-city text-slate-400 text-xs" />
            <select
              value={city}
              onChange={e => setCity(e.target.value)}
              className="text-xs border border-slate-200 rounded-lg px-2 py-1.5 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-300"
            >
              <option value="">{t('history_city_all')}</option>
              {cityNames.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>

          {/* Time range */}
          <div className="flex gap-1">
            {RANGES.map(r => (
              <button
                key={r.days}
                onClick={() => setRange(r.days)}
                className={`px-2.5 py-1.5 text-xs font-medium rounded-lg transition-colors ${range === r.days ? 'bg-slate-700 text-white' : 'bg-white border border-slate-200 text-slate-600 hover:bg-slate-50'}`}
              >
                {r.label}
              </button>
            ))}
          </div>

          {/* Metric pills */}
          <div className="flex gap-1">
            {METRICS.map(m => (
              <button
                key={m.key}
                onClick={() => setMetric(m.key)}
                className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${metric === m.key ? 'bg-indigo-600 text-white' : 'bg-white border border-slate-200 text-slate-600 hover:bg-slate-50'}`}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>
      </PageHeader>

      <Card>
        <div className="bg-slate-800 rounded-xl p-4" style={{ height: '360px' }}>
          {!shown ? (
            <div className="flex items-center justify-center h-full text-slate-400 text-sm">{t('loading_history')}</div>
          ) : shown.length === 0 ? (
            <div className="flex items-center justify-center h-full text-slate-400 text-sm">{t('no_history')}</div>
          ) : (
            <canvas ref={chartRef} />
          )}
        </div>
      </Card>

      {shown && shown.length > 0 && (
        <p className="text-xs text-slate-400 mt-2">
          {t('history_note', {
            n:    String(shown.length),
            from: new Date(shown[0].timestamp * 1000).toLocaleDateString(getLocale(lang)),
            to:   new Date(shown[shown.length - 1].timestamp * 1000).toLocaleDateString(getLocale(lang)),
          })}
        </p>
      )}
    </div>
  )
}
