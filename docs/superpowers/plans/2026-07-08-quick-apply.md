# Quick Apply Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user paste a single LinkedIn job link on the Discovery screen and funnel that one job into the existing pipeline (ATS score → Resume → Cover Letter → Contacts → Apply), stopping at each existing review step.

**Architecture:** One new pure scraper (`scrape_single_job`) + one new SSE router (`quick_apply.py`) reusing the existing broker/browser_worker/run_state machinery. The frontend adds a paste box to the Discovery page that streams progress and shows a preview card; "Start Pipeline" reuses the existing `POST /api/jobs/select`, so nothing in the review/apply flow changes.

**Tech Stack:** Python 3.14, FastAPI, Playwright (via `browser_worker`), React/Vite/TypeScript, SSE.

## Global Constraints

- **Not a git repo** — there are NO commit steps. Each task ends by running its test/verification and confirming the result.
- **Tests are standalone scripts** run with `python <file>.py` from `M:/job-agent` with the venv active — the project has no pytest suite; match `test_e2e.py`'s PASS/FAIL-printing style.
- **Never launch a real browser or touch real state in a test.** Mock `browser_worker.start` + `.started` + `.submit` *together*; patch `DISCOVERED_JSON` and `run_state`'s `CURRENT_RUN_PATH`/`DISCOVERED_JSON` to temp paths. (Lessons: `feedback_job_agent`, `project_job_agent_webapp`.)
- **LinkedIn `/jobs/view/` links only.** Reject anything else with HTTP 400 before any work.
- **A pasted job is never silently dropped** — `scrape_single_job` skips the location allow-list, min-ATS, and unpaid filters. It still ATS-scores (score shown, not used to filter).
- **ThinkingBlock / encoding rules** unchanged — no new Claude calls in this feature.
- All backend commands assume cwd `M:/job-agent` with `env\Scripts\activate` (venv) active.

---

## File Structure

- **Create** `steps/step1_discover.py::scrape_single_job(...)` (new function in existing file).
- **Create** `backend/routers/quick_apply.py` — the SSE router.
- **Modify** `backend/schemas/jobs.py` — add `QuickApplyStartRequest`.
- **Modify** `backend/app.py` — register the router.
- **Modify** `frontend/src/api/client.ts` — add `api.quickApply`.
- **Modify** `frontend/src/types.ts` — extend `ProgressEvent` with `job` + `warning`.
- **Modify** `frontend/src/pages/DiscoveryPage.tsx` — paste box, SSE watch, preview card.
- **Create** `test_quick_apply.py` (repo root) — backend test script.

---

### Task 1: `scrape_single_job` scraper function

**Files:**
- Modify: `steps/step1_discover.py` (add function near `_scrape_linkedin`)
- Test: `test_quick_apply.py` (repo root)

**Interfaces:**
- Consumes: existing `_fetch_jd`, `_detect_work_type`, `_ats_score`, `_read_resume_text`, `cfg.JOB_PRIORITY`.
- Produces: `scrape_single_job(browser_context, url: str, on_progress=None) -> dict | None`. Returns a job dict shaped like a discovered job (`title, company, location, link, source, jd, posted_text, work_type, priority, ats`), or `None` if `url` lacks `/jobs/view/` or the page is unreadable.

- [ ] **Step 1: Write the failing test** — append to `test_quick_apply.py`:

