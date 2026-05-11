import { useState, useEffect, useRef } from 'react'
import type { ScanStatus } from '../types'

export type EmpireRefreshState = 'idle' | 'running' | 'done'

export function useEmpireRefresh(onDone?: () => void) {
  const [state, setState] = useState<EmpireRefreshState>('idle')
  const [status, setStatus] = useState<ScanStatus | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const trigger = () => {
    setState('running')
    fetch('/api/data/refresh', { method: 'POST' }).catch(() => {})
  }

  useEffect(() => {
    if (state !== 'running') return
    intervalRef.current = setInterval(() => {
      fetch('/api/data/status')
        .then(r => r.json())
        .then((s: ScanStatus) => {
          setStatus(s)
          if (s.status === 'done' || s.status === 'idle') {
            setState('done')
            if (onDone) onDone()
            setTimeout(() => setState('idle'), 3000)
          }
        })
        .catch(() => {})
    }, 2000)
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [state])

  return { trigger, state, status }
}
