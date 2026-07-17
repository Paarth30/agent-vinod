"""
End-to-end test runner — uses .env config, no interactive prompts.
Tests each step individually and reports pass/fail.
"""
import sys
import time
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

PASS = "[bold green]PASS[/bold green]"
FAIL = "[bold red]FAIL[/bold red]"
SKIP = "[bold yellow]SKIP[/bold yellow]"

results = {}

def section(title):
    console.print(Panel(f"[bold]{title}[/bold]", expand=False))

def mark(step, status, note=""):
    results[step] = (status, note)
    icon = PASS if status == "pass" else (FAIL if status == "fail" else SKIP)
    console.print(f"  {icon} {step}" + (f" — {note}" if note else ""))


# ── Validate environment ───────────────────────────────────────────────────────
section("Checking config & environment")
try:
    import config as cfg
    cfg.validate()
    mark("Config / .env", "pass", f"Roles: {cfg.JOB_TITLES}, Locations: {cfg.JOB_LOCATIONS}")
except Exception as e:
    mark("Config / .env", "fail", str(e))
    console.print("[red]Cannot continue without valid config.[/red]")
    sys.exit(1)

# ── Resume file ────────────────────────────────────────────────────────────────
section("Checking resume")
docx_files = list(Path("data").glob("*.docx"))
if docx_files:
    cfg.RESUME_DOCX_PATH = str(docx_files[0])
    mark("Resume file", "pass", docx_files[0].name)
else:
    mark("Resume file", "fail", "No .docx found in data/")
    sys.exit(1)

# ── Build run config from .env ────────────────────────────────────────────────
section("Run config (from .env)")
try:
    run_config = {
        "role":          cfg.JOB_TITLES[0] if cfg.JOB_TITLES else "Business Analyst",
        "location":      cfg.JOB_LOCATIONS[0] if cfg.JOB_LOCATIONS else "India",
        "experience":    cfg.JOB_EXPERIENCE,
        "keywords":      cfg.JOB_KEYWORDS,
        "max_jobs":      cfg.MAX_JOBS_PER_RUN,
        "methods":       ["linkedin", "email"],
        "all_titles":    cfg.JOB_TITLES,
        "all_locations": cfg.JOB_LOCATIONS,
        "work_types":    getattr(cfg, "JOB_WORK_TYPES", ["Remote", "Hybrid"]),
    }
    mark("Run config", "pass", f"Roles: {cfg.JOB_TITLES} | Locations: {cfg.JOB_LOCATIONS}")
except Exception as e:
    mark("Run config", "fail", str(e))
    sys.exit(1)

# ── Browser + LinkedIn session ─────────────────────────────────────────────────
section("Browser & LinkedIn session")
from playwright.sync_api import sync_playwright

SESSION = Path("data/linkedin_session.json")
playwright = sync_playwright().start()
browser = playwright.chromium.launch(headless=False)
context = browser.new_context(
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    storage_state=str(SESSION) if SESSION.exists() else None,
)

try:
    page = context.new_page()
    page.goto("https://www.linkedin.com/feed", timeout=20000)
    time.sleep(3)
    if "/feed" in page.url:
        mark("LinkedIn session", "pass", "Session active")
    else:
        mark("LinkedIn session", "fail", f"Landed at {page.url} — run test_linkedin_login.py first")
    page.close()
except Exception as e:
    mark("LinkedIn session", "fail", str(e))

# ── Step 1: Job discovery ──────────────────────────────────────────────────────
section("Step 1 — Job Discovery")
jobs = []
try:
    from steps import step1_discover

    # Monkey-patch to skip the user-selection prompt in test mode
    original_select = step1_discover._user_select_jobs
    step1_discover._user_select_jobs = lambda j: j  # auto-select all

    # Also skip the final Confirm by patching
    import unittest.mock as mock
    with mock.patch("steps.step1_discover.Confirm.ask", return_value=True):
        jobs = step1_discover.run(run_config, context)

    step1_discover._user_select_jobs = original_select
    from steps.step_excel import update_from_discovered
    update_from_discovered()
    mark("Step 1 Discovery", "pass", f"{len(jobs)} job(s) found")
except SystemExit:
    mark("Step 1 Discovery", "fail", "No jobs found — check data/jobs_debug.png")