```python
"""Standalone tests for the Quick Apply feature. Run: python test_quick_apply.py
No real browser, no real network, no real state files are touched."""
import sys
from unittest import mock

PASS, FAIL = "PASS", "FAIL"
results = []
def check(name, cond, note=""):
    results.append((name, cond))
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f" — {note}" if note else ""))

# ── Task 1: scrape_single_job ───────────────────────────────────────────────
from steps import step1_discover

def test_rejects_non_job_view_url():
    got = step1_discover.scrape_single_job(object(), "https://www.linkedin.com/feed/")
    check("rejects non /jobs/view/ url", got is None)

def test_scrapes_and_scores():
    # Fake Playwright page: a job-view DOM. We stub the extraction helpers the
    # function delegates to rather than simulating real selectors.
    with mock.patch.object(step1_discover, "_fetch_jd", return_value="We need SQL, Agile, JIRA. 2 years experience. Bachelor degree."), \
         mock.patch.object(step1_discover, "_read_resume_text", return_value="SQL Agile JIRA 3 years experience bachelor"), \
         mock.patch.object(step1_discover, "_extract_job_view_fields",
                           return_value={"title": "Business Analyst", "company": "Acme",
                                         "location": "Noida, India (Hybrid)", "posted_text": "2 days ago"}):
        job = step1_discover.scrape_single_job(object(), "https://www.linkedin.com/jobs/view/123456/")
    check("returns a job dict", isinstance(job, dict))
    check("job has link", job and job.get("link", "").endswith("/jobs/view/123456/"))
    check("job has work_type hybrid", job and job.get("work_type") == "hybrid")
    check("job is ATS scored", job and isinstance(job.get("ats"), dict) and job["ats"].get("score") is not None)

test_rejects_non_job_view_url()
test_scrapes_and_scores()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python test_quick_apply.py`
Expected: FAIL — `AttributeError: module 'steps.step1_discover' has no attribute 'scrape_single_job'` (or `_extract_job_view_fields`).

- [ ] **Step 3: Write minimal implementation** — add to `steps/step1_discover.py`:

```python
def _extract_job_view_fields(page) -> dict:
    """Extract title/company/location/posted from a LinkedIn job-VIEW page
    (different DOM from the search-results cards). Best-effort with fallbacks."""
    def _text(selectors):
        for sel in selectors:
            el = page.query_selector(sel)
            if el:
                t = el.inner_text().strip().split("\n")[0].strip()
                if t:
                    return t
        return ""

    title = _text([
        ".job-details-jobs-unified-top-card__job-title",
        ".job-details-jobs-unified-top-card__job-title h1",
        "h1",
    ])
    company = _text([
        ".job-details-jobs-unified-top-card__company-name a",
        ".job-details-jobs-unified-top-card__company-name",
        "a[href*='/company/']",
    ])
    location = _text([
        ".job-details-jobs-unified-top-card__primary-description-container span.tvm__text",
        ".job-details-jobs-unified-top-card__bullet",
        ".jobs-unified-top-card__bullet",
    ])
    posted = ""
    container = page.query_selector(".job-details-jobs-unified-top-card__primary-description-container")
    if container:
        blob = container.inner_text().lower()
        import re as _re
        m = _re.search(r"\b\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago\b", blob)
        if m:
            posted = m.group(0)
    return {"title": title or "Unknown", "company": company or "Unknown",
            "location": location, "posted_text": posted}


def scrape_single_job(browser_context, url: str, on_progress=None) -> dict | None:
    """Scrape ONE LinkedIn job-view URL into a discovered-job dict + ATS score.
    Unlike run_headless, it applies NO location/min-ATS/unpaid filters — the user
    pasted this job deliberately, so it must never be silently dropped."""
    import re

    def _progress(msg):
        console.print(msg)
        if on_progress:
            on_progress(msg)

    if not url or "/jobs/view/" not in url:
        return None

    page = browser_context.new_page()
    try:
        _progress("  Fetching job page...")
        page.goto(url, timeout=30000)
        page.wait_for_load_state("domcontentloaded")
        time.sleep(random.uniform(2, 3))

        fields = _extract_job_view_fields(page)
    except Exception as e:
        _progress(f"  [red]Could not load job page: {e}[/red]")
        page.close()
        return None
    else:
        page.close()

    if fields["title"] == "Unknown" and fields["company"] == "Unknown":
        return None

    _progress("  Reading job description...")
    jd = _fetch_jd(browser_context, url)

    location = fields["location"] or ""
    work_type = _detect_work_type(location) or "on-site"
    import config as cfg
    job = {
        "title": fields["title"],
        "company": fields["company"],
        "location": location,
        "link": url,
        "source": "linkedin",
        "jd": jd,
        "posted_text": fields["posted_text"],
        "work_type": work_type,
        "priority": cfg.JOB_PRIORITY.get(work_type, 0),
    }

    _progress("  Scoring against your resume (ATS)...")
    resume_text = _read_resume_text()
    job["ats"] = _ats_score(resume_text, job) if resume_text else {"score": None, "label": "No resume", "breakdown": {}}
    return job
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python test_quick_apply.py`
Expected: the 6 Task-1 checks print `PASS`.

