import type { AtsScore } from '../types'
import { StatusPill } from './StatusPill'

const ROWS: [string, keyof NonNullable<AtsScore['breakdown']>][] = [
  ['Skills /35', 'skills'],
  ['Keywords /30', 'keywords'],
  ['Experience /20', 'experience'],
  ['Education /10', 'education'],
  ['Title /5', 'title'],
]

function Delta({ before, after }: { before: number; after: number }) {
  const d = after - before
  if (d > 0) return <span className="delta-pos">+{d}</span>
  if (d < 0) return <span className="delta-neg">{d}</span>
  return <span className="delta-zero">=</span>
}

export function AtsPanel({ before, after }: { before: AtsScore; after: AtsScore }) {
  const b = before.breakdown ?? {}
  const a = after.breakdown ?? {}

  return (
    <div className="panel">
      <h3>ATS Score</h3>
      <table className="ats-table">
        <thead>
          <tr><th>Category</th><th>Before</th><th>After</th><th>Change</th></tr>
        </thead>
        <tbody>
          {ROWS.map(([label, key]) => (
            <tr key={key}>
              <td className="muted">{label}</td>
              <td>{b[key] ?? 0}</td>
              <td>{a[key] ?? 0}</td>
              <td><Delta before={b[key] ?? 0} after={a[key] ?? 0} /></td>
            </tr>
          ))}
          <tr>
            <td><strong>TOTAL</strong></td>
            <td>{before.score ?? 0}% {before.label && <StatusPill label={before.label} />}</td>
            <td>{after.score ?? 0}% {after.label && <StatusPill label={after.label} />}</td>
            <td><strong><Delta before={before.score ?? 0} after={after.score ?? 0} /></strong></td>
          </tr>
        </tbody>
      </table>
      {!!after.missing_skills?.length && (
        <p className="muted" style={{ marginTop: 8 }}>
          Skills still missing: {after.missing_skills.slice(0, 8).join(', ')}
        </p>
      )}
    </div>
  )
}
