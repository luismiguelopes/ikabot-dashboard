import { useState, useEffect, useRef } from 'react'
import { useT, useLang, getLocale } from '../i18n'
import { MATERIALS } from '../constants'
import { Card } from './ui/Card'
import { PageHeader } from './ui/PageHeader'
import Chart from 'chart.js/auto'

export function HistoryPage() {
  const t = useT()
  const lang = useLang()
  const [history, setHistory] = useState<any[] | null>(null)
  const [metric, setMetric]   = useState('gold')
  const chartRef = useRef<HTMLCanvasElement | null>(null)
  const chartInstance = useRef<Chart | null>(null)

  useEffect(() => {
    fetch('/api/history')
      .then(r => r.json())
      .then(setHistory)
      .catch(() => setHistory([]))
  }, [])

  useEffect(() => {
    if (!history || history.length === 0 || !chartRef.current) return
    if (chartInstance.current) { chartInstance.current.destroy() }

    const labels = history.map(h => {
      const d = new Date(h.timestamp * 1000)
      return d.toLocaleString(getLocale(lang), { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
    })

    const datasets: any[] = []
    const colors = ['#6366f1','#22c55e','#f59e0b','#ef4444','#06b6d4','#a855f7']

    if (metric === 'gold') {
      datasets.push({ label: t('chart_gold'), data: history.map(h => h.gold.total), borderColor: colors[0], backgroundColor: colors[0]+'22', tension: 0.3, fill: true })
      datasets.push({ label: t('chart_gold_prod'), data: history.map(h => h.gold.production), borderColor: colors[1], backgroundColor: colors[1]+'22', tension: 0.3, fill: false, yAxisID: 'y2' })
    } else if (metric === 'resources') {
      MATERIALS.forEach((m, i) => {
        datasets.push({ label: m[lang as 'pt' | 'en'], data: history.map(h => h.resources.available[i]), borderColor: colors[i % colors.length], tension: 0.3, fill: false })
      })
    } else if (metric === 'ships') {
      datasets.push({ label: t('chart_ships_avail'), data: history.map(h => h.ships.available), borderColor: colors[0], tension: 0.3, fill: false })
      datasets.push({ label: t('chart_ships_total'), data: history.map(h => h.ships.total),     borderColor: colors[1], tension: 0.3, fill: false })
    } else if (metric === 'citizens') {
      datasets.push({ label: t('chart_citizens'), data: history.map(h => h.housing.citizens), borderColor: colors[2], tension: 0.3, fill: false })
      datasets.push({ label: t('chart_housing'),  data: history.map(h => h.housing.space),    borderColor: colors[0], tension: 0.3, fill: false })
    }

    const scales: any = {
      y: { ticks: { color: '#94a3b8' }, grid: { color: '#e2e8f020' } },
      x: { ticks: { color: '#94a3b8', maxTicksLimit: 12 }, grid: { color: '#e2e8f020' } },
    }
    if (metric === 'gold') {
      scales.y2 = { position: 'right', ticks: { color: '#94a3b8' }, grid: { drawOnChartArea: false } }
    }

    chartInstance.current = new Chart(chartRef.current, {
      type: 'line',
      data: { labels, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#cbd5e1', font: { size: 12 } } } },
        scales,
      },
    })
  }, [history, metric, lang])

  const METRICS = [
    { key: 'gold',      label: t('metric_gold')      },
    { key: 'resources', label: t('metric_resources') },
    { key: 'ships',     label: t('metric_ships')     },
    { key: 'citizens',  label: t('metric_citizens')  },
  ]

  return (
    <div>
      <PageHeader icon="fa-chart-line" title={t('history_title')}>
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
      </PageHeader>

      <Card>
        <div className="bg-slate-800 rounded-xl p-4" style={{ height: '360px' }}>
          {!history ? (
            <div className="flex items-center justify-center h-full text-slate-400 text-sm">{t('loading_history')}</div>
          ) : history.length === 0 ? (
            <div className="flex items-center justify-center h-full text-slate-400 text-sm">
              {t('no_history')}
            </div>
          ) : (
            <canvas ref={chartRef} />
          )}
        </div>
      </Card>

      {history && history.length > 0 && (
        <p className="text-xs text-slate-400 mt-2">
          {t('history_note', {
            n: String(history.length),
            from: new Date(history[0].timestamp * 1000).toLocaleDateString(getLocale(lang)),
            to: new Date(history[history.length-1].timestamp * 1000).toLocaleDateString(getLocale(lang)),
          })}
        </p>
      )}
    </div>
  )
}
