"""Debug job search - shows what LinkedIn returns and takes a screenshot."""
from pathlib import Path
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv
import os, time

load_dotenv()

SESSION = Path("data/linkedin_session.json")

ROLE     = "Business Analyst"
LOCATION = "Remote"
KEYWORDS = "SQL, Agile"

def test():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            storage_state=str(SESSION) if SESSION.exists() else None,
        )
        page = context.new_page()

        query = f"{ROLE} {KEYWORDS}".replace(" ", "%20")
        loc   = LOCATION.replace(" ", "%20")
        url   = f"https://www.linkedin.com/jobs/search/?keywords={query}&location={loc}"

        print(f"Navigating to: {url}")
        page.goto(url, timeout=30000)
        page.wait_for_load_state("domcontentloaded")
        time.sleep(4)

        page.screenshot(path="data/jobs_debug.png")
        print(f"Screenshot saved -> data/jobs_debug.png")
        print(f"Current URL: {page.url}")

        # Try every likely job card selector
        selectors = [
            ".job-search-card",
            "[data-entity-urn]",
            ".jobs-search__results-list li",
            ".scaffold-layout__list li",
            "[class*='job-card']",
            "li[class*='jobs-search-results']",
            ".jobs-search-results-list__list-item",
            "ul.jobs-search__results-list > li",
        ]

        for sel in selectors:
            cards = page.query_selector_all(sel)
            print(f"  {sel!r}: {len(cards)} results")

        # Also print raw page title + h1 to confirm we're on the right page
        print(f"\nPage title: {page.title()}")
        h1s = page.query_selector_all("h1")
        for h in h1s:
            print(f"  h1: {h.inner_text().strip()!r}")

        time.sleep(2)
        page.close()
        context.close()
        browser.close()

if __name__ == "__main__":
    test()
