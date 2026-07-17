"""LinkedIn headed-Playwright browser session — login/session-restore, and a
minimal no-login context for steps that just need a browser (e.g. Easy Apply).
Shared by main.py (CLI) and the web backend."""
from pathlib import Path
from rich.console import Console

console = Console()


def browser_context_no_login():
    """Minimal browser context for steps that need it (Easy Apply) without full login flow."""
    from playwright.sync_api import sync_playwright

    SESSION_FILE = Path("data/linkedin_session.json")
    browser_context_no_login._playwright = sync_playwright().__enter__()
    pw = browser_context_no_login._playwright
    browser = pw.chromium.launch(headless=False)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        storage_state=str(SESSION_FILE) if SESSION_FILE.exists() else None,
        no_viewport=True,
    )
    browser_context_no_login._browser = browser
    browser_context_no_login._pw = pw

    # Wrap context.close to also clean up browser and playwright
    _orig_close = context.close
    def _close():
        _orig_close()
        browser.close()
        pw.__exit__(None, None, None)
    context.close = _close

    return context


def linkedin_login(context, session_file: Path):
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    import config as cfg
    import time

    page = context.new_page()
    try:
        if session_file.exists():
            page.goto("https://www.linkedin.com/feed", timeout=20000)
            time.sleep(2)
            if "/feed" in page.url or "/in/" in page.url:
                console.print("[green]OK[/green] LinkedIn session restored from cache")
                page.close()
                return
            else:
                console.print("[yellow]Saved session expired — logging in again...[/yellow]")

        page.goto("https://www.linkedin.com/login", timeout=20000)
        time.sleep(1)
        page.fill("#username", cfg.LINKEDIN_EMAIL)
        page.fill("#password", cfg.LINKEDIN_PASSWORD)
        page.click("button[type='submit']")
        time.sleep(3)

        page_text = page.inner_text("body")
        needs_verification = (
            "checkpoint" in page.url
            or "challenge" in page.url
            or "Check your LinkedIn app" in page_text
            or "verification" in page_text.lower()
            or "security check" in page_text.lower()
        )
        if needs_verification:
            console.print("[yellow]LinkedIn requires verification — approve it on your phone now.[/yellow]")
            console.print("Waiting up to 60 seconds...")
            page.wait_for_url("**/feed**", timeout=60000)

        if "/feed" in page.url or "/in/" in page.url:
            context.storage_state(path=str(session_file))
            console.print("[green]OK[/green] Logged in to LinkedIn — session saved for next run")
        else:
            console.print("[yellow]LinkedIn login may have failed — continuing anyway.[/yellow]")

    except PlaywrightTimeout:
        console.print("[yellow]LinkedIn login timed out — continuing without it.[/yellow]")
    finally:
        page.close()
