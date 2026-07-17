import { useEffect, useState } from 'react'
import { api } from '../api/client'

/** Shown on Resume/Cover Letter pages so it's obvious when the jobs listed
 * below are from a previous run while a new discovery search is still going
 * in the background — otherwise it looks like unexplained stale data. */
export function DiscoveryActiveBanner() {
  const [active, setActive] = useState(false)

  useEffect(() => {
    api.status.get().then((s) => setActive(!!s.active_discovery_run_id)).catch(() => {})
  }, [])

  if (!active) return null

  return (
    <div className="panel" style={{ borderColor: 'var(--amber)' }}>
      <p style={{ color: 'var(--amber)' }}>
        A new job search is running in the background — the results below are from a previous run.
        Go to the Discovery tab to watch its progress.
      </p>
    </div>
  )
}
