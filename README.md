# Agent Vinod — Job Application Agent

Automates the tedious parts of a job search on LinkedIn: discovers postings that match your criteria, scores them against your resume, tailors a resume and cover letter per job with Claude, finds an HR/recruiter contact, and sends the application (email or LinkedIn Easy Apply) — while you review and approve along the way.

Two interfaces, one shared pipeline:
- **CLI** (`main.py`) — terminal-based, fully interactive.
- **Web app** (`backend/` + `frontend/`) — FastAPI + React, a browser UI over the same pipeline with live progress and a review/approve flow at each stage.

> **Disclaimer**: This automates actions on LinkedIn (scraping search results, driving Easy Apply) which may be against LinkedIn's Terms of Service. Use at your own risk, on your own account, at a reasonable pace. This is a personal-use tool, not a mass-spam bot — it's built around reviewing and approving your own applications, not blasting hundreds of companies unattended.

---

## How it works

1. **Discover** — searches LinkedIn for your configured job titles × locations × work types, scores each posting against your resume (skills, keywords, experience, education, title match), filters out duplicates/unpaid internships/mismatched titles, and ranks by priority + location rules.
2. **Tailor resume** — Claude rewrites your resume per job to better match the description, with an ATS score before/after and a diff/chat loop to refine it.
3. **Cover letter** — Claude drafts a short, keyword-scored cover letter per job, same refine loop.
4. **Find contact** — looks up an HR/recruiter/talent-acquisition contact at the company (Hunter.io → Apollo.io → permutation-guess + SMTP verify). Never falls back to a random employee — if no matching contact is found, that job just skips the email method.
5. **Apply** — emails the tailored resume + cover letter to the contact if one was found, otherwise attempts LinkedIn Easy Apply. If Easy Apply can't finish automatically (e.g. a custom screening question), the browser stays open on that job for you to finish by hand.
6. **Track** — everything is logged to an Excel tracker (`data/job_tracker.xlsx`) and a CSV/JSON application log.

---

## Prerequisites

- **Python 3.11+** (developed on 3.14)
- **Node.js 20+** and npm (only needed for the web app's frontend)
- **Google Chrome/Chromium** — installed automatically by Playwright's install step below
- **Microsoft Word** (Windows or macOS) — required for PDF conversion of tailored resumes (`docx2pdf` drives Word via COM/AppleScript). On Linux, PDF conversion isn't supported by this library; the `.docx` is still generated and emailed fine, but you'd need to adapt `step2_resume.py`'s PDF step (e.g. swap in LibreOffice's `soffice --headless --convert-to pdf`) to get PDFs there.
- A **LinkedIn account** (used for scraping + Easy Apply — runs in a visible, non-headless browser window since LinkedIn may require you to approve a login/2FA checkpoint on your phone the first time)
- An **Anthropic API key** (for resume/cover-letter generation) — see the naming gotcha below
- Optional: **Hunter.io** and/or **Apollo.io** API keys (contact finding — the tool still works without these, just with fewer contacts found)
- A **Gmail account with an App Password** (for sending applications by email) — regular passwords won't work; generate one at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) (requires 2FA enabled on the Google account)