- [ ] **Step 5: Checkpoint** — confirm no other file was changed; the existing `_scrape_linkedin` path is untouched.

---

### Task 2: Quick-apply schema + SSE router + wiring

**Files:**
- Modify: `backend/schemas/jobs.py`
- Create: `backend/routers/quick_apply.py`
- Modify: `backend/app.py:46-52`
- Test: `test_quick_apply.py`

**Interfaces:**
- Consumes: `step1_discover.scrape_single_job`, `browser_worker`, `broker`, `run_state`, `_save_discovered`, `discovery._job_to_out`, `get_job_statuses`, `get_title_company_statuses`.
- Produces: `POST /api/quick-apply/start` (body `{link}`) → `{run_id}`; `GET /api/quick-apply/stream/{run_id}` (SSE). The `done` event shape: `{"type":"done","job": <JobOut dict>, "warning": <str|None>}`.

- [ ] **Step 1: Write the failing test** — append to `test_quick_apply.py`:

```python
# ── Task 2: quick-apply router ──────────────────────────────────────────────
import json, tempfile, time as _time
from pathlib import Path

def test_router():
    from fastapi.testclient import TestClient
    tmp = Path(tempfile.mkdtemp())
    disc = tmp / "discovered_jobs.json"
    cur = tmp / "current_run.json"

    fake_job = {"title": "Business Analyst", "company": "Acme", "location": "Noida (Hybrid)",
                "link": "https://www.linkedin.com/jobs/view/123456/", "source": "linkedin",
                "jd": "SQL Agile", "posted_text": "2 days ago", "work_type": "hybrid",
                "priority": 2, "ats": {"score": 72, "label": "Good", "breakdown": {}}}

    from backend.services import run_state as rs_mod
    from backend.routers import quick_apply, discovery
    from backend.services.browser_worker import browser_worker

    with mock.patch.object(rs_mod, "CURRENT_RUN_PATH", cur), \
         mock.patch.object(rs_mod, "DISCOVERED_JSON", disc), \
         mock.patch.object(quick_apply, "DISCOVERED_JSON", disc), \
         mock.patch.object(quick_apply.step1_discover, "_save_discovered", lambda jobs: disc.write_text(json.dumps(jobs))), \
         mock.patch.object(browser_worker, "started", True), \
         mock.patch.object(browser_worker, "start", lambda: None), \
         mock.patch.object(browser_worker, "submit", lambda fn: fake_job), \
         mock.patch.object(quick_apply, "get_job_statuses", lambda: {}), \
         mock.patch.object(quick_apply, "get_title_company_statuses", lambda: {}):

        from backend.app import app
        client = TestClient(app)

        bad = client.post("/api/quick-apply/start", json={"link": "https://example.com/foo"})
        check("bad link -> 400", bad.status_code == 400, f"got {bad.status_code}")

        good = client.post("/api/quick-apply/start", json={"link": fake_job["link"]})
        check("good link -> 200 run_id", good.status_code == 200 and "run_id" in good.json())
        run_id = good.json()["run_id"]

        # Drain the SSE stream (TestClient streams synchronously)
        events, deadline = [], _time.time() + 10
        with client.stream("GET", f"/api/quick-apply/stream/{run_id}") as resp:
            for line in resp.iter_lines():
                if _time.time() > deadline:
                    break
                if line and line.startswith("data:"):
                    ev = json.loads(line[5:].strip())
                    events.append(ev)
                    if ev.get("type") in ("done", "error"):
                        break
        done = next((e for e in events if e.get("type") == "done"), None)
        check("stream yields done event", done is not None)
        check("done carries the job", bool(done) and done.get("job", {}).get("company") == "Acme")
        check("done carries no warning for fresh job", bool(done) and done.get("warning") in (None, ""))

test_router()

print()
n_fail = sum(1 for _, ok in results if not ok)
print(f"{'ALL PASS' if n_fail == 0 else str(n_fail) + ' FAILED'} ({len(results)} checks)")
sys.exit(1 if n_fail else 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python test_quick_apply.py`
Expected: FAIL — `404` on `/api/quick-apply/start` (router not registered yet).

