# Agent Vinod — Project Context

Job-application automation tool for Paarth Agarwal (BA/PM/PO roles, India, remote/hybrid). Discovers LinkedIn postings, scores them against his resume, tailors a resume + cover letter per job via Claude, finds an HR/recruiter contact, and sends the application (email or LinkedIn Easy Apply).

**Two interfaces to the same pipeline**, sharing all business logic in `steps/`:
1. **CLI** (`main.py`) — original, fully working, terminal-based.
2. **Web app** (`backend/` + `frontend/`) — FastAPI + React/Vite, built to replace the terminal UI. **Milestones 1 and 2 are done. Milestone 3 is not built.**

Run the CLI: `agent-vinod.bat`. Run the web app: `agent-vinod-web.bat` (opens backend on `:8000` and frontend on `:5173` in separate windows — use `localhost:5173` in the browser, not `127.0.0.1`, since Vite only binds IPv6 `[::1]` on this machine). Test the CLI: `python test_e2e.py`.

---

## Web app status

### Milestone 1 (done) — Discovery, Resume tailoring, Cover letters
- Discovery page: search form (titles/locations/work-types/max-jobs/min-ATS-score, all editable per run, pre-filled from `.env`), a **"Suggest roles from my resume"** button (one Claude call reads the resume and suggests titles matched to actual seniority — don't suggest senior/VP roles for an entry-level resume), live SSE progress log, results table with checkboxes + a **Reject** button per row (marks `Rejected` in the Excel tracker).
- Resume/Cover-Letter Review pages: **batch-then-review** pattern — tailor/generate everything first (no per-job blocking prompts), then a summary table where you click any job (tailored or not, even mid-batch) to see a diff + ATS/keyword score + a chat box to refine/regenerate/skip. A **"Preview PDF"** button opens the actual generated file. Only untailored/ungenerated jobs are processed by default ("Tailor/Generate N remaining"); "Re-tailor/Re-generate all" is a separate explicit action.
- Every page resumes an in-progress batch after you navigate away and back or reload — the backend tracks "is a batch currently running" per stage (`active_discovery_run_id`, `active_resume_run_id`, etc. on the `RunState` singleton, exposed via `GET /api/status`), and the frontend reconnects to the SSE stream on mount instead of losing the live view.
- A loading indicator (`> {text}█`, blinking cursor) shows for every async wait in the app — job detail fetches, chat feedback, "Suggest from resume," "Use previously found jobs," Reject, Proceed/Accept buttons, the initial app load.

### Milestone 2 (done) — Contacts + Apply
- Contacts page: batch-finds HR/recruiter/talent-acquisition/leadership contacts (Hunter.io → Apollo.io → SMTP-verify permutation guessing) for selected jobs. **Never auto-fills a contact whose title doesn't match** — if nothing is found, you can manually type one in (or leave it, and that job will just skip the email method during Apply).
- Apply page: **one confirmation for the whole batch** (`window.confirm()`) before sending. Email first if a contact was found, else LinkedIn Easy Apply if it's a LinkedIn posting. If Easy Apply can't finish automatically, the browser window stays open on that job and the page shows a "needs manual apply" card with Mark-Applied/Skip buttons (replaces the CLI's blocking terminal `input()` — implemented via an SSE `needs_manual_apply` event + a `threading.Event` the resolve endpoint sets).
- Fixed after an Opus review: re-clicking "Send" no longer re-applies to already-applied jobs; contacts and application results now survive a backend restart (previously in-memory only); a locked `job_tracker.xlsx` no longer aborts a batch after real emails already went out; SSE no longer double-delivers events published just before a client connects.

### Milestone 3 (not built) — Tracker/analytics dashboard
Read-only views over `job_tracker.xlsx` and `applications.csv/json` — applications-over-time, ATS distribution, status breakdown, by-company table. Low risk, no business-logic changes expected. This is the natural next thing to build.

---

## Architecture

```
config.py, main.py, steps/*.py, data/     ← CLI, unchanged in spirit; steps/ functions reused directly by the backend
backend/
  app.py                    FastAPI app; lifespan scans data/*.docx for cfg.RESUME_DOCX_PATH
  routers/                  discovery, resumes, coverletters, contacts, apply, status
  services/
    run_state.py             RunState singleton — current job list + stage + active-run tracking; persists to data/web_state/current_run.json
    sse.py                   ProgressBroker — SSE queue + ring buffer per run_id, sequence-numbered to avoid double delivery
    browser_worker.py        Single dedicated thread owning the one headed Playwright browser (Playwright isn't thread-safe) — starts lazily on first discovery/apply request
    claude_client.py         Lazy singleton anthropic.Anthropic client
    diffing.py                JSON-friendly diff builder (mirrors the CLI's Rich diff rendering)
    thread_safety.py          com_initialized() — needed because docx2pdf/Word-COM requires per-thread CoInitialize, and CLI never hit this (always ran on the main thread)
    title_suggester.py        One Claude call: resume + current titles → suggested search titles
  schemas/                   Pydantic request/response models, one file per router
frontend/src/
  App.tsx, types.ts
  api/client.ts              One typed wrapper per endpoint; every GET uses cache:'no-store' + a cache-busting query param
  hooks/useSSE.ts             EventSource wrapper
  pages/                      DiscoveryPage, ResumeReviewPage, CoverLetterReviewPage, ContactsPage, ApplyPage
  components/                 JobTable, DiffView, AtsPanel, ChatBox, LogConsole, StatusPill, Stepper, InlineLoading, DiscoveryActiveBanner
```

**Design principle carried through both milestones**: the backend imports and calls the existing pure `steps/*.py` functions directly (`_tailor`, `_apply_feedback`, `_ats_score`, `_generate`, `_hunter_search`, `_send_email`, `_linkedin_easy_apply`, etc.) rather than duplicating business logic. Only a few small, additive changes were made to `steps/`, always preserving the CLI's existing behavior:
- `step1_discover.py` — added `run_headless()` (same pipeline minus the interactive prompts); `run()` now delegates to it.
- `step5_apply.py` — `_linkedin_easy_apply`/`_manual_apply_fallback` gained an optional `on_wait=None` callback param; `None` (CLI default) preserves the exact original blocking-`input()` behavior.
- `step2_resume.py`/`step3_coverletter.py` — output filenames now include an 8-char hash of the job key, to prevent same-company+title collisions.
- `step4_contacts.py` — `_hunter_search`/`_apollo_search` no longer fall back to "the first email found" if no HR/recruiter title matches; they return `None` instead (**never email a random employee**).
- `browser_session.py` (new file) — `_linkedin_login`/`_browser_context_no_login` extracted out of `main.py`, shared by both the CLI and the backend.
- `config.py` — added `MIN_ATS_SCORE` (default 50).

---

## Discovery now paginates until it hits your target job count (2026-07-11/12)

`run_headless` (`steps/step1_discover.py`) used to take one pass over every title×location combo and return whatever survived filters — often well short of `max_jobs`. It now round-robins LinkedIn's `&start=N` pagination across every combo (all combos' page 1 first, then page 2, etc.) until enough suitable jobs survive every filter, or every combo is genuinely exhausted (a page returns **zero** cards, not just "fewer than a full page" — see below), or a hard safety cap is hit (`MAX_PAGES_PER_COMBO=4`, `MAX_TOTAL_PAGE_LOADS=40`). Falling short of the target is always reported explicitly in the progress log, never silent.

**Real bug found while verifying this live, worth knowing if search results ever look capped again**: LinkedIn's job list renders inside its own scrollable side-panel with an **obfuscated, build-specific class name** — not a stable selector, and not the outer window. A single `window.scrollTo` never touched it, so every fetch (regardless of title/location, before this fix existed at all) rendered only the ~7 cards that fit that panel's initial viewport. Fixed by scrolling *every* element on the page whose `scrollHeight - clientHeight > 50` (brute-force, not a guessed selector) — confirmed live to actually grow the rendered count, and confirmed `start=25` returns a fully distinct, zero-overlap batch of new jobs (i.e. LinkedIn's pagination itself works fine; the scraper just wasn't rendering a full page before paging). Live-verified end to end: real `.env` defaults, `max_jobs=20` → exactly 20/20 returned.

This same live run also confirmed the 2026-07-09 location-alias fix (`_LOCATION_ALIASES` in `_normalize_location` — the `.env` defaults `"New Delhi India"` / `"Noida Uttar Pradesh India"` resolve to correct comma-separated LinkedIn locations) actually works against real LinkedIn, not just in a unit check.

---

## Critical non-obvious facts (don't relearn these the hard way)

- **`.env`'s `GEMINI_API_KEY` field holds the real Anthropic/Claude key** (legacy name, `sk-ant-...` value) — `config.py` reads it as `cfg.GEMINI_API_KEY`. Don't rename the field.
- **`claude-sonnet-5` returns a `ThinkingBlock` before the `TextBlock`** — always extract via `next((b.text for b in message.content if hasattr(b, "text")), "")`, never `message.content[0].text`.
- **All `steps/*.py` code uses relative paths** (`Path("data/...")`) — the backend MUST run with cwd = `M:/job-agent`, or every reused function silently reads/writes the wrong location. `agent-vinod-web.bat` handles this.
- **`uvicorn --reload` is scoped to `--reload-dir backend --reload-dir steps`** — if it watched the whole cwd, routine writes to `data/discovered_jobs.json`/debug screenshots would trigger a restart mid-scrape, killing the in-progress Playwright browser.
- **Vite only binds `[::1]` (IPv6) on this machine** — use `localhost:5173`, not `127.0.0.1:5173`, when checking if the dev server is up.
- **`docx2pdf` (Word-COM) needs `pythoncom.CoInitialize()` per thread** — the CLI never hit this (always ran on the main thread); the backend wraps every `_save_resume`/`_save_letter` call site in `thread_safety.com_initialized()`.
- **A backend restart kills the headed Playwright browser and any in-flight scrape/apply** — there's no way around this; `RunState` only persists what can be meaningfully reconstructed from disk (job metadata, tailored text, contacts, application results), not an in-progress browser session.
- **Gmail App Password needs `.strip().replace(" ", "")`** before SMTP login (Google displays it with spaces).
- **Never let contact search fall back to a random employee** — HR/recruiter/talent-acquisition/leadership titles only; if none found, no auto-contact, full stop.

## Testing gotchas — if you write a test against the backend

`TestClient`/a fresh Python process is **not filesystem-isolated** from the user's real, currently-running backend — they share the same on-disk files. Before running any test that mutates state:
1. Check if the user's own server is live (`netstat`/`curl` its port) — if so, be extra careful.
2. Monkeypatch every path constant a test might touch: `backend.services.run_state.CURRENT_RUN_PATH` / `DISCOVERED_JSON`, `backend.routers.discovery.DISCOVERED_JSON`, and — easy to forget — `steps.step6_track.CSV_PATH` / `JSON_PATH` if exercising the apply flow. None currently accept a parameter override.
3. Mock `backend.services.browser_worker.browser_worker.start` (→ `None`) and `.started` (→ `True`) together with `.submit` — `.start()` really launches a headed Chromium + attempts a real LinkedIn login if you forget.
4. Patch functions where they're **imported into**, not where they're defined — e.g. `backend.routers.apply._linkedin_easy_apply`, not `steps.step5_apply._linkedin_easy_apply` (the router does `from steps.step5_apply import _linkedin_easy_apply`, which binds a separate local reference).

`test_e2e.py` (the CLI's own test) mocks `_gemini_call`, `_send_email`, `_linkedin_easy_apply`, `Confirm.ask`, `Prompt.ask` per step module, and does real (unmocked) LinkedIn scraping — nothing in the web app work has changed its behavior.
