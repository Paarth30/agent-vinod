import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useSSE } from '../hooks/useSSE'
import { LogConsole } from '../components/LogConsole'
import { StatusPill } from '../components/StatusPill'
import { InlineLoading } from '../components/InlineLoading'
import { DiscoveryActiveBanner } from '../components/DiscoveryActiveBanner'
import type { ContactSummary } from '../types'

export function ContactsPage({ onProceed }: { onProceed: () => void }) {
  const [summaries, setSummaries] = useState<ContactSummary[]>([])
  const [runId, setRunId] = useState<string | null>(null)
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [proceeding, setProceeding] = useState(false)

  const [name, setName] = useState('')
  const [title, setTitle] = useState('')
  const [email, setEmail] = useState('')

  const { messages, done } = useSSE(runId ? api.contacts.streamUrl(runId) : null)
  const remaining = summaries.filter((s) => s.status !== 'found')

  const refreshSummaries = () => api.contacts.list().then(setSummaries).catch(() => {})

  useEffect(() => {
    refreshSummaries()
    api.status.get().then((s) => {
      if (s.active_contacts_run_id) setRunId(s.active_contacts_run_id)
    }).catch(() => {})
  }, [])

  useEffect(() => { if (done) refreshSummaries() }, [done])

  // Contacts progress events don't carry enough data to patch one row locally
  // (unlike ATS/keyword scores) — just re-fetch the list as each one lands.
  useEffect(() => {
    if (messages.some((m) => m.type === 'progress')) refreshSummaries()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.length])

  const findRemaining = async () => {
    const keys = remaining.map((s) => s.job_key)
    if (!keys.length) return
    const { run_id } = await api.contacts.find(keys)
    setRunId(run_id)
  }

  const researchAll = async () => {
    const { run_id } = await api.contacts.find()
    setRunId(run_id)
  }

  const openJob = (s: ContactSummary) => {
    setSelectedKey(s.job_key)
    setName(s.contact_name ?? '')
    setTitle(s.contact_title ?? '')
    setEmail(s.contact_email ?? '')
  }

  const withBusy = async (fn: () => Promise<ContactSummary>) => {
    setBusy(true)
    try {
      const s = await fn()
      openJob(s)
      refreshSummaries()
    } finally {
      setBusy(false)
    }
  }

  const proceed = async () => {
    setProceeding(true)
    try {
      await api.contacts.proceed()
      onProceed()
    } finally {
      setProceeding(false)
    }
  }

  const finding = runId !== null && !done

  return (
    <div className="stack">
      <DiscoveryActiveBanner />
      <div className="panel row-between">
        <h2>Find Contacts</h2>
        <div className="row">
          <button onClick={findRemaining} disabled={finding || !remaining.length}>
            {finding ? 'Searching…' : `Find ${remaining.length} remaining`}
          </button>
          <button onClick={researchAll} disabled={finding || !summaries.length}>Re-search all</button>
          <button className="primary" onClick={proceed} disabled={proceeding || !summaries.length}>
            {proceeding ? 'Proceeding…' : 'Proceed to Apply'}
          </button>
        </div>
      </div>

      {finding && (
        <div className="panel">
          <h3>Progress</h3>
          <LogConsole messages={messages} />
        </div>
      )}

      <div className="panel">
        <h3>Contacts</h3>
        <p className="muted">Only HR, recruiting, talent acquisition, or leadership contacts are ever auto-matched — nothing is sent to a random employee. If none was found, you can enter one manually.</p>
        {!summaries.length && <p className="muted">No jobs selected yet.</p>}
        {!!summaries.length && (
          <table>
            <thead>
              <tr><th>Company</th><th>Title</th><th>Contact</th><th>Email</th><th>Status</th></tr>
            </thead>
            <tbody>
              {summaries.map((s) => (
                <tr key={s.job_key} className={`selectable ${selectedKey === s.job_key ? 'active-row' : ''}`} onClick={() => openJob(s)}>
                  <td>{s.company}</td>
                  <td>{s.title}</td>
                  <td>{s.contact_name || <span className="muted">—</span>} {s.contact_title ? `(${s.contact_title})` : ''}</td>
                  <td>{s.contact_email || <span className="muted">—</span>}</td>
                  <td><StatusPill label={s.status === 'found' ? 'found' : 'not_found'} tone={s.status === 'found' ? 'green' : 'yellow'} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {selectedKey && (
        <div className="panel">
          <h3>Edit contact — {summaries.find((s) => s.job_key === selectedKey)?.company}</h3>
          <div className="grid-form">
            <label className="stack">
              <span className="muted">Name</span>
              <input type="text" value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="stack">
              <span className="muted">Title</span>
              <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} />
            </label>
            <label className="stack">
              <span className="muted">Email</span>
              <input type="text" value={email} onChange={(e) => setEmail(e.target.value)} />
            </label>
          </div>
          <div className="row" style={{ marginTop: 12 }}>
            <button
              className="primary"
              disabled={busy || !email.trim()}
              onClick={() => withBusy(() => api.contacts.set(selectedKey, { name, title, email }))}
            >
              Save contact
            </button>
            <button disabled={busy} onClick={() => withBusy(() => api.contacts.refresh(selectedKey))}>
              Re-search this job
            </button>
            <button className="danger" disabled={busy} onClick={() => withBusy(() => api.contacts.clear(selectedKey))}>
              Clear contact
            </button>
          </div>
          {busy && <InlineLoading text="working" />}
        </div>
      )}
    </div>
  )
}
