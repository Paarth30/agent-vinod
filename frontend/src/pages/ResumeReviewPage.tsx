import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useSSE } from '../hooks/useSSE'
import { LogConsole } from '../components/LogConsole'
import { DiffView } from '../components/DiffView'
import { AtsPanel } from '../components/AtsPanel'
import { ChatBox } from '../components/ChatBox'
import { StatusPill } from '../components/StatusPill'
import { DiscoveryActiveBanner } from '../components/DiscoveryActiveBanner'
import { InlineLoading } from '../components/InlineLoading'
import type { ResumeDetail, ResumeSummary } from '../types'

export function ResumeReviewPage({ onProceed }: { onProceed: () => void }) {
  const [summaries, setSummaries] = useState<ResumeSummary[]>([])
  const [runId, setRunId] = useState<string | null>(null)
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [detail, setDetail] = useState<ResumeDetail | null>(null)
  const [busy, setBusy] = useState(false);
  const [proceeding, setProceeding] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)

  const { messages, done } = useSSE(runId ? api.resumes.streamUrl(runId) : null)
  const anyTailored = summaries.some((s) => s.status === 'tailored')
  const untailored = summaries.filter((s) => s.status !== 'tailored')

  const refreshSummaries = () => api.resumes.list().then(setSummaries).catch(() => {})

  useEffect(() => {
    refreshSummaries()
    // Resume watching a tailoring batch that's still running (or already
    // finished) in the backend — same reasoning as DiscoveryPage: navigating
    // away and back must not lose the live view of work still in flight.
    api.status.get().then((s) => {
      if (s.active_resume_run_id) setRunId(s.active_resume_run_id)
    }).catch(() => {})
  }, [])

  useEffect(() => { if (done) refreshSummaries() }, [done])

  // Apply per-job progress updates to the visible table in real time, instead
  // of only refreshing once the whole batch finishes.
  useEffect(() => {
    for (const m of messages) {
      if (m.type !== 'progress' || !m.job_key) continue
      const key = m.job_key
      setSummaries((prev) => prev.map((s) => (
        s.job_key === key
          ? { ...s, ats_before: m.ats_before ?? s.ats_before, ats_after: m.ats_after ?? s.ats_after, status: m.ats_after != null ? 'tailored' : s.status }
          : s
      )))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.length])

  const tailorRemaining = async () => {
    const keys = untailored.map((s) => s.job_key)
    if (!keys.length) return
    const { run_id } = await api.resumes.tailor(keys)
    setRunId(run_id)
  }

  const retailorAll = async () => {
    const { run_id } = await api.resumes.tailor()
    setRunId(run_id)
  }

  const openJob = async (key: string) => {
    setSelectedKey(key)
    setDetailLoading(true)
    try {
      const d = await api.resumes.detail(key)
      setDetail(d)
    } finally {
      setDetailLoading(false)
    }
  }

  const withBusy = async (fn: () => Promise<ResumeDetail>) => {
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
      await api.resumes.proceed()
      onProceed()
    } finally {
      setProceeding(false)
    }
  }

  const tailoring = runId !== null && !done

  return (
    <div className="stack">
      <DiscoveryActiveBanner />
      <div className="panel row-between">
        <h2>Resume Tailoring</h2>
        <div className="row">
          <button onClick={tailorRemaining} disabled={tailoring || !untailored.length}>
            {tailoring ? 'Tailoring…' : `Tailor ${untailored.length} remaining`}
          </button>
          <button onClick={retailorAll} disabled={tailoring || !summaries.length}>Re-tailor all</button>
          <button className="primary" onClick={proceed} disabled={proceeding || !anyTailored}>
            {proceeding ? 'Proceeding…' : 'Accept All & Continue'}
          </button>
        </div>
      </div>

      {tailoring && (
        <div className="panel">
          <h3>Progress</h3>
          <LogConsole messages={messages} />
          <p className="muted">The list below keeps updating live — click any job, tailored or not, to view or edit it while this runs.</p>
        </div>
      )}

      <div className="panel">
        <h3>Tailored Resumes</h3>
        {!summaries.length && <p className="muted">No jobs selected yet.</p>}
        {!!summaries.length && (
          <table>
            <thead>
              <tr><th>Company</th><th>Title</th><th>ATS Before→After</th><th>Status</th></tr>
            </thead>
            <tbody>
              {summaries.map((s) => (
                <tr key={s.job_key} className={`selectable ${selectedKey === s.job_key ? 'active-row' : ''}`} onClick={() => openJob(s.job_key)}>
                  <td>{s.company}</td>
                  <td>{s.title}</td>
                  <td>{s.ats_before ?? '—'}% → {s.ats_after ?? '—'}%</td>
                  <td><StatusPill label={s.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {detailLoading && !detail && (
        <div className="panel"><InlineLoading text="loading resume" /></div>
      )}

      {detail && (
        <div className="panel">
          <div className="row-between">
            <h3>{detail.company} — {detail.title}</h3>
            <a href={api.resumes.pdfUrl(detail.job_key)} target="_blank" rel="noreferrer">
              <button>Preview PDF</button>
            </a>
          </div>
          {detailLoading && <InlineLoading text="loading resume" />}
          <div className="detail-layout">
            <AtsPanel before={detail.ats_before} after={detail.ats_after} />
            <div className="stack">
              <DiffView diff={detail.diff} fullText={detail.resume_text} />
              <ChatBox
                busy={busy}
                onFeedback={(text) => withBusy(() => api.resumes.feedback(detail.job_key, text))}
                onRegen={() => withBusy(() => api.resumes.regen(detail.job_key))}
                onSkip={() => withBusy(() => api.resumes.skip(detail.job_key))}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
