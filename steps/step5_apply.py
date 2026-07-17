import smtplib
import time
import random
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from rich.console import Console
from rich.prompt import Confirm
import config as cfg

console = Console()

PHONE = cfg.EMAIL_ADDRESS  # fallback; add PHONE= to .env if needed


def run(jobs: list[dict], browser_context, methods: list[str] = None) -> list[dict]:
    if methods is None:
        methods = ["linkedin", "email"]

    console.print("\n[bold]Step 5: Sending Applications[/bold]")
    console.print(f"[yellow]About to apply to {len(jobs)} job(s) via: {', '.join(methods)}[/yellow]")

    if not Confirm.ask("[bold red]Send all applications now?[/bold red]"):
        console.print("[red]Aborted. No applications were sent.[/red]")
        raise SystemExit(0)

    for i, job in enumerate(jobs, 1):
        console.print(f"\n[cyan][{i}/{len(jobs)}][/cyan] Applying to [bold]{job['title']}[/bold] at [bold]{job['company']}[/bold]")
        results = []

        # Email — only if contact email found AND email method selected
        if "email" in methods and job.get("contact") and job["contact"].get("email"):
            ok = _send_email(job)
            results.append(("email", ok))

        # LinkedIn Easy Apply — only if email didn't succeed (avoid double-apply)
        email_sent = any(m == "email" and ok for m, ok in results)
        if "linkedin" in methods and not email_sent and job.get("source") == "linkedin" and job.get("link"):
            ok = _linkedin_easy_apply(job, browser_context)
            results.append(("linkedin", ok))

        job["application_results"] = results
        job["applied"] = any(ok for _, ok in results)

        if not results:
            console.print("  [dim]No apply method available for this job.[/dim]")
        for method, ok in results:
            icon = "[green]Sent[/green]" if ok else "[red]Failed[/red]"
            console.print(f"  {method}: {icon}")

        time.sleep(random.uniform(3, 7))

    return jobs


