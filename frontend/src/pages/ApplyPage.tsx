import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useSSE } from '../hooks/useSSE'
import { LogConsole } from '../components/LogConsole'
import { StatusPill } from '../components/StatusPill'
import { InlineLoading } from '../components/InlineLoading'
import { DiscoveryActiveBanner } from '../components/DiscoveryActiveBanner'
import type { ApplySummary, PendingManual } from '../types'

export function ApplyPage() {
  const [summaries, setSummaries] = useState<ApplySummary[]>([])
  const [pending, setPending] = useState<PendingManual[]>([])
  const [runId, setRunId] = useState<string | null>(null)
  const [resolving, setResolving] = useState<string | null>(null)

  const { messages, done } = useSSE(runId ? api.apply.streamUrl(runId) : null)

  const refreshSummaries = () => api.apply.list().then(setSummaries).catch(() => {})
  const refreshPending = () => api.apply.pending().then(setPending).catch(() => {})

  useEffect(() => {
    refreshSummaries()
    refreshPending()
    // Resume watching an apply batch still running (or just finished), same
    // reasoning as every other stage — and re-show any job that's currently
    // waiting on a manual-apply decision, since that browser tab is still open.
    api.status.get().then((s) => {
      if (s.active_apply_run_id) setRunId(s.active_apply_run_id)
    }).catch(() => {})
  }, [])

  useEffect(() => { if (done) { refreshSummaries(); refreshPending() } }, [done])

  useEffect(() => {
    for (const m of messages) {
      if (m.type === 'needs_manual_apply' && m.job_key) refreshPending()
      if (m.type === 'progress' && m.job_key) {
        const key = m.job_key
        const sent = m.methods_sent ?? []
        const failed = m.methods_failed ?? []
        const status = sent.length ? 'applied' : failed.length ? 'failed' : 'no_method'
        setSummaries((prev) => prev.map((s) => (
          s.job_key === key ? { ...s, status, methods_sent: sent, methods_failed: failed } : s
        )))
        refreshPending()
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.length])

  const start = async () => {
    const count = summaries.filter((s) => s.status === 'pending').length
    if (!window.confirm(`Send ${count} real application(s) now? This will email contacts and/or submit LinkedIn Easy Apply for every pending job.`)) {
      return
    }
    const { run_id } = await api.apply.start()
    setRunId(run_id)
  }

  const resolve = async (jobKey: string, applied: boolean) => {
    setResolving(jobKey)
    try {
      await api.apply.resolve(jobKey, applied)
      setPending((prev) => prev.filter((p) => p.job_key !== jobKey))
      refreshSummaries()
    } finally {
      setResolving(null)
    }
  }

  const applying = runId !== null && !done
  const pendingCount = summaries.filter((s) => s.status === 'pending').length

  return (
    <div className="stack">
      <DiscoveryActiveBanner />
      <div className="panel row-between">
        <h2>Send Applications</h2>
        <button className="primary" onClick={start} disabled={applying || !pendingCount}>
          {applying ? 'Sending…' : `Send ${pendingCount} application(s)`}
        </button>
      </div>

      {applying && (
        <div className="panel">
          <h3>Progress</h3>
          <LogConsole messages={messages} />
        </div>
      )}

      {!!pending.length && (
        <div className="panel" style={{ borderColor: 'var(--amber)' }}>
          <h3 style={{ color: 'var(--amber)' }}>Needs manual apply</h3>
          <p className="muted">LinkedIn Easy Apply couldn't finish these automatically. A browser window is open on each job below — apply by hand, then mark it here.</p>
          <div className="stack">
            {pending.map((p) => (
              <div key={p.job_key} className="row-between" style={{ borderTop: '1px solid var(--border)', paddingTop: 8, alignItems: 'flex-start' }}>
                <div style={{ flex: '1 1 auto', minWidth: 0 }}>
                  <strong>{p.company}</strong> — {p.title}
                  <br />
                  <a href={p.link} target="_blank" rel="noreferrer" className="muted" style={{ wordBreak: 'break-all' }}>{p.link}</a>
                </div>
                <div className="row" style={{ flexShrink: 0 }}>
                  <button className="primary" disabled={resolving === p.job_key} onClick={() => resolve(p.job_key, true)}>
                    Mark applied
                  </button>
                  <button className="danger" disabled={resolving === p.job_key} onClick={() => resolve(p.job_key, false)}>
                    Skip
                  </button>
                </div>
              </div>
            ))}
          </div>
          {resolving && <InlineLoading text="recording your decision" />}
        </div>
      )}

      <div className="panel">
        <h3>Applications</h3>
        {!summaries.length && <p className="muted">No jobs selected yet.</p>}
        {!!summaries.length && (
          <table>
            <thead>
              <tr><th>Company</th><th>Title</th><th>Sent via</th><th>Status</th><th>Job</th></tr>
            </thead>
            <tbody>
              {summaries.map((s) => (
                <tr key={s.job_key}>
                  <td>{s.company}</td>
                  <td>{s.title}</td>
                  <td>{s.methods_sent.join(', ') || <span className="muted">—</span>}</td>
                  <td>
                    <StatusPill
                      label={s.status}
                      tone={s.status === 'applied' ? 'green' : s.status === 'needs_manual' ? 'yellow' : s.status === 'failed' ? 'red' : 'gray'}
                    />
                  </td>
                  <td>
                    {s.link
                      ? <a href={s.link} target="_blank" rel="noreferrer">View</a>
                      : <span className="muted">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
