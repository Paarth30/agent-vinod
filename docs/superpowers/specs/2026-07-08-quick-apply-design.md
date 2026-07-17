# Quick Apply — paste a link, run the whole pipeline

**Date:** 2026-07-08
**Status:** Approved (design), pending implementation

## Goal

Let the user paste a single LinkedIn job link on the Discovery screen and funnel that one job straight into the existing pipeline — ATS score → Resume → Cover Letter → Contacts → Apply — stopping at each existing review step exactly as a normally-discovered job does. No autonomous applying; the user keeps per-step approval.

## Scope decisions (locked in during brainstorming)

- **Flow:** Stop at each existing review step. Quick Apply only *injects* one job into the pipeline and drops the user at Resume Review; the review/apply flow itself is unchanged.
- **Link scope:** LinkedIn `/jobs/view/...` URLs only. Anything else → clear "not supported / not a LinkedIn job link" error.
- **Duplicate handling:** Warn but allow. If the job is already in the tracker (discovered, or marked Applied/Rejected), show a notice but let the user proceed anyway.
- **Filters deliberately skipped for a pasted job:** location allow-list (`JOB_LOCATION_RULES`), min-ATS threshold, and the unpaid-internship heuristic are NOT applied — the user pasted this job on purpose, so it must never be silently dropped. It is still ATS-scored (the score is shown, not used to filter).
- **No cross-navigation state-retention for the fetch step** — it's a seconds-long operation; navigating away mid-fetch just means re-pasting. Once the user hits "Start Pipeline", they are in the normal (fully state-retained) flow.
- **Final visual styling** of the paste box comes with the separate UI-redesign work; this spec places it functionally on the Discovery screen.

## User-facing flow

1. Discovery screen shows a prominent **"Have a specific job? Paste LinkedIn link"** input + **Quick Apply** button, above/beside the existing search form.
2. User pastes `https://www.linkedin.com/jobs/view/<id>/...` → clicks Quick Apply.
3. Live SSE progress (same `LogConsole` pattern as discovery): "Logging into LinkedIn… / Fetching job… / Scoring against your resume…".
4. **Preview card** appears:
   - Title / Company / Location / work-type.
   - ATS score pill + breakdown (reuses `AtsPanel`-style display or a compact inline version).
   - If the job is already in the tracker: an amber warning banner, e.g. `⚠ You already applied to this on 2026-07-03` / `⚠ Already in your discovered list`.
   - Buttons: **Start Pipeline →** and **Cancel**.
5. **Start Pipeline** → commits this single job as the selection and routes to Resume Review (`stage = tailoring_resumes`). From here everything is the existing flow.
6. **Cancel** → discard, return to the Discovery form.

## Backend

### New: `steps/step1_discover.py::scrape_single_job(browser_context, url, on_progress=None) -> dict | None`
- Validates `url` contains `/jobs/view/`; returns `None` (caller maps to an error) if not.
- Navigates to the job-view page (single navigation). Extracts, with fallback selectors:
  - **title** — `.job-details-jobs-unified-top-card__job-title`, `h1`, …
  - **company** — `.job-details-jobs-unified-top-card__company-name a`, `.job-details-jobs-unified-top-card__company-name`, …
  - **location / work-type** — primary-description container / tertiary text; run through `_detect_work_type`.
  - **JD** — reuse `_fetch_jd`-style extraction (expand "show more", try the JD selectors). Since we're already on the page, extract inline rather than a second navigation.
- Assigns `work_type = _detect_work_type(location) or "on-site"` and `priority` from `cfg.JOB_PRIORITY` (same as `_filter_and_prioritize`), but does **not** run the location allow-list / min-ATS / unpaid filters.
- ATS-scores via `_ats_score(_read_resume_text(), job)`.
- Returns a job dict shaped exactly like a discovered job (`title, company, location, link, source="linkedin", jd, posted_text, work_type, priority, ats`).
- Calls `on_progress(msg)` at each stage for SSE, mirroring `run_headless`.

