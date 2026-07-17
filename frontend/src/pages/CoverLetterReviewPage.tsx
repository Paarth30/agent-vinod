import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useSSE } from '../hooks/useSSE'
import { LogConsole } from '../components/LogConsole'
import { DiffView } from '../components/DiffView'
import { ChatBox } from '../components/ChatBox'
import { StatusPill } from '../components/StatusPill'
import { DiscoveryActiveBanner } from '../components/DiscoveryActiveBanner'
import { InlineLoading } from '../components/InlineLoading'
import type { LetterDetail, LetterSummary } from '../types'

export function CoverLetterReviewPage({ onProceed }: { onProceed: () => void }) {
  const [summaries, setSummaries] = useState<LetterSummary[]>([])
  const [runId, setRunId] = useState<string | null>(null)
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [detail, setDetail] = useState<LetterDetail | null>(null)
  const [busy, setBusy] = useState(false)
  const [proceeding, setProceeding] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)

  const { messages, done } = useSSE(runId ? api.letters.streamUrl(runId) : null)
  const anyReady = summaries.some((s) => s.status === 'ready')
  const remaining = summaries.filter((s) => s.status !== 'ready')

  const refreshSummaries = () => api.letters.list().then(setSummaries).catch(() => {})

  useEffect(() => {
    refreshSummaries()
    // Resume watching a generation batch that's still running (or already
    // finished) in the backend — navigating away and back must not lose it.
    api.status.get().then((s) => {
      if (s.active_letter_run_id) setRunId(s.active_letter_run_id)
    }).catch(() => {})
  }, [])

  useEffect(() => { if (done) refreshSummaries() }, [done])

  // Apply per-job progress updates to the visible table in real time.
  useEffect(() => {
    for (const m of messages) {
      if (m.type !== 'progress' || !m.job_key) continue
      const key = m.job_key
      setSummaries((prev) => prev.map((s) => (
        s.job_key === key
          ? { ...s, keyword_score: m.score ?? s.keyword_score, keyword_label: m.label ?? s.keyword_label, status: m.score != null ? 'ready' : s.status }
          : s
      )))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.length])

  const generateRemaining = async () => {
    const keys = remaining.map((s) => s.job_key)
    if (!keys.length) return
    const { run_id } = await api.letters.generate(keys)
    setRunId(run_id)
  }

  const regenerateAll = async () => {
    const { run_id } = await api.letters.generate()
    setRunId(run_id)
  }

  const openJob = async (key: string) => {
    setSelectedKey(key)
    setDetailLoading(true)
    try {
      const d = await api.letters.detail(key)
      setDetail(d)
    } finally {
      setDetailLoading(false)
    }
  }

  const withBusy = async (fn: () => Promise<LetterDetail>) => {
    setBusy(true)
    try {
      const d = await fn()
      setDetail(d)
      refreshSummaries()
    } finally {
      setBusy(false)
    }
  }

  const proceed = async () => {
    setProceeding(true)
    try {
      await api.letters.proceed()
      onProceed()
    } finally {
      setProceeding(false)
    }
  }

  const generating = runId !== null && !done

  return (
    <div className="stack">
      <DiscoveryActiveBanner />
      <div className="panel row-between">
        <h2>Cover Letters</h2>
        <div className="row">
          <button onClick={generateRemaining} disabled={generating || !remaining.length}>
            {generating ? 'Generating…' : `Generate ${remaining.length} remaining`}
          </button>
          <button onClick={regenerateAll} disabled={generating || !summaries.length}>Re-generate all</button>
          <button className="primary" onClick={proceed} disabled={proceeding || !anyReady}>
            {proceeding ? 'Finishing…' : 'Accept All & Finish'}
          </button>
        </div>
      </div>

      {generating && (
        <div className="panel">
          <h3>Progress</h3>
          <LogConsole messages={messages} />
          <p className="muted">The list below keeps updating live — click any job, ready or not, to view or edit it while this runs.</p>
        </div>
      )}

      <div className="panel">
        <h3>Cover Letters</h3>
        {!summaries.length && <p className="muted">No jobs selected yet.</p>}
        {!!summaries.length && (
          <table>
            <thead>
              <tr><th>Company</th><th>Title</th><th>Keyword Match</th><th>Status</th></tr>
            </thead>
            <tbody>
              {summaries.map((s) => (
                <tr key={s.job_key} className={`selectable ${selectedKey === s.job_key ? 'active-row' : ''}`} onClick={() => openJob(s.job_key)}>
                  <td>{s.company}</td>
                  <td>{s.title}</td>
                  <td>{s.keyword_score != null ? `${s.keyword_score}% ${s.keyword_label ?? ''}` : '—'}</td>
                  <td><StatusPill label={s.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {detailLoading && !detail && (
        <div className="panel"><InlineLoading text="loading letter" /></div>
      )}

      {detail && (
        <div className="panel">
          <h3>{detail.company} — {detail.title}</h3>
          {detailLoading && <InlineLoading text="loading letter" />}
          {detail.score?.score != null && (
            <p className="muted">
              Keyword match: {detail.score.score}% {detail.score.label} ({detail.score.matched}/{detail.score.total} covered)
              {!!detail.score.missing?.length && <> — missing: {detail.score.missing.join(', ')}</>}
            </p>
          )}
          <div className="stack" style={{ marginTop: 8 }}>
            <DiffView diff={detail.diff} fullText={detail.letter_text} />
            <ChatBox
              busy={busy}
              onFeedback={(text) => withBusy(() => api.letters.feedback(detail.job_key, text))}
              onRegen={() => withBusy(() => api.letters.regen(detail.job_key))}
              onSkip={() => withBusy(() => api.letters.skip(detail.job_key))}
            />
          </div>
        </div>
      )}
    </div>
  )
}