except Exception as e:
    mark("Step 1 Discovery", "fail", str(e))

MOCK_RESUME = "MOCK RESUME TEXT — Gemini not called in test mode"
MOCK_LETTER = "MOCK COVER LETTER — Gemini not called in test mode"

# ── Step 2: Resume tailoring ───────────────────────────────────────────────────
section("Step 2 — Resume Tailoring")
if jobs:
    try:
        from steps import step2_resume
        import unittest.mock as mock
        with mock.patch("steps.step2_resume.gemini_call", return_value=MOCK_RESUME), \
             mock.patch("steps.step2_resume.Confirm.ask", return_value=True), \
             mock.patch("steps.step2_resume.Prompt.ask", return_value="done"):
            jobs = step2_resume.run(jobs[:2])  # test with first 2 jobs only
        mark("Step 2 Resume", "pass", f"Tailored {len(jobs)} resume(s)")
    except Exception as e:
        mark("Step 2 Resume", "fail", str(e))
else:
    mark("Step 2 Resume", "skip", "No jobs from step 1")

# ── Step 3: Cover letters ──────────────────────────────────────────────────────
section("Step 3 — Cover Letters")
if jobs:
    try:
        from steps import step3_coverletter
        import unittest.mock as mock
        with mock.patch("steps.step3_coverletter.gemini_call", return_value=MOCK_LETTER), \
             mock.patch("steps.step3_coverletter.Confirm.ask", return_value=True), \
             mock.patch("steps.step3_coverletter.Prompt.ask", return_value="done"):
            jobs = step3_coverletter.run(jobs)
        mark("Step 3 Cover Letters", "pass", f"Generated {sum(1 for j in jobs if j.get('cover_letter'))} letter(s)")
    except Exception as e:
        mark("Step 3 Cover Letters", "fail", str(e))
else:
    mark("Step 3 Cover Letters", "skip", "No jobs from step 1")

# ── Step 4: Contacts ───────────────────────────────────────────────────────────
section("Step 4 — Contact Finding")
if jobs:
    try:
        from steps import step4_contacts
        import unittest.mock as mock
        with mock.patch("steps.step4_contacts.Confirm.ask", return_value=True):
            jobs = step4_contacts.run(jobs)
        found = sum(1 for j in jobs if j.get("contact"))
        mark("Step 4 Contacts", "pass", f"Found {found}/{len(jobs)} contacts")
    except Exception as e:
        mark("Step 4 Contacts", "fail", str(e))
else:
    mark("Step 4 Contacts", "skip", "No jobs from step 1")

# ── Step 5: Apply (DRY RUN — does NOT send anything) ──────────────────────────
section("Step 5 — Apply (DRY RUN)")
if jobs:
    try:
        from steps import step5_apply
        import unittest.mock as mock
        # Patch the actual send functions so nothing is sent
        with mock.patch("steps.step5_apply._send_email", return_value=True), \
             mock.patch("steps.step5_apply._linkedin_easy_apply", return_value=True), \
             mock.patch("steps.step5_apply.Confirm.ask", return_value=True):
            jobs = step5_apply.run(jobs, context)
        mark("Step 5 Apply", "pass", "Dry run OK — no emails/applications sent")
    except Exception as e:
        mark("Step 5 Apply", "fail", str(e))
else:
    mark("Step 5 Apply", "skip", "No jobs from step 1")

# ── Step 6: Tracking ───────────────────────────────────────────────────────────
section("Step 6 — Tracking")
if jobs:
    try:
        from steps import step6_track
        step6_track.run(jobs)
        mark("Step 6 Track", "pass", "Logged to data/applications.csv")
    except Exception as e:
        mark("Step 6 Track", "fail", str(e))
else:
    mark("Step 6 Track", "skip", "No jobs from step 1")

# ── Summary ────────────────────────────────────────────────────────────────────
context.close()
browser.close()
playwright.stop()

console.print()
table = Table(title="Test Summary", show_lines=True)
table.add_column("Step", style="white")
table.add_column("Result")
table.add_column("Note", style="dim")

for step, (status, note) in results.items():
    icon = "[green]PASS[/green]" if status == "pass" else ("[yellow]SKIP[/yellow]" if status == "skip" else "[red]FAIL[/red]")
    table.add_row(step, icon, note)

console.print(table)