def _send_email(job: dict) -> bool:
    contact = job["contact"]
    to_email = contact["email"]
    to_name = contact.get("name") or "Hiring Team"

    subject = f"Application for {job['title']} - {cfg.EMAIL_ADDRESS.split('@')[0].title()}"

    body = job.get("cover_letter") or (
        f"Dear {to_name},\n\n"
        f"I am writing to express my interest in the {job['title']} role at {job['company']}. "
        f"Please find my resume attached.\n\nBest regards"
    )

    msg = MIMEMultipart()
    msg["From"] = cfg.EMAIL_ADDRESS
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    # Attach resume — prefer tailored PDF, fall back to original docx
    resume_file = (
        job.get("resume_pdf")
        or job.get("resume_docx")
        or cfg.RESUME_DOCX_PATH
    )
    if resume_file and Path(resume_file).exists():
        with open(resume_file, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{Path(resume_file).name}"')
        msg.attach(part)

    pwd = (cfg.EMAIL_PASSWORD or "").strip().replace(" ", "")
    if not pwd:
        console.print("  [red]Email error: EMAIL_PASSWORD not set in .env[/red]")
        return False
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(cfg.EMAIL_ADDRESS, pwd)
            server.sendmail(cfg.EMAIL_ADDRESS, to_email, msg.as_string())
        return True
    except Exception as e:
        console.print(f"  [red]Email error: {e}[/red]")
        return False


def _modal_fingerprint(page) -> str:
    """Cheap snapshot of the Easy Apply modal's visible content, used to detect
    when clicking Next/Review didn't actually advance the form."""
    try:
        modal = (
            page.query_selector(".jobs-easy-apply-modal")
            or page.query_selector("[data-test-modal-id='easy-apply-modal']")
            or page.query_selector("[role='dialog']")
        )
        return modal.inner_text() if modal else ""
    except Exception:
        return ""


def _linkedin_easy_apply(job: dict, browser_context, on_wait=None) -> bool:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    page = browser_context.new_page()
    try:
        page.goto(job["link"], timeout=30000)
        page.wait_for_load_state("domcontentloaded")
        time.sleep(random.uniform(2, 3))

        # Find Easy Apply button — try multiple selector variants
        easy_apply_btn = (
            page.query_selector("button.jobs-apply-button[aria-label*='Easy Apply']")
            or page.query_selector("[aria-label*='Easy Apply']")
            or page.query_selector("button:has-text('Easy Apply')")
        )

        if not easy_apply_btn:
            console.print("  [yellow]Easy Apply not available — handing off to you.[/yellow]")
            return _manual_apply_fallback(page, job, on_wait)

        easy_apply_btn.click()
        time.sleep(random.uniform(1, 2))

        # Walk through modal — max 15 steps
        for step in range(15):
            time.sleep(1)

            # Upload resume if prompted
            upload = page.query_selector("input[type='file']")
            if upload:
                resume_file = job.get("resume_pdf") or job.get("resume_docx") or cfg.RESUME_DOCX_PATH
                if resume_file and Path(resume_file).exists():
                    upload.set_input_files(resume_file)
                    time.sleep(1)

            # Fill phone number if field is empty
            phone_input = page.query_selector("input[id*='phoneNumber']")
            phone_val = getattr(cfg, "PHONE_NUMBER", "")
            if phone_input and phone_val and not phone_input.input_value():
                phone_input.fill(phone_val)

            # Check for required unfilled fields — only catches plain <input>/<select>
            # elements; LinkedIn's custom screening questions (radio groups, custom
            # dropdowns) aren't real form controls and slip past this, which is why
            # the post-click fingerprint check below exists as a backstop.
            required_empty = page.query_selector_all(
                "input[required]:not([type='file']):not([type='hidden'])[value=''], "
                "select[required] option[value='']:checked"
            )
            if required_empty:
                console.print(f"  [yellow]Form has unanswered questions at step {step+1} — handing off to you.[/yellow]")
                return _manual_apply_fallback(page, job, on_wait)

            submit_btn = page.query_selector("button[aria-label='Submit application']")
            next_btn = (
                page.query_selector("button[aria-label='Continue to next step']")
                or page.query_selector("button[aria-label='Review your application']")
                or page.query_selector("button:has-text('Next')")
                or page.query_selector("button:has-text('Review')")
            )

            if submit_btn:
                submit_btn.click()
                time.sleep(2)
                console.print("  [green]Easy Apply submitted.[/green]")
                return True
            elif next_btn:
                before = _modal_fingerprint(page)
                next_btn.click()
                time.sleep(1.5)
                # LinkedIn's custom (non-<select>/<input>) screening-question widgets
                # block navigation client-side instead of throwing — if the modal's
                # content is unchanged after clicking Next, we're stuck on a question
                # our selectors above didn't recognize as unfilled. Don't keep
                # clicking into a wall; hand off instead of burning the step budget.
                if _modal_fingerprint(page) == before:
                    console.print(f"  [yellow]Form didn't advance at step {step+1} (likely an unanswered question) — handing off to you.[/yellow]")
                    return _manual_apply_fallback(page, job, on_wait)
            else:
                console.print(f"  [yellow]Easy Apply stalled at step {step+1} — handing off to you.[/yellow]")
                return _manual_apply_fallback(page, job, on_wait)

        console.print("  [yellow]Easy Apply didn't finish within the step limit — handing off to you.[/yellow]")
        return _manual_apply_fallback(page, job, on_wait)

    except PlaywrightTimeout:
        console.print("  [red]LinkedIn timed out — handing off to you.[/red]")
        return _manual_apply_fallback(page, job, on_wait)
    except Exception as e:
        console.print(f"  [red]Easy Apply error: {e}[/red]")
        return _manual_apply_fallback(page, job, on_wait)
    finally:
        page.close()


def _manual_apply_fallback(page, job: dict, on_wait=None) -> bool:
    """Keep the browser open on the job page and wait for the user to apply manually.

    `on_wait`, if given (used by the web backend), is called instead of blocking on
    terminal input() — it must block until the user resolves it and return True/False.
    The CLI path (on_wait=None) is completely unchanged."""
    link = job.get("link", "")
    if on_wait is not None:
        return on_wait(job)

    console.print(f"\n  [bold yellow]>>> Manual apply needed[/bold yellow]")
    console.print(f"  The browser is open on: [cyan]{link}[/cyan]")
    console.print(f"  Job: [bold]{job['title']}[/bold] at [bold]{job['company']}[/bold]")
    console.print(f"  Please apply in the browser window, then come back here.")
    console.print()

    try:
        answer = input("  Press Enter when done, or type 'skip' to skip this job: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "skip"

    if answer == "skip":
        console.print("  [dim]Skipped.[/dim]")
        return False

    console.print("  [green]Marked as applied.[/green]")
    return True
