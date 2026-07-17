interface Step {
  key: string
  label: string
}

const STEPS: Step[] = [
  { key: 'discover', label: 'Discovery' },
  { key: 'resumes', label: 'Resumes' },
  { key: 'letters', label: 'Cover Letters' },
  { key: 'contacts', label: 'Contacts' },
  { key: 'apply', label: 'Apply' },
]

const STAGE_TO_STEP: Record<string, string> = {
  idle: 'discover',
  discovering: 'discover',
  selecting: 'discover',
  tailoring_resumes: 'resumes',
  reviewing_resumes: 'resumes',
  tailoring_letters: 'letters',
  reviewing_letters: 'letters',
  finding_contacts: 'contacts',
  reviewing_contacts: 'contacts',
  applying: 'apply',
  done: 'apply',
}

export function Stepper({ stage, current, onNavigate }: { stage: string; current: string; onNavigate: (key: string) => void }) {
  const activeFromStage = STAGE_TO_STEP[stage] ?? 'discover'
  const activeIndex = STEPS.findIndex((s) => s.key === activeFromStage)

  return (
    <div className="stepper">
      {STEPS.map((step, i) => {
        const cls = step.key === current ? 'current' : i < activeIndex ? 'done' : ''
        return (
          <span key={step.key}>
            {i > 0 && <span className="stepper-sep">→</span>}
            <button
              className={`stepper-step ${cls}`}
              style={{ border: 'none' }}
              onClick={() => onNavigate(step.key)}
            >
              {step.label}
            </button>
          </span>
        )
      })}
    </div>
  )
}