- [ ] **Step 3a: Add the schema** — append to `backend/schemas/jobs.py`:

```python
class QuickApplyStartRequest(BaseModel):
    link: str
```

- [ ] **Step 3b: Create `backend/routers/quick_apply.py`:**

```python
import re
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from steps import step1_discover
from steps.step1_discover import _job_key
from steps.step_excel import get_job_statuses, get_title_company_statuses

from backend.schemas.jobs import QuickApplyStartRequest, RunIdResponse
from backend.routers.discovery import _job_to_out
from backend.services.run_state import run_state
from backend.services.sse import broker, strip_rich_markup, parse_last_event_id
from backend.services.browser_worker import browser_worker

router = APIRouter(prefix="/api/quick-apply", tags=["quick-apply"])

DISCOVERED_JSON = Path("data/discovered_jobs.json")

_JOB_VIEW_RE = re.compile(r"linkedin\.com/jobs/view/\d+", re.IGNORECASE)


def _warning_for(job: dict) -> str | None:
    """Warn (but don't block) if this job is already in the tracker."""
    skip = {"Applied", "Rejected"}
    key = _job_key(job)
    tc = (job.get("title", "").strip().lower(), job.get("company", "").strip().lower())
    status = get_job_statuses().get(key) or get_title_company_statuses().get(tc)
    if status in skip:
        return f"You already marked this job {status} in a previous run."
    if DISCOVERED_JSON.exists():
        try:
            import json
            existing = {_job_key(j) for j in json.loads(DISCOVERED_JSON.read_text(encoding="utf-8"))}
            if key in existing:
                return "This job is already in your discovered list."
        except Exception:
            pass
    return None


def _quick_apply_worker(run_id: str, link: str):
    def on_progress(msg: str):
        broker.publish(run_id, {"type": "log", "message": strip_rich_markup(msg)})

    try:
        if not browser_worker.started:
            broker.publish(run_id, {"type": "log", "message": "Launching browser and logging into LinkedIn..."})
            browser_worker.start()
        job = browser_worker.submit(
            lambda: step1_discover.scrape_single_job(browser_worker.context, link, on_progress)
        )
        if not job:
            broker.finish(run_id, {"type": "error",
                                   "message": "Couldn't read that job — check the link is a public LinkedIn job posting."})
            return
        warning = _warning_for(job)
        step1_discover._save_discovered([job])
        run_state.set_jobs([job])
        run_state.stage = "selecting"
        run_state.save()
        broker.finish(run_id, {"type": "done", "job": _job_to_out(job), "warning": warning})
    except Exception as e:
        broker.finish(run_id, {"type": "error", "message": str(e)})


@router.post("/start", response_model=RunIdResponse)
def start_quick_apply(body: QuickApplyStartRequest):
    link = (body.link or "").strip()
    if not _JOB_VIEW_RE.search(link):
        raise HTTPException(400, "Not a LinkedIn job link. Paste a linkedin.com/jobs/view/... URL.")
    run_id = broker.new_run()
    threading.Thread(target=_quick_apply_worker, args=(run_id, link), daemon=True).start()
    return {"run_id": run_id}


@router.get("/stream/{run_id}")
async def stream_quick_apply(run_id: str, request: Request):
    last_event_id = parse_last_event_id(request.headers.get("last-event-id"))
    return StreamingResponse(broker.stream(run_id, last_event_id), media_type="text/event-stream")
```

- [ ] **Step 3c: Register the router** — in `backend/app.py`, update the import on line 17 and add an include:

```python
from backend.routers import discovery, resumes, coverletters, contacts, apply, status, quick_apply
```
```python
app.include_router(quick_apply.router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python test_quick_apply.py`
Expected: final line `ALL PASS (N checks)`.

