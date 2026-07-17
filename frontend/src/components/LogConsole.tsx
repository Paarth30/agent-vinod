import { useEffect, useRef } from 'react'
import type { ProgressEvent } from '../types'

export function LogConsole({ messages }: { messages: ProgressEvent[] }) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [messages])

  const lines = messages.map((m, i) => {
    if (m.type === 'log') return <div key={i}>{m.message}</div>
    if (m.type === 'progress') {
      const parts = [`[${m.index}/${m.total}]`, m.company, m.title ? `— ${m.title}` : null, m.message]
      if (m.ats_before !== undefined && m.ats_after !== undefined) {
        parts.push(`ATS ${m.ats_before}%→${m.ats_after}%`)
      }
      if (m.score !== undefined) parts.push(`Keyword match: ${m.score}% ${m.label ?? ''}`)
      return <div key={i}>{parts.filter(Boolean).join(' ')}</div>
    }
    if (m.type === 'done') return <div key={i} style={{ color: 'var(--green-fg)' }}>Done — {m.count} job(s).</div>
    if (m.type === 'error') return <div key={i} className="error-text">Error: {m.message}</div>
    return null
  })

  return <div className="log-console" ref={ref}>{lines.length ? lines : <span className="muted">No output yet.</span>}</div>
}
