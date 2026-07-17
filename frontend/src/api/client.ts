import type {
  Job, ResumeSummary, ResumeDetail, LetterSummary, LetterDetail, StatusResponse,
  ContactSummary, ApplySummary, PendingManual,
} from '../types'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  // no-store: every one of these endpoints returns live, mutable state (job
  // status, tailored text, ATS scores) — the browser must never serve a
  // cached GET response for them.
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
    ...init,
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}: ${body}`)
  }
  if (res.status === 204) return undefined as unknown as T
  return res.json() as Promise<T>
}

// Belt-and-suspenders on top of `cache: 'no-store'` — a unique query string
// guarantees no intermediary (browser cache, dev-server proxy) can ever
// short-circuit a GET with a previously-seen response for the same URL.
const bust = (path: string) => path + (path.includes('?') ? '&' : '?') + '_=' + Date.now()
const get = <T>(path: string) => req<T>(bust(path))
const post = <T>(path: string, body?: unknown) =>
  req<T>(path, { method: 'POST', body: body !== undefined ? JSON.stringify(body) : undefined })

export const api = {
  status: {
    get: () => get<StatusResponse>('/api/status'),
    syncExcel: () => post<{ ok: boolean; count: number }>('/api/excel/sync'),
  },
  discovery: {
    defaults: () => get<{ titles: string[]; locations: string[]; work_types: string[]; max_jobs: number; min_ats_score: number; experience: string; min_years: number | null; max_years: number | null }>('/api/discovery/defaults'),
    start: (body: { titles?: string[]; locations?: string[]; work_types?: string[]; max_jobs?: number; min_ats_score?: number; experience?: string; min_years?: number | null; max_years?: number | null }) =>
      post<{ run_id: string }>('/api/discovery/start', body),
    stop: (runId: string) => post<{ ok: boolean }>(`/api/discovery/stop/${runId}`),
    streamUrl: (runId: string) => `/api/discovery/stream/${runId}`,
    suggestTitles: () => post<{ titles: string[] }>('/api/discovery/suggest-titles'),
  },
  quickApply: {
    start: (link: string) => post<{ run_id: string }>('/api/quick-apply/start', { link }),
    streamUrl: (runId: string) => `/api/quick-apply/stream/${runId}`,
  },
  jobs: {
    list: () => get<Job[]>('/api/jobs'),
    previous: () => get<Job[]>('/api/jobs/previous'),
    select: (jobKeys: string[]) => post<{ ok: boolean; count: number }>('/api/jobs/select', { job_keys: jobKeys }),
    reject: (jobKey: string) => post<{ ok: boolean }>(`/api/jobs/${encodeURIComponent(jobKey)}/reject`),
  },
  resumes: {
    tailor: (jobKeys?: string[]) => post<{ run_id: string }>('/api/resumes/tailor', { job_keys: jobKeys ?? null }),
    streamUrl: (runId: string) => `/api/resumes/stream/${runId}`,
    list: () => get<ResumeSummary[]>('/api/resumes'),
    detail: (jobKey: string) => get<ResumeDetail>(`/api/resumes/${encodeURIComponent(jobKey)}`),
    pdfUrl: (jobKey: string) => `/api/resumes/${encodeURIComponent(jobKey)}/pdf`,
    feedback: (jobKey: string, feedback: string) =>
      post<ResumeDetail>(`/api/resumes/${encodeURIComponent(jobKey)}/feedback`, { feedback }),
    regen: (jobKey: string) => post<ResumeDetail>(`/api/resumes/${encodeURIComponent(jobKey)}/regen`),
    skip: (jobKey: string) => post<ResumeDetail>(`/api/resumes/${encodeURIComponent(jobKey)}/skip`),
    proceed: () => post<{ ok: boolean }>('/api/resumes/proceed'),
  },
  letters: {
    generate: (jobKeys?: string[]) => post<{ run_id: string }>('/api/letters/generate', { job_keys: jobKeys ?? null }),
    streamUrl: (runId: string) => `/api/letters/stream/${runId}`,
    list: () => get<LetterSummary[]>('/api/letters'),
    detail: (jobKey: string) => get<LetterDetail>(`/api/letters/${encodeURIComponent(jobKey)}`),
    feedback: (jobKey: string, feedback: string) =>
      post<LetterDetail>(`/api/letters/${encodeURIComponent(jobKey)}/feedback`, { feedback }),
    regen: (jobKey: string) => post<LetterDetail>(`/api/letters/${encodeURIComponent(jobKey)}/regen`),
    skip: (jobKey: string) => post<LetterDetail>(`/api/letters/${encodeURIComponent(jobKey)}/skip`),
    proceed: () => post<{ ok: boolean }>('/api/letters/proceed'),
  },
  contacts: {
    find: (jobKeys?: string[]) => post<{ run_id: string }>('/api/contacts/find', { job_keys: jobKeys ?? null }),
    streamUrl: (runId: string) => `/api/contacts/stream/${runId}`,
    list: () => get<ContactSummary[]>('/api/contacts'),
    refresh: (jobKey: string) => post<ContactSummary>(`/api/contacts/${encodeURIComponent(jobKey)}/refresh`),
    set: (jobKey: string, body: { name?: string; title?: string; email: string }) =>
      post<ContactSummary>(`/api/contacts/${encodeURIComponent(jobKey)}/set`, body),
    clear: (jobKey: string) => post<ContactSummary>(`/api/contacts/${encodeURIComponent(jobKey)}/clear`),
    proceed: () => post<{ ok: boolean }>('/api/contacts/proceed'),
  },
  apply: {
    start: (jobKeys?: string[], methods?: string[]) =>
      post<{ run_id: string }>('/api/apply/start', { job_keys: jobKeys ?? null, methods: methods ?? null }),
    streamUrl: (runId: string) => `/api/apply/stream/${runId}`,
    list: () => get<ApplySummary[]>('/api/apply'),
    pending: () => get<PendingManual[]>('/api/apply/pending'),
    resolve: (jobKey: string, applied: boolean) =>
      post<{ ok: boolean }>(`/api/apply/${encodeURIComponent(jobKey)}/resolve`, { applied }),
  },
}