**⚠️ Naming gotcha**: the `.env` variable is called `GEMINI_API_KEY` for historical reasons, but it actually holds your **Anthropic (Claude)** API key (`sk-ant-...`), not a Google Gemini key. Get one from [console.anthropic.com](https://console.anthropic.com/).

---

## Setup

### 1. Clone and set up Python

```bash
git clone <your-repo-url>
cd job-agent

python -m venv env
# Windows:
env\Scripts\activate
# macOS/Linux:
source env/bin/activate

pip install -r requirements.txt
playwright install chromium
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your values:

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Yes | Your **Anthropic** API key (see gotcha above) |
| `LINKEDIN_EMAIL` / `LINKEDIN_PASSWORD` | Yes | LinkedIn login used for scraping + Easy Apply |
| `EMAIL_ADDRESS` / `EMAIL_PASSWORD` | Yes | Gmail address + App Password, used to send applications |
| `HUNTER_API_KEY` | No | Improves contact-finding (hunter.io) |
| `APOLLO_API_KEY` | No | Improves contact-finding (apollo.io) |
| `JOB_TITLES` | Yes | Comma-separated titles to search, e.g. `Business Analyst,Product Manager` |
| `JOB_LOCATION` | Yes | Comma-separated search locations |
| `JOB_WORK_TYPE` | No | Comma-separated: `Remote`, `Hybrid`, `On-site` (default `Remote,Hybrid`) |
| `JOB_KEYWORDS` | No | Keywords used for extra scoring signal |
| `MAX_JOBS_PER_RUN` | No | Cap on jobs processed per run (default 20) |
| `MIN_ATS_SCORE` | No | Drops scored jobs below this threshold (default 50) |
| `ONSITE_LOCATIONS` | No | Comma-separated city allow-list for on-site jobs (default `Noida`) — jobs outside this list are filtered out regardless of search results |
| `HYBRID_LOCATIONS` | No | Comma-separated city allow-list for hybrid jobs (default `Noida,Delhi,Gurugram,Gurgaon`) |

`ONSITE_LOCATIONS`/`HYBRID_LOCATIONS` exist because "remote" has no location constraint but on-site/hybrid roles are only worth applying to within commuting distance — set these to whatever cities are realistic for you. Remote jobs are never location-filtered.

### 3. Add your resume

Drop your resume as a `.docx` file into `data/` (see [data/README.md](data/README.md)). The agent picks the most recently modified `.docx` in that folder.

### 4. (Web app only) Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

---

## Running it

### CLI

```bash
python main.py
```
On Windows you can also double-click `agent-vinod.bat`.

First run: choose "Full run" to search LinkedIn and go through the whole pipeline. On later runs, you can choose to skip straight to resume tailoring using previously discovered jobs.

### Web app

Two processes, run from the project root:

```bash
# Terminal 1 — backend (FastAPI)
uvicorn backend.app:app --reload --reload-dir backend --reload-dir steps --port 8000

# Terminal 2 — frontend (Vite)
cd frontend
npm run dev
```
On Windows you can also double-click `agent-vinod-web.bat`, which starts both in separate windows.

Then open **http://localhost:5173** in your browser. (On some setups Vite's dev server binds only the IPv6 loopback address — use `localhost:5173`, not `127.0.0.1:5173`, if the page won't load.)

Both processes must be run with the project root as the working directory — all file paths (`data/...`) are relative.

---

## Testing

```bash
python test_e2e.py
```
Runs the full pipeline end-to-end with all external calls (Claude, email, LinkedIn Easy Apply) mocked — safe to run without burning API quota or sending real applications. LinkedIn *discovery* scraping itself is not mocked, so this does make a real (read-only) search.

---

## Project structure

```
config.py              Loads and validates .env
main.py                 CLI entry point
steps/                  Shared pipeline logic, used by both CLI and web backend
  step1_discover.py       LinkedIn scraping, filtering, ATS scoring
  step2_resume.py          Claude resume tailoring
  step3_coverletter.py     Claude cover letter generation
  step4_contacts.py        Hunter/Apollo/permutation contact finding
  step5_apply.py           Email sending + LinkedIn Easy Apply
  step6_track.py           CSV/JSON application logging
  step_excel.py            Excel tracker read/write
  browser_session.py       Playwright LinkedIn login/session handling
  llm.py / scoring.py      Shared Claude-call wrapper / keyword-scoring helpers
backend/                FastAPI web app
  app.py                   App entry point
  routers/                 One router per pipeline stage (discovery, resumes, coverletters, contacts, apply, status)
  services/                Run state, SSE progress streaming, browser worker, etc.
frontend/               React + Vite UI
  src/pages/               One page per pipeline stage
  src/components/          Shared UI components
data/                   Your resume + all generated output (gitignored — see data/README.md)
```

---

## Known limitations

- LinkedIn's page structure changes over time — scraping/Easy Apply selectors may need updates if LinkedIn redesigns their UI.
- PDF conversion (`docx2pdf`) requires Microsoft Word on Windows/macOS; not supported out of the box on Linux.
- The browser runs non-headless (visible window) — needed for LinkedIn login verification and for manual apply fallback when Easy Apply can't finish automatically.
- Single-user tool: the web app assumes one person using it at a time (no multi-user auth or job isolation).

## License

Not yet licensed — add a `LICENSE` file (e.g. MIT) if you want others to be able to legally use/fork this.