- [ ] **Step 5: Checkpoint** — confirm the temp-dir patches held: the real `data/discovered_jobs.json` and `data/web_state/current_run.json` mtimes are unchanged (the test wrote only to its tempdir).

---

### Task 3: Frontend API client + types

**Files:**
- Modify: `frontend/src/api/client.ts:31-92`
- Modify: `frontend/src/types.ts:118-134`

**Interfaces:**
- Produces: `api.quickApply.start(link)` → `{run_id}`; `api.quickApply.streamUrl(runId)`. `ProgressEvent` gains optional `job?: Job` and `warning?: string | null`.

- [ ] **Step 1: Extend `ProgressEvent`** — in `frontend/src/types.ts`, add two fields to the `ProgressEvent` interface (after `methods_failed`):

```typescript
  job?: Job
  warning?: string | null
```

- [ ] **Step 2: Add the API client block** — in `frontend/src/api/client.ts`, add inside the `api` object (after the `discovery` block):

```typescript
  quickApply: {
    start: (link: string) => post<{ run_id: string }>('/api/quick-apply/start', { link }),
    streamUrl: (runId: string) => `/api/quick-apply/stream/${runId}`,
  },
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run build`
Expected: build succeeds (TypeScript compiles with no errors). If `npm run build` is slow, `npx tsc --noEmit` is enough.

- [ ] **Step 4: Checkpoint** — no runtime change yet; this task only adds types + a client method.

---

### Task 4: Frontend Quick-Apply UI on the Discovery page

**Files:**
- Modify: `frontend/src/pages/DiscoveryPage.tsx`

**Interfaces:**
- Consumes: `api.quickApply.start/streamUrl`, `api.jobs.select`, `useSSE`, `LogConsole`, `InlineLoading`, the `onProceed` prop (already routes to Resume Review), `ProgressEvent.job`/`warning`.

- [ ] **Step 1: Add quick-apply state + second SSE subscription** — near the other `useState`/`useSSE` calls in `DiscoveryPage`:

```typescript
  const [quickLink, setQuickLink] = useState('')
  const [quickRunId, setQuickRunId] = useState<string | null>(null)
  const [quickErr, setQuickErr] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)

  const quick = useSSE(quickRunId ? api.quickApply.streamUrl(quickRunId) : null)
  const quickDoneEvent = quick.messages.find((m) => m.type === 'done')
  const quickJob = quickDoneEvent?.job ?? null
  const quickWarning = quickDoneEvent?.warning ?? null
  const quickBusy = quickRunId !== null && !quick.done && !quick.error
```

- [ ] **Step 2: Add the handlers:**

```typescript
  const startQuickApply = async () => {
    setQuickErr(null)
    const link = quickLink.trim()
    if (!link) return
    setStarting(true)
    try {
      const { run_id } = await api.quickApply.start(link)
      setQuickRunId(run_id)
    } catch (e) {
      setQuickErr(e instanceof Error ? e.message : 'Failed to start')
    } finally {
      setStarting(false)
    }
  }

  const startPipelineForQuickJob = async () => {
    if (!quickJob) return
    setSubmitting(true)
    try {
      await api.jobs.select([quickJob.job_key])
      onProceed()
    } finally {
      setSubmitting(false)
    }
  }

  const cancelQuickApply = () => {
    setQuickRunId(null)
    setQuickLink('')
    setQuickErr(null)
  }
```

- [ ] **Step 3: Add the UI panel** — insert as the FIRST `.panel` inside the returned `<div className="stack">` (above the `Job Discovery` panel):

