import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useSSE } from '../hooks/useSSE'
import { LogConsole } from '../components/LogConsole'
import { JobTable } from '../components/JobTable'
import { InlineLoading } from '../components/InlineLoading'
import type { Job } from '../types'

const csv = (arr: string[]) => arr.join(', ')
const parseCsv = (s: string) => s.split(',').map((x) => x.trim()).filter(Boolean)

export function DiscoveryPage({ onProceed }: { onProceed: () => void }) {
  const [titles, setTitles] = useState('')
  const [locations, setLocations] = useState('')
  const [workTypes, setWorkTypes] = useState('')
  const [maxJobs, setMaxJobs] = useState(20)
  const [minAtsScore, setMinAtsScore] = useState(50)
  const [experience, setExperience] = useState('any')
  const [minYears, setMinYears] = useState('')
  const [maxYears, setMaxYears] = useState('')
  const [suggesting, setSuggesting] = useState(false)

  const [runId, setRunId] = useState<string | null>(null)
  const [jobs, setJobs] = useState<Job[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [mode, setMode] = useState<'fresh' | 'previous'>('fresh')
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [rejecting, setRejecting] = useState<string | null>(null)

  const { messages, done, error } = useSSE(runId ? api.discovery.streamUrl(runId) : null)

  // Quick Apply — paste a single LinkedIn job link and funnel it into the pipeline.
  const [quickLink, setQuickLink] = useState('')
  const [quickRunId, setQuickRunId] = useState<string | null>(null)
  const [quickErr, setQuickErr] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)

  const quick = useSSE(quickRunId ? api.quickApply.streamUrl(quickRunId) : null)
  const quickDoneEvent = quick.messages.find((m) => m.type === 'done')
  const quickJob = quickDoneEvent?.job ?? null
  const quickWarning = quickDoneEvent?.warning ?? null
  const quickBusy = quickRunId !== null && !quick.done && !quick.error

  useEffect(() => {
    api.discovery.defaults().then((d) => {
      setTitles(csv(d.titles))
      setLocations(csv(d.locations))
      setWorkTypes(csv(d.work_types))
      setMaxJobs(d.max_jobs)
      setMinAtsScore(d.min_ats_score)
      setExperience(d.experience || 'any')
      setMinYears(d.min_years != null ? String(d.min_years) : '')
      setMaxYears(d.max_years != null ? String(d.max_years) : '')
    }).catch(() => {})

    // Resume watching a discovery run that's still going (or just finished)
    // in the backend, so navigating away and back doesn't lose the live log
    // or make an in-progress/completed search look like it never happened.
    api.status.get().then((s) => {
      if (s.active_discovery_run_id) {
        setMode('fresh')
        setRunId(s.active_discovery_run_id)
      }
      if (s.job_count > 0) {
        api.jobs.list().then(setJobs).catch(() => {})
      }
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (done) api.jobs.list().then(setJobs).catch(() => {})
  }, [done])

  const startSearch = async () => {
    setMode('fresh')
    setJobs([])
    setSelected(new Set())
    setLoading(true)
    try {
      const { run_id } = await api.discovery.start({
        titles: parseCsv(titles),
        locations: parseCsv(locations),
        work_types: parseCsv(workTypes),
        max_jobs: maxJobs,
        min_ats_score: minAtsScore,
        experience,
        min_years: minYears.trim() ? Number(minYears) : null,
        max_years: maxYears.trim() ? Number(maxYears) : null,
      })
      setRunId(run_id)
    } finally {
      setLoading(false)
    }
  }

  const stopSearch = async () => {
    if (runId) await api.discovery.stop(runId)
  }

  const loadPrevious = async () => {
    setMode('previous')
    setLoading(true)
    try {
      const prev = await api.jobs.previous()
      setJobs(prev)
      setSelected(new Set())
    } finally {
      setLoading(false)
    }
  }

  const toggle = (key: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key); else next.add(key)
      return next
    })
  }

  const reject = async (key: string) => {
    setRejecting(key)
    try {
      await api.jobs.reject(key)
      setJobs((prev) => prev.filter((j) => j.job_key !== key))
      setSelected((prev) => {
        const next = new Set(prev)
        next.delete(key)
        return next
      })
    } finally {
      setRejecting(null)
    }
  }

  const proceed = async () => {
    if (!selected.size) return
    setSubmitting(true)
    try {
      await api.jobs.select(Array.from(selected))
      onProceed()
    } finally {
      setSubmitting(false)
    }
  }

  const startQuickApply = async () => {
    setQuickErr(null)
    const link = quickLink.trim()
    if (!link) return
    setStarting(true)
    try {
      const { run_id } = await api.quickApply.start(link)
      setQuickRunId(run_id)
    } catch (e) {
      setQuickErr(e instanceof Error ? e.message : 'Failed to start')
    } finally {
      setStarting(false)
    }
  }

  const startPipelineForQuickJob = async () => {
    if (!quickJob) return
    setSubmitting(true)
    try {
      await api.jobs.select([quickJob.job_key])
      onProceed()
    } finally {
      setSubmitting(false)
    }
  }

  const cancelQuickApply = () => {
    setQuickRunId(null)
    setQuickLink('')
    setQuickErr(null)
  }

  const suggestTitles = async () => {
    setSuggesting(true)
    try {
      const { titles: suggested } = await api.discovery.suggestTitles()
      setTitles(csv(suggested))
    } catch {
      alert('Could not get title suggestions — check the resume file exists and Claude is reachable.')
    } finally {
      setSuggesting(false)
    }
  }

  const searching = runId !== null && !done && !error

  return (
    <div className="stack">
      <div className="panel">
        <h2>Quick Apply — paste a LinkedIn job link</h2>
        <div className="row">
          <input
            type="text"
            placeholder="https://www.linkedin.com/jobs/view/..."
            value={quickLink}
            onChange={(e) => setQuickLink(e.target.value)}
            disabled={quickBusy || !!quickJob}
          />
          <button className="primary" onClick={startQuickApply} disabled={quickBusy || starting || !!quickJob || !quickLink.trim()}>
            {quickBusy ? 'Working…' : 'Quick Apply'}
          </button>
        </div>
        {quickErr && <p className="error-text">{quickErr}</p>}

        {quickRunId && !quickJob && (
          <div style={{ marginTop: 12 }}>
            <LogConsole messages={quick.messages} />
            {quick.error && <p className="error-text">{quick.error}</p>}
          </div>
        )}

        {quickJob && (
          <div className="panel" style={{ marginTop: 12 }}>
            {quickWarning && <p className="warn-text">⚠ {quickWarning}</p>}
            <h3>{quickJob.title} — {quickJob.company}</h3>
            <p className="muted">{quickJob.location} · {quickJob.work_type ?? 'unknown'}</p>
            <p>
              ATS score:{' '}
              {quickJob.ats?.score != null
                ? <strong>{quickJob.ats.score}% {quickJob.ats.label}</strong>
                : <span className="muted">no score (JD/resume unavailable)</span>}
            </p>
            <div className="row" style={{ marginTop: 8 }}>
              <button className="primary" onClick={startPipelineForQuickJob} disabled={submitting}>
                {submitting ? 'Starting…' : 'Start Pipeline →'}
              </button>
              <button onClick={cancelQuickApply} disabled={submitting}>Cancel</button>
            </div>
          </div>
        )}
      </div>

      <div className="panel">
        <h2>Job Discovery</h2>
        <div className="grid-form">
          <label className="stack">
            <span className="muted">Job titles (comma-separated)</span>
            <div className="row">
              <input type="text" value={titles} onChange={(e) => setTitles(e.target.value)} disabled={searching} />
              <button onClick={suggestTitles} disabled={searching || suggesting} title="Ask Claude which roles suit your resume">
                {suggesting ? 'Asking Claude…' : 'Suggest from resume'}
              </button>
            </div>
            {suggesting && <InlineLoading text="reading your resume" />}
          </label>
          <label className="stack">
            <span className="muted">Locations (comma-separated)</span>
            <input type="text" value={locations} onChange={(e) => setLocations(e.target.value)} disabled={searching} />
          </label>
          <label className="stack">
            <span className="muted">Work types (comma-separated)</span>
            <input type="text" value={workTypes} onChange={(e) => setWorkTypes(e.target.value)} disabled={searching} />
          </label>
          <label className="stack">
            <span className="muted">Max jobs per run</span>
            <input type="text" inputMode="numeric" value={maxJobs} onChange={(e) => setMaxJobs(Number(e.target.value) || 0)} disabled={searching} />
          </label>
          <label className="stack">
            <span className="muted">Minimum ATS score to keep a job (%)</span>
            <input type="text" inputMode="numeric" value={minAtsScore} onChange={(e) => setMinAtsScore(Number(e.target.value) || 0)} disabled={searching} />
          </label>
          <label className="stack">
            <span className="muted">Experience level</span>
            <select value={experience} onChange={(e) => setExperience(e.target.value)} disabled={searching}>
              <option value="internship">Internship</option>
              <option value="entry">Entry (0-2 yrs)</option>
              <option value="mid">Mid-Senior (2-5 yrs)</option>
              <option value="senior">Senior (5+ yrs)</option>
              <option value="lead">Director/Lead</option>
              <option value="any">Any</option>
            </select>
          </label>
          <label className="stack">
            <span className="muted">Your years of experience (min-max, blank = no filter)</span>
            <div className="row">
              <input type="text" inputMode="numeric" placeholder="min" value={minYears} onChange={(e) => setMinYears(e.target.value)} disabled={searching} />
              <input type="text" inputMode="numeric" placeholder="max" value={maxYears} onChange={(e) => setMaxYears(e.target.value)} disabled={searching} />
            </div>
          </label>
        </div>
        <div className="row" style={{ marginTop: 12 }}>
          <button className="primary" onClick={startSearch} disabled={loading || searching}>
            {searching ? 'Searching…' : 'Start search'}
          </button>
          <button onClick={stopSearch} disabled={!searching}>Stop</button>
          <button onClick={loadPrevious} disabled={loading || searching}>
            {loading && mode === 'previous' ? 'Loading…' : 'Use previously found jobs'}
          </button>
        </div>
      </div>

      {mode === 'fresh' && runId && (
        <div className="panel">
          <h3>Progress</h3>
          <LogConsole messages={messages} />
          {error && <p className="error-text">{error}</p>}
        </div>
      )}

      <div className="panel">
        <div className="row-between">
          <h2>{mode === 'previous' ? 'Previously Found Jobs' : 'Jobs Found'}</h2>
          <button className="primary" onClick={proceed} disabled={!selected.size || submitting}>
            {submitting ? 'Proceeding…' : `Proceed to Resume Tailoring (${selected.size})`}
          </button>
        </div>
        <JobTable
          jobs={jobs}
          selected={selected}
          loading={loading}
          rejectingKey={rejecting}
          onToggle={toggle}
          onSelectAll={() => setSelected(new Set(jobs.map((j) => j.job_key)))}
          onSelectNone={() => setSelected(new Set())}
          onReject={reject}
        />
      </div>
    </div>
  )
}
