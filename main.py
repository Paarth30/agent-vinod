"""
Job Application Agent
Run: python main.py
"""
import sys
import os
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
from pathlib import Path
from rich.console import Console
from rich.prompt import Prompt
from rich.panel import Panel
from rich.table import Table
from steps.browser_session import linkedin_login as _linkedin_login, browser_context_no_login as _browser_context_no_login

console = Console()

DISCOVERED_JSON = Path("data/discovered_jobs.json")


def main():
    # Validate environment
    try:
        import config as cfg
        cfg.validate()
    except EnvironmentError as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        console.print("Copy [cyan].env.example[/cyan] to [cyan].env[/cyan] and fill in your values.")
        sys.exit(1)
    except ImportError:
        console.print("[red]Missing dependencies.[/red] Run: [cyan]pip install -r requirements.txt[/cyan]")
        sys.exit(1)

    # Find resume in data folder
    data_dir = Path("data")
    docx_files = sorted(data_dir.glob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not docx_files:
        console.print("[red]Resume not found.[/red] Place your .docx resume in the [cyan]data/[/cyan] folder.")
        sys.exit(1)
    cfg.RESUME_DOCX_PATH = str(docx_files[0])

    # ── Startup menu ────────────────────────────────────────────────────────────
    console.print()
    console.print(Panel("[bold cyan]Agent Vinod[/bold cyan] — Job Application Agent", expand=False))
    console.print()

    prev_count = _count_previous_jobs()
    if prev_count > 0:
        console.print(f"  [1] Full run — search LinkedIn for new jobs, then apply")
        console.print(f"  [2] Skip search — use [cyan]{prev_count}[/cyan] previously found jobs, go straight to resume tailoring")
        console.print()
        choice = Prompt.ask("  Choose", choices=["1", "2"], default="1")
    else:
        console.print("  No previous jobs found — running full search.")
        choice = "1"

    console.print()

    # ── Mode 2: skip discovery, load previous jobs ──────────────────────────────
    if choice == "2":
        jobs = _load_and_select_previous_jobs()
        if not jobs:
            console.print("[red]No jobs selected. Exiting.[/red]")
            sys.exit(0)

        from steps import step2_resume, step3_coverletter, step4_contacts, step5_apply, step6_track
        from steps.step_excel import log_application, update_from_discovered, update_job_status

        # Rebuild / deduplicate Excel sheet before starting
        update_from_discovered()

        # Browser still needed for LinkedIn Easy Apply in step 5
        context = _browser_context_no_login()
        try:
            jobs = step2_resume.run(jobs)
            jobs = step3_coverletter.run(jobs)
            jobs = step4_contacts.run(jobs)
            jobs = step5_apply.run(jobs, context, methods=["linkedin", "email"])
            step6_track.run(jobs)
            for job in jobs:
                if job.get("applied"):
                    log_application(job)
                    update_job_status(job.get("link", ""), "Applied")
        except SystemExit:
            pass
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted by user.[/yellow]")
        except Exception as e:
            console.print(f"\n[red]Unexpected error:[/red] {e}")
            raise
        finally:
            context.close()

        return

    # ── Mode 1: full run ─────────────────────────────────────────────────────────
    from playwright.sync_api import sync_playwright

    SESSION_FILE = Path("data/linkedin_session.json")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            storage_state=str(SESSION_FILE) if SESSION_FILE.exists() else None,
            no_viewport=True,
        )
        _linkedin_login(context, SESSION_FILE)

        try:
            from steps import step1_discover, step2_resume, step3_coverletter, step4_contacts, step5_apply, step6_track
            from steps.step_excel import update_from_discovered, log_application, update_job_status

            run_config = {
                "role":          cfg.JOB_TITLES[0] if cfg.JOB_TITLES else "Business Analyst",
                "location":      cfg.JOB_LOCATIONS[0] if cfg.JOB_LOCATIONS else "India",
                "experience":    cfg.JOB_EXPERIENCE,
                "min_years":     cfg.MIN_YEARS_EXPERIENCE,
                "max_years":     cfg.MAX_YEARS_EXPERIENCE,
                "keywords":      cfg.JOB_KEYWORDS,
                "max_jobs":      cfg.MAX_JOBS_PER_RUN,
                "min_ats_score": cfg.MIN_ATS_SCORE,
                "methods":       ["linkedin", "email"],
                "all_titles":    cfg.JOB_TITLES,
                "all_locations": cfg.JOB_LOCATIONS,
                "work_types":    getattr(cfg, "JOB_WORK_TYPES", ["Remote", "Hybrid"]),
            }
            console.print(
                f"  Roles: [cyan]{', '.join(cfg.JOB_TITLES)}[/cyan]  |  "
                f"Locations: [cyan]{', '.join(cfg.JOB_LOCATIONS)}[/cyan]  |  "
                f"Work types: [cyan]{', '.join(getattr(cfg, 'JOB_WORK_TYPES', []))}[/cyan]"
            )

            jobs = step1_discover.run(run_config, context)
            update_from_discovered()

            jobs = step2_resume.run(jobs)
            jobs = step3_coverletter.run(jobs)
            jobs = step4_contacts.run(jobs)
            jobs = step5_apply.run(jobs, context, methods=run_config["methods"])
            step6_track.run(jobs)
            for job in jobs:
                if job.get("applied"):
                    log_application(job)
                    update_job_status(job.get("link", ""), "Applied")

        except SystemExit:
            pass
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted by user.[/yellow]")
        except Exception as e:
            console.print(f"\n[red]Unexpected error:[/red] {e}")
            raise
        finally:
            context.close()
            browser.close()


def _count_previous_jobs() -> int:
    if not DISCOVERED_JSON.exists():
        return 0
    import json
    try:
        return len(json.loads(DISCOVERED_JSON.read_text(encoding="utf-8")))
    except Exception:
        return 0


def _load_and_select_previous_jobs() -> list[dict]:
    import json
    from steps.step1_discover import _display_jobs, _user_select_jobs, _job_key
    from steps.step_excel import get_job_statuses

    all_jobs = json.loads(DISCOVERED_JSON.read_text(encoding="utf-8"))

    # Deduplicate using normalized job key (LinkedIn ID strips tracking params)
    seen, jobs = {}, []
    for j in all_jobs:
        key = _job_key(j)
        if key not in seen:
            seen[key] = True
            jobs.append(j)

    # Exclude jobs already marked Applied/Rejected — don't re-tailor/re-apply
    prev_statuses = get_job_statuses()
    skip_statuses = {"Applied", "Rejected"}
    before = len(jobs)
    jobs = [j for j in jobs if prev_statuses.get(_job_key(j)) not in skip_statuses]
    already_handled = before - len(jobs)
    if already_handled:
        console.print(f"  [dim]Skipped {already_handled} job(s) already Applied/Rejected.[/dim]")

    # Sort by ATS score descending, then priority
    jobs.sort(key=lambda j: (-((j.get("ats") or {}).get("score") or 0), -(j.get("priority") or 0)))

    console.print(f"[bold]Previously found jobs ({len(jobs)} total):[/bold]\n")
    _display_jobs(jobs)

    return _user_select_jobs(jobs)


if __name__ == "__main__":
    main()
