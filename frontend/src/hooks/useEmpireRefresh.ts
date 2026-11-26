import { useState, useEffect, useRef, useCallback } from 'react'
import type { ScanStatus } from '../types'

export type EmpireRefreshState = 'idle' | 'running' | 'done'

// The bot picks up the refresh request between steps, which can take a few minutes when it is
// busy (seen: 2.5 min), so the status file still holds the previous run's result for a while.
// Past this, stop waiting for the new run (e.g. the bot is offline).
const MAX_WAIT_FOR_START_MS = 5 * 60_000

export function useEmpireRefresh(onDone?: () => void) {
  const [state, setState] = useState<EmpireRefreshState>('idle')
  const [status, setStatus] = useState<ScanStatus | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Latest callback, read by the polling interval. Keeping it out of the effect's dependencies
  // means a caller passing an inline callback cannot restart the interval on every render.
  const onDoneRef = useRef(onDone)
  useEffect(() => { onDoneRef.current = onDone }, [onDone])
  // The run started by the last trigger: a terminal status only counts once this run has been
  // seen running (or the bot never started it), and `finished` stops late responses from
  // calling onDone twice.
  const runRef = useRef({ startedAt: 0, sawRunning: false, finished: true })

  useEffect(() => {
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
    }
  }, [])

  const trigger = useCallback(() => {
    runRef.current = { startedAt: Date.now(), sawRunning: false, finished: false }
    setStatus(null)
    setState('running')
    fetch('/api/data/refresh', { method: 'POST' }).catch(() => {})
  }, [])

  useEffect(() => {
    if (state !== 'running') return
    intervalRef.current = setInterval(() => {
      fetch('/api/data/status')
        .then(r => r.json())
        .then((s: ScanStatus) => {
          const run = runRef.current
          if (run.finished) return
          if (s.status === 'running') run.sawRunning = true
          const terminal = s.status === 'done' || s.status === 'idle' || s.status === 'error'
          const gaveUp = Date.now() - run.startedAt > MAX_WAIT_FOR_START_MS
          // until the new run shows up, a terminal status is the previous run's
          if (run.sawRunning || gaveUp) setStatus(s)
          if (terminal && (run.sawRunning || gaveUp)) {
            run.finished = true
            setState('done')
            onDoneRef.current?.()
            timeoutRef.current = setTimeout(() => setState('idle'), 3000)
          }
        })
        .catch(() => {})
    }, 2000)
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [state])

  return { trigger, state, status }
}
