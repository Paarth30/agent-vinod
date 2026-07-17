import type { Job } from '../types'
import { StatusPill } from './StatusPill'
import { InlineLoading } from './InlineLoading'

interface JobTableProps {
  jobs: Job[]
  selected: Set<string>
  onToggle: (jobKey: string) => void
  onSelectAll: () => void
  onSelectNone: () => void
  onReject?: (jobKey: string) => void
  rejectingKey?: string | null
  loading?: boolean
}

export function JobTable({ jobs, selected, onToggle, onSelectAll, onSelectNone, onReject, rejectingKey, loading }: JobTableProps) {
  if (!jobs.length) {
    return loading ? <InlineLoading text="loading jobs" /> : <p className="muted">No jobs yet.</p>
  }

  return (
    <div className="stack">
      <div className="row">
        <button onClick={onSelectAll}>Select all</button>
        <button onClick={onSelectNone}>Select none</button>
        <span className="muted">{selected.size} of {jobs.length} selected</span>
      </div>
      <table>
        <thead>
          <tr>
            <th></th>
            <th>Title</th>
            <th>Company</th>
            <th>Location</th>
            <th>Type</th>
            <th>ATS</th>
            <th>Posted</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr key={job.job_key} className="selectable" onClick={() => onToggle(job.job_key)}>
              <td onClick={(e) => e.stopPropagation()}>
                <input type="checkbox" checked={selected.has(job.job_key)} onChange={() => onToggle(job.job_key)} />
              </td>
              <td>{job.title}</td>
              <td>{job.company}</td>
              <td>{job.location}</td>
              <td>{job.work_type && <StatusPill label={job.work_type} tone={job.work_type === 'remote' ? 'green' : job.work_type === 'hybrid' ? 'yellow' : 'red'} />}</td>
              <td>
                {job.ats?.score != null
                  ? <StatusPill label={`${job.ats.score}% ${job.ats.label ?? ''}`} tone={job.ats.score >= 80 ? 'green' : job.ats.score >= 65 ? 'blue' : job.ats.score >= 50 ? 'yellow' : 'red'} />
                  : <span className="muted">No JD</span>}
              </td>
              <td className="muted">{job.posted_text}</td>
              <td onClick={(e) => e.stopPropagation()}>
                {onReject && (
                  <button className="danger" disabled={rejectingKey === job.job_key} onClick={() => onReject(job.job_key)}>
                    {rejectingKey === job.job_key ? '…' : 'Reject'}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