```tsx
      <div className="panel">
        <h2>Quick Apply — paste a LinkedIn job link</h2>
        <div className="row">
          <input
            type="text"
            placeholder="https://www.linkedin.com/jobs/view/..."
            value={quickLink}
            onChange={(e) => setQuickLink(e.target.value)}
            disabled={quickBusy || !!quickJob}
          />
          <button className="primary" onClick={startQuickApply} disabled={quickBusy || starting || !!quickJob || !quickLink.trim()}>
            {quickBusy ? 'Working…' : 'Quick Apply'}
          </button>
        </div>
        {quickErr && <p className="error-text">{quickErr}</p>}

        {quickRunId && !quickJob && (
          <div style={{ marginTop: 12 }}>
            <LogConsole messages={quick.messages} />
            {quick.error && <p className="error-text">{quick.error}</p>}
          </div>
        )}

        {quickJob && (
          <div className="panel" style={{ marginTop: 12 }}>
            {quickWarning && <p className="warn-text">⚠ {quickWarning}</p>}
            <h3>{quickJob.title} — {quickJob.company}</h3>
            <p className="muted">{quickJob.location} · {quickJob.work_type ?? 'unknown'}</p>
            <p>
              ATS score:{' '}
              {quickJob.ats?.score != null
                ? <strong>{quickJob.ats.score}% {quickJob.ats.label}</strong>
                : <span className="muted">no score (JD/resume unavailable)</span>}
            </p>
            <div className="row" style={{ marginTop: 8 }}>
              <button className="primary" onClick={startPipelineForQuickJob} disabled={submitting}>
                {submitting ? 'Starting…' : 'Start Pipeline →'}
              </button>
              <button onClick={cancelQuickApply} disabled={submitting}>Cancel</button>
            </div>
          </div>
        )}
      </div>
```

- [ ] **Step 4: Add a `.warn-text` style if absent** — check `frontend/src/index.css` for `.warn-text`; if it doesn't exist, add:

```css
.warn-text { color: var(--warn, #e0a800); margin: 0 0 8px; }
```

(If a warning/amber class already exists, reuse it instead of adding a duplicate.)

- [ ] **Step 5: Typecheck + build**

Run: `cd frontend && npm run build`
Expected: compiles with no errors.

- [ ] **Step 6: Checkpoint** — visual verification deferred to Task 5 (needs the running app).

---

### Task 5: End-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Backend regression** — confirm the feature is purely additive:

Run: `python test_e2e.py`
Expected: all existing steps still `PASS`.

Run: `python test_quick_apply.py`
Expected: `ALL PASS`.

- [ ] **Step 2: Live drive (browser)** — start the app (`agent-vinod-web.bat`) or the two dev servers, open `http://localhost:5173`, and on the Discovery screen:
  1. Paste a real `linkedin.com/jobs/view/...` link → Quick Apply.
  2. Confirm live progress logs appear ("Fetching job… / Scoring…").
  3. Confirm the preview card shows title/company/location + ATS score.
  4. Paste a non-LinkedIn URL → confirm the inline 400 error ("Not a LinkedIn job link").
  5. Click **Start Pipeline** → confirm it lands on Resume Review for that one job and the rest of the pipeline behaves normally.

- [ ] **Step 3: Duplicate warning** — re-paste a link for a job already marked Applied/Rejected in the tracker → confirm the amber warning shows but Start Pipeline is still enabled.

- [ ] **Step 4: Opus review** — per the standing project rule, dispatch an Opus code review (`Agent`, `model: opus`) over the new/changed files, fix findings, then report.

---

## Self-Review

**Spec coverage:**
- LinkedIn-only + 400 on bad link → Task 2 (`_JOB_VIEW_RE`, `start_quick_apply`). ✓
- ATS score / scrape one job, skip filters → Task 1 (`scrape_single_job`). ✓
- Warn-but-allow duplicates → Task 2 (`_warning_for`), Task 4 (warning banner, Start Pipeline stays enabled). ✓
- SSE progress + preview card → Task 2 (stream), Task 4 (LogConsole + card). ✓
- Reuse `/api/jobs/select`, drop into Resume Review → Task 4 (`startPipelineForQuickJob` → `onProceed`). ✓
- No new state-retention for the fetch step → not implemented (by design); the select step onward is already retained. ✓
- Never touch real state/browser in tests → Global Constraints + Task 2 patches. ✓

**Placeholder scan:** none — every code step shows complete code.

**Type consistency:** `scrape_single_job(browser_context, url, on_progress=None)` used identically in Task 1 and Task 2's worker; `done` event `{type, job, warning}` matches the `ProgressEvent` extension (Task 3) and the reader in Task 4; `api.quickApply.start/streamUrl` defined in Task 3 and consumed in Task 4.
