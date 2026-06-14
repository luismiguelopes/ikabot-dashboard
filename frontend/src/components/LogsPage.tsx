import { useState, useEffect, useRef, useCallback } from 'react'
import { useT } from '../i18n'
import { Card } from './ui/Card'
import { PageHeader } from './ui/PageHeader'
import { RefreshButton } from './ui/RefreshButton'

const LEVEL_COLOR: Record<string, string> = {
  ERROR:   'text-red-400',
  WARNING: 'text-yellow-400',
  INFO:    'text-slate-300',
  DEBUG:   'text-slate-500',
}

function lineColor(line: string): string {
  for (const [lvl, cls] of Object.entries(LEVEL_COLOR)) {
    if (line.includes(` ${lvl} `)) return cls
  }
  return 'text-slate-300'
}

export function LogsPage() {
  const t = useT()
  const [lines, setLines]           = useState<string[]>([])
  const [note, setNote]             = useState<string | null>(null)
  const [count, setCount]           = useState(200)
  const [autoScroll, setAutoScroll] = useState(true)
  const boxRef = useRef<HTMLDivElement>(null)

  const fetchLogs = useCallback(() => {
    fetch(`/api/logs?lines=${count}`)
      .then(r => r.json())
      .then((d: { lines?: string[]; note?: string; error?: string }) => {
        setLines(d.lines ?? [])
        setNote(d.note ?? d.error ?? null)
      })
      .catch(() => {})
  }, [count])

  useEffect(() => { fetchLogs() }, [fetchLogs])

  // Poll every 5s
  useEffect(() => {
    const id = setInterval(fetchLogs, 5000)
    return () => clearInterval(id)
  }, [fetchLogs])

  // Auto-scroll to bottom when new lines arrive
  useEffect(() => {
    if (autoScroll && boxRef.current) {
      boxRef.current.scrollTop = boxRef.current.scrollHeight
    }
  }, [lines, autoScroll])

  return (
    <div>
      <PageHeader icon="fa-terminal" title={t('logs_title')}>
        <div className="flex items-center gap-3 flex-wrap">
          <label className="flex items-center gap-1.5 text-xs text-slate-500">
            <input type="checkbox" checked={autoScroll} onChange={e => setAutoScroll(e.target.checked)} />
            {t('logs_autoscroll')}
          </label>
          <select
            value={count}
            onChange={e => setCount(Number(e.target.value))}
            className="border border-slate-200 rounded-lg px-2 py-1.5 text-xs bg-white"
          >
            {[100, 200, 500, 1000].map(n => (
              <option key={n} value={n}>{n} {t('logs_lines')}</option>
            ))}
          </select>
          <RefreshButton onRefresh={fetchLogs} />
        </div>
      </PageHeader>

      <Card>
        <div
          ref={boxRef}
          className="bg-slate-900 rounded-lg p-4 font-mono text-xs leading-relaxed overflow-auto"
          style={{ maxHeight: '70vh' }}
        >
          {lines.length === 0 ? (
            <p className="text-slate-500">{note || t('logs_empty')}</p>
          ) : (
            lines.map((line, i) => (
              <div key={i} className={`whitespace-pre-wrap break-all ${lineColor(line)}`}>{line}</div>
            ))
          )}
        </div>
      </Card>
    </div>
  )
}