### New: `backend/routers/quick_apply.py` (prefix `/api/quick-apply`)
- `POST /start` — body `QuickApplyStartRequest {link: str}`.
  - Rejects non-LinkedIn / non-`/jobs/view/` links with HTTP 400 before spawning any work.
  - Returns `{run_id}`; spawns a daemon worker thread (same shape as `_discovery_worker`).
- Worker:
  1. `browser_worker.start()` if not started (publishes "Launching browser and logging into LinkedIn…").
  2. `job = browser_worker.submit(lambda: scrape_single_job(browser_worker.context, link, on_progress))`.
  3. If `job is None` → `broker.finish(run_id, {"type": "error", "message": "Couldn't read that job — check the link is a public LinkedIn job posting."})`.
  4. Else:
     - Compute duplicate warning via `get_job_statuses()` (by `_job_key`) and `get_title_company_statuses()` (by title+company). Applied/Rejected → "already applied/rejected"; otherwise present in `discovered_jobs.json` → "already in discovered list".
     - `_save_discovered([job])` (append to `discovered_jobs.json`), `run_state.set_jobs([job])`, `run_state.stage = "selecting"`, `run_state.save()`.
     - `broker.finish(run_id, {"type": "done", "job": _job_to_out(job), "warning": <str|None>})`.
- `GET /stream/{run_id}` — SSE with `Last-Event-ID` support (same as the other 5 stream endpoints).
- **Start Pipeline reuses the existing `POST /api/jobs/select`** with `job_keys=[job_key]` — no new commit endpoint. That already sets `stage = tailoring_resumes` and `run_state.replace_jobs`.

### Schema — `backend/schemas/jobs.py`
- Add `class QuickApplyStartRequest(BaseModel): link: str`.

### Wiring
- Register the new router in `backend/app.py` alongside the others.

## Frontend

- **Discovery page** (`pages/DiscoveryPage.tsx`): add a Quick-Apply section — link `<input>` + button. On submit: `POST /api/quick-apply/start` → `useSSE` on the returned `run_id` → `LogConsole` for live progress.
- On the terminal `done` event: render a **preview card** (reuse `StatusPill`/`AtsPanel` where practical) with the job details, ATS score/breakdown, optional warning banner, and Start Pipeline / Cancel buttons.
- **Start Pipeline** → `POST /api/jobs/select {job_keys:[job.job_key]}` → on success, App-level stage becomes `tailoring_resumes` (existing `/api/status`-driven routing takes the user to Resume Review). Show `InlineLoading` ("Starting…") while the select call is in flight.
- **Cancel** → clear local quick-apply state, back to the form.
- `api/client.ts`: add `quickApplyStart(link)` and reuse existing `selectJobs`. All GETs keep the existing `cache:'no-store'` + cache-buster convention.
- `types.ts`: add the quick-apply done-event payload shape.

## Error handling

- Non-LinkedIn link → 400 from `/start`, shown inline under the input (no SSE run started).
- Job page unreadable (login wall, deleted posting, selectors miss) → SSE `error` event, shown in the LogConsole / an error banner; user can retry or edit the link.
- Locked `job_tracker.xlsx` etc. is not touched in this flow until Start Pipeline → the existing (already try/except-wrapped) paths handle it.

## Testing

- Unit-test `scrape_single_job` URL validation (`/jobs/view/` required) with a mocked page/context — no real browser, no real navigation (per the "never launch a real Chromium / never touch shared state in tests" lessons).
- Router test for `/api/quick-apply/start`: mock `browser_worker.start`/`.started`/`.submit` **together** and `scrape_single_job`; assert 400 on a bad link, and a `done` event carrying the job + correct warning on a good one. Patch `DISCOVERED_JSON` / `run_state` paths to temp files so the user's real `discovered_jobs.json` / `current_run.json` are never clobbered.
- Confirm the existing `test_e2e.py` still passes unchanged (this feature is purely additive).

## Non-goals

- No non-LinkedIn URL support.
- No autonomous end-to-end applying (final apply still goes through the existing Apply page + its per-batch confirm).
- No new persistence/state-retention machinery for the fetch step.

## Post-implementation

Per the standing project rule: implement → dispatch an Opus review (Agent tool, `model: opus`) → fix findings → report.
