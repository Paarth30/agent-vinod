type Tone = 'green' | 'yellow' | 'red' | 'blue' | 'gray'

const LABEL_TONES: Record<string, Tone> = {
  Excellent: 'green',
  Good: 'blue',
  Fair: 'yellow',
  Low: 'red',
  tailored: 'green',
  ready: 'green',
  original: 'yellow',
  skipped: 'red',
  no_jd: 'gray',
}

export function StatusPill({ label, tone }: { label: string; tone?: Tone }) {
  const resolvedTone = tone ?? LABEL_TONES[label] ?? 'gray'
  return <span className={`pill pill-${resolvedTone}`}>{label}</span>
}
