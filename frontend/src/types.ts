export interface AtsBreakdown {
  skills?: number
  keywords?: number
  experience?: number
  education?: number
  title?: number
}

export interface AtsScore {
  score: number | null
  label?: string
  breakdown?: AtsBreakdown
  matched_skills?: string[]
  missing_skills?: string[]
}

export interface Job {
  job_key: string
  title: string
  company: string
  location: string
  link: string
  work_type?: string | null
  priority?: number | null
  posted_text?: string | null
  ats?: AtsScore | null
}

export interface DiffLine {
  type: 'add' | 'del' | 'hunk' | 'context'
  text: string
}

export interface ResumeSummary {
  job_key: string
  company: string
  title: string
  ats_before: number | null
  ats_after: number | null
  status: 'tailored' | 'original' | 'no_jd'
}

export interface ResumeDetail {
  job_key: string
  company: string
  title: string
  resume_text: string | null
  diff: DiffLine[]
  ats_before: AtsScore
  ats_after: AtsScore
}

export interface LetterSummary {
  job_key: string
  company: string
  title: string
  keyword_score: number | null
  keyword_label: string | null
  status: 'ready' | 'skipped'
}

export interface LetterScore {
  score?: number
  label?: string
  matched?: number
  total?: number
  missing?: string[]
}

export interface LetterDetail {
  job_key: string
  company: string
  title: string
  letter_text: string | null
  diff: DiffLine[]
  score: LetterScore
}

export interface ContactSummary {
  job_key: string
  company: string
  title: string
  contact_name: string | null
  contact_title: string | null
  contact_email: string | null
  source: string | null
  status: 'found' | 'not_found'
}

export interface ApplySummary {
  job_key: string
  company: string
  title: string
  link: string
  status: 'pending' | 'applied' | 'failed' | 'needs_manual' | 'no_method'
  methods_sent: string[]
  methods_failed: string[]
}

export interface PendingManual {
  job_key: string
  company: string
  title: string
  link: string
}

export interface StatusResponse {
  run_id: string | null
  stage: string
  job_count: number
  active_discovery_run_id: string | null
  active_resume_run_id: string | null
  active_letter_run_id: string | null
  active_contacts_run_id: string | null
  active_apply_run_id: string | null
}

export interface ProgressEvent {
  type: 'log' | 'progress' | 'done' | 'error' | 'needs_manual_apply'
  message?: string
  index?: number
  total?: number
  job_key?: string
  company?: string
  title?: string
  link?: string
  ats_before?: number | null
  ats_after?: number | null
  score?: number
  label?: string
  count?: number
  methods_sent?: string[]
  methods_failed?: string[]
  job?: Job
  warning?: string | null
}
