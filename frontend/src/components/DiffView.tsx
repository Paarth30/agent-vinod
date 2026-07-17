import type { DiffLine } from '../types'

const CLASS_FOR: Record<DiffLine['type'], string> = {
  add: 'diff-line-add',
  del: 'diff-line-del',
  hunk: 'diff-line-hunk',
  context: 'diff-line-context',
}

export function DiffView({ diff, fullText }: { diff: DiffLine[]; fullText?: string | null }) {
  if (!diff.length) {
    if (fullText) {
      return <div className="diff-view">{fullText}</div>
    }
    return <div className="diff-view muted">No changes from the original.</div>
  }
  return (
    <div className="diff-view">
      {diff.map((line, i) => (
        <span key={i} className={CLASS_FOR[line.type]}>
          {(line.type === 'add' ? '+ ' : line.type === 'del' ? '- ' : '  ') + line.text}
        </span>
      ))}
    </div>
  )
}
