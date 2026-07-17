import { useEffect, useRef, useState } from 'react'
import type { ProgressEvent } from '../types'

interface UseSSEResult {
  messages: ProgressEvent[]
  done: boolean
  error: string | null
}

/** Subscribes to a backend SSE progress stream while `url` is non-null. */
export function useSSE(url: string | null): UseSSEResult {
  const [messages, setMessages] = useState<ProgressEvent[]>([])
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const sourceRef = useRef<EventSource | null>(null)

  useEffect(() => {
    setMessages([])
    setDone(false)
    setError(null)

    if (!url) return

    const source = new EventSource(url)
    sourceRef.current = source

    source.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data) as ProgressEvent
        setMessages((prev) => [...prev, parsed])
        // The run is genuinely over — close deliberately so EventSource doesn't
        // spend forever auto-reconnecting to a stream with nothing left to say.
        if (parsed.type === 'done') {
          setDone(true)
          source.close()
        }
        if (parsed.type === 'error') {
          setError(parsed.message ?? 'unknown error')
          source.close()
        }
      } catch {
        // ignore malformed frames
      }
    }
    // No source.close() here — a transient network drop mid-run should let
    // EventSource auto-reconnect (it resumes via Last-Event-ID against the
    // backend's ring buffer instead of duplicating already-seen messages).
    source.onerror = () => {}

    return () => {
      source.close()
      sourceRef.current = null
    }
  }, [url])

  return { messages, done, error }
}
