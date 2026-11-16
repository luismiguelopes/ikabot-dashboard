import { useEffect, useRef } from 'react'
import { LIVE_EVENT, pollInterval, clearPoll } from '../api'
import type { LiveTopic } from '../api'

interface Opts {
  /** Slow poll kept as a safety net (live updates can drop); 0 = none. Default 5 min. */
  fallbackMs?: number
  /** At most one refresh per this many ms; changes in between fold into one. Default 5 s. */
  minGapMs?: number
}

// Re-run `fn` when the bot changes one of `topics` (P13.40). Changes arrive in bursts (a farm
// step writes several rows), so they are folded into one call at most every `minGapMs`; while
// the tab is hidden nothing runs and one call is made when it shows again.
export function useLiveRefresh(fn: () => void, topics: LiveTopic[], { fallbackMs = 300000, minGapMs = 5000 }: Opts = {}) {
  const fnRef = useRef(fn)
  fnRef.current = fn
  const key = topics.join(',')

  useEffect(() => {
    const wanted = key.split(',') as LiveTopic[]
    let last = 0
    let timer: ReturnType<typeof setTimeout> | null = null
    let missed = false
    const run = () => {
      timer = null
      if (document.hidden) { missed = true; return }
      last = Date.now()
      fnRef.current()
    }
    const schedule = () => {
      if (timer) return
      timer = setTimeout(run, Math.max(0, last + minGapMs - Date.now()))
    }
    const onLive = (e: Event) => {
      const got = (e as CustomEvent<LiveTopic[]>).detail || []
      if (got.some(t => wanted.includes(t))) schedule()
    }
    // with a fallback poll, pollInterval already refreshes once when the tab shows again
    const onVisible = () => { if (!document.hidden && missed) { missed = false; if (!poll) schedule() } }
    window.addEventListener(LIVE_EVENT, onLive)
    document.addEventListener('visibilitychange', onVisible)
    const poll = fallbackMs ? pollInterval(() => { last = Date.now(); fnRef.current() }, fallbackMs) : null
    return () => {
      window.removeEventListener(LIVE_EVENT, onLive)
      document.removeEventListener('visibilitychange', onVisible)
      if (timer) clearTimeout(timer)
      if (poll) clearPoll(poll)
    }
  }, [key, fallbackMs, minGapMs])
}
