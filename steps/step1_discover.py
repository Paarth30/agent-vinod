import time
import random
import re
from urllib.parse import quote
from rich.console import Console
from rich.table import Table
from rich.prompt import Confirm, Prompt
from steps.scoring import STOPWORDS as STOPWORDS_SET, top_jd_keywords

console = Console()


def _process_candidates(all_jobs: list[dict], config: dict, resume_text: str, progress_fn, quiet: bool = False) -> list[dict]:
    """Dedup, location/work-type prioritize, exclude already-applied/rejected jobs,
    ATS-score against the resume, and apply the min-ATS cutoff. Pure over the same
    `all_jobs` list — safe to call repeatedly as more search pages are fetched, so
    `run_headless` can cheaply check "do we have enough suitable jobs yet?" after
    every round instead of only once at the very end."""

    def _p(msg):
        if not quiet:
            progress_fn(msg)

    # Deduplicate — by LinkedIn job ID (survives tracking-param churn) AND by
    # normalized title+company, since companies frequently repost the exact same
    # listing as a brand-new job ID, which the ID-only key wouldn't catch.
    seen_keys = set()
    seen_title_company = set()
    unique = []
    for j in all_jobs:
        if j.get("title") == "Unknown":
            continue
        key = _job_key(j)
        tc_key = (j.get("title", "").strip().lower(), j.get("company", "").strip().lower())
        if key in seen_keys or tc_key in seen_title_company:
            continue
        seen_keys.add(key)
        seen_title_company.add(tc_key)
        unique.append(j)

    # Assign work type, priority score, and apply location filters
    unique = _filter_and_prioritize(unique)

    # Exclude jobs already marked Applied/Rejected in a previous run — don't
    # re-tailor a resume or re-apply to a job that's already been dealt with.
    # Checked both by exact LinkedIn job ID and by (title, company), since some
    # recruiters repost the identical listing under a new job ID every run.
    from steps.step_excel import get_job_statuses, get_title_company_statuses
    prev_statuses = get_job_statuses()
    prev_tc_statuses = get_title_company_statuses()
    skip_statuses = {"Applied", "Rejected"}
    before = len(unique)
    unique = [
        j for j in unique
        if prev_statuses.get(_job_key(j)) not in skip_statuses
        and prev_tc_statuses.get((j.get("title", "").strip().lower(), j.get("company", "").strip().lower())) not in skip_statuses
    ]
    already_handled = before - len(unique)
    if already_handled:
        _p(f"  [dim]Skipped {already_handled} job(s) already Applied/Rejected in a previous run.[/dim]")

    if not unique:
        return []

    # Score each job against resume using ATS criteria — before the min-score
    # filter below, so that filter doesn't starve the final count.
    if resume_text:
        _p("  [dim]Scoring jobs against your resume (ATS)...[/dim]")
        for job in unique:
            job["ats"] = _ats_score(resume_text, job)

    # Drop jobs that scored below the minimum ATS threshold — but keep jobs
    # with no fetchable JD (score is None), since suitability can't be ruled
    # out for those; they're just unverified rather than confirmed unsuitable.
    #
    # Crucially, never let this cutoff empty the entire result set. A below-
    # threshold ATS score is a soft signal, NOT positive evidence a job is
    # unsuitable (same "no evidence, no exclusion" philosophy as the work-type
    # and years-of-experience re-verification above). When *every* surviving
    # job scores below the cutoff, silently returning nothing hides jobs that
    # LinkedIn actually surfaced and passed every relevance filter — leaving the
    # user staring at an empty search while the LinkedIn results panel visibly
    # shows matching postings. In that case keep them, best score first, and say
    # so; the user still sees each score in the table and can skip poor fits.
    min_ats_score = config.get("min_ats_score")
    if min_ats_score and resume_text:
        before = len(unique)
        kept = [j for j in unique if (j.get("ats") or {}).get("score") is None or j["ats"]["score"] >= min_ats_score]
        below_threshold = before - len(kept)
        if kept:
            unique = kept
            if below_threshold:
                _p(f"  [dim]Filtered out {below_threshold} job(s) scoring below {min_ats_score}% ATS fit.[/dim]")
        elif before:
            unique.sort(key=lambda j: ((j.get("ats") or {}).get("score") or 0, j.get("priority") or 0), reverse=True)
            _p(
                f"  [yellow]All {before} job(s) scored below your {min_ats_score}% ATS cutoff — "
                f"showing them anyway (best fit first) so the search isn't empty. "
                f"Check the ATS column and skip any that don't fit.[/yellow]"
            )

    return unique


def run_headless(config: dict, browser_context, stop_event=None, on_progress=None) -> list[dict]:
    """Same pipeline as run(), minus _user_select_jobs and the final Confirm.ask.
    Used by the web backend; run() (CLI) delegates to this for the actual pipeline.
    `stop_event` (threading.Event), if set between search pages, stops the search
    early — same granularity as the CLI's KeyboardInterrupt handling.
    `on_progress(msg)` is called alongside every console.print for SSE streaming.

    Keeps paging LinkedIn results (round-robin across every title x location
    combo, one extra page per combo per round) until at least `config["max_jobs"]`
    suitable jobs survive every filter, or every combo genuinely runs out of fresh
    results, or a hard page-load safety cap is hit — whichever comes first. A
    below-target final count is only ever returned once the search has actually
    run dry, and it's always reported explicitly, never returned silently.
    """

    def _progress(msg: str):
        console.print(msg)
        if on_progress:
            on_progress(msg)

    import config as cfg
    all_jobs = []

    titles    = config.get("all_titles") or [config["role"]]
    locations = config.get("all_locations") or [config["location"]]
    combos = [(t, l) for t in titles for l in locations]

    # Work-type filter: Remote=2, Hybrid=3, On-site=1
    work_type_map = {"remote": "2", "hybrid": "3", "on-site": "1", "onsite": "1"}
    selected_work_types = config.get("work_types") or getattr(cfg, "JOB_WORK_TYPES", ["Remote"])
    work_codes = ",".join(
        work_type_map[w.lower()] for w in selected_work_types
        if w.lower() in work_type_map
    )

    target = config["max_jobs"]
    resume_text = _read_resume_text()
    if not resume_text:
        _progress("  [yellow]Resume not readable — skipping ATS scoring.[/yellow]")

    PAGE_SIZE = 25
    MAX_PAGES_PER_COMBO = 4     # ~100 fresh postings per title/location before giving up on that combo
    MAX_TOTAL_PAGE_LOADS = 40   # hard ceiling on LinkedIn page loads regardless of combo count

    exhausted = [False] * len(combos)
    page_cursor = [0] * len(combos)
    total_page_loads = 0
    stopped = False
    capped = False

    _progress("  [dim](Press Ctrl+C at any time to stop searching and proceed with jobs found so far)[/dim]")
    try:
        while True:
            made_progress = False
            for idx, (title, location) in enumerate(combos):
                if exhausted[idx]:
                    continue
                if stop_event is not None and stop_event.is_set():
                    stopped = True
                    break
                if total_page_loads >= MAX_TOTAL_PAGE_LOADS:
                    capped = True
                    break
                page = page_cursor[idx]
                if page >= MAX_PAGES_PER_COMBO:
                    exhausted[idx] = True
                    continue
                label = f"{title} in {location}"
                if page:
                    label += f" (page {page + 1})"
                _progress(f"  Searching [cyan]{label}[/cyan]...")
                jobs, raw_count = _scrape_linkedin(title, location, work_codes, config, browser_context, start=page * PAGE_SIZE)
                _progress(f"    Found {len(jobs)} jobs")
                all_jobs.extend(jobs)
                page_cursor[idx] += 1
                total_page_loads += 1
                made_progress = True
                if raw_count == 0:
                    # A near-full page (raw_count just under PAGE_SIZE) is NOT proof
                    # of exhaustion — confirmed live that scrolling the results panel
                    # often renders only ~12-13 of a page's ~25 cards even once
                    # growth "stabilizes", while the next start=N page still returns
                    # a fully distinct, non-overlapping batch. Only a genuinely empty
                    # page means LinkedIn has nothing more for this combo.
                    exhausted[idx] = True

            if stopped or capped or all(exhausted) or not made_progress:
                break

            # Always complete one full round over every combo before checking
            # whether we already have enough — keeps the "search everything once"
            # behavior predictable instead of hammering the first combo alone.
            provisional = _process_candidates(all_jobs, config, resume_text, _progress, quiet=True)
            if len(provisional) >= target:
                break
    except KeyboardInterrupt:
        stopped = True

    if stopped:
        _progress(f"\n  [yellow]Search stopped early — proceeding with {len(all_jobs)} raw job(s) found so far.[/yellow]")

    unique = _process_candidates(all_jobs, config, resume_text, _progress, quiet=False)

    if not stopped and len(unique) < target:
        reason = "hit the search safety cap" if capped else "exhausted LinkedIn's fresh results for these titles/locations"
        _progress(
            f"  [yellow]Could only find {len(unique)} suitable job(s) of the {target} requested — {reason}. "
            f"Try widening titles/locations, or the posted-within window, if you need more.[/yellow]"
        )

    unique = unique[:target]

    _save_discovered(unique)
    return unique


def run(config: dict, browser_context) -> list[dict]:
    console.print("\n[bold]Step 1: Job Discovery[/bold]")

    unique = run_headless(config, browser_context)

    if not unique:
        console.print("[red]No jobs found.[/red]")
        console.print("Possible reasons: LinkedIn blocked scraping, selectors changed, or no results for these keywords.")
        raise SystemExit(0)

    _display_jobs(unique)
    selected = _user_select_jobs(unique)

    if not selected:
        console.print("[red]No jobs selected. Exiting.[/red]")
        raise SystemExit(0)

    console.print(f"\n[green]Selected {len(selected)} job(s).[/green]")

    if not Confirm.ask("[bold green]Proceed to resume tailoring?[/bold green]"):
        raise SystemExit(0)

    return selected


def _stem(word: str) -> str:
    """Strip common suffixes so 'manager'/'management' or 'analyst'/'analysts'
    compare equal — LinkedIn postings vary inflection more than they vary meaning."""
    for suf in ("ments", "ment", "ers", "er", "ing", "es", "s"):
        if word.endswith(suf) and len(word) - len(suf) >= 3:
            return word[: -len(suf)]
    return word


def _title_matches_query(title: str, query: str) -> bool:
    """LinkedIn's own keyword search is fuzzy/related, not exact — a search for
    'Associate Product Manager' surfaces 'Product Manager', 'Assistant Product
    Manager', 'Associate - Digital Product Management', etc. Requiring every
    query word to literally appear in the title (the original approach) rejected
    all of those near-matches, including ones that were otherwise good, work-type
    -matching candidates. Now: match on word stems (so 'manager'/'management'
    count as the same root), and allow one query word to not match when the
    query has 3+ significant words, so a single modifier swap (e.g. 'associate'
    vs 'assistant') doesn't sink an otherwise-clear match."""
    import re
    STOPWORDS = {"a", "an", "the", "of", "for", "and", "or", "in", "to", "with"}
    query_words = [w for w in re.findall(r"[a-z]+", query.lower()) if w not in STOPWORDS]
    title_stems = {_stem(w) for w in re.findall(r"[a-z]+", title.lower())}
    matches = 0
    for w in query_words:
        qs = _stem(w)
        if any(qs in ts or ts in qs for ts in title_stems):
            matches += 1
    required = len(query_words) if len(query_words) <= 2 else len(query_words) - 1
    return matches >= required


UNPAID_MARKERS = [
    "unpaid internship", "this is an unpaid", "internship is unpaid",
    "no stipend", "without stipend", "non-stipend", "not a paid",
    "no compensation", "no monetary compensation", "voluntary basis",
]


def _is_unpaid(jd: str) -> bool:
    j = jd.lower()
    return any(m in j for m in UNPAID_MARKERS)


_YEARS_RE = re.compile(
    r"(\d+)\s*(?:[-–]|to)?\s*(\d+)?\+?\s*years?\s*(?:of\s+)?(?:experience|exp)\b"
)


def _extract_required_years(jd: str) -> tuple[int, int | None] | None:
    """Pulls a required-experience range out of JD text, e.g. '1-2 years
    experience' -> (1, 2), '5+ years of experience' -> (5, None) — the second
    slot is None when the JD only states a minimum/plain number, not a bound."""
    m = _YEARS_RE.search(jd.lower())
    if not m:
        return None
    lo = int(m.group(1))
    hi = int(m.group(2)) if m.group(2) else None
    return lo, hi


_LOCATION_ALIASES = {
    "new delhi india": "New Delhi, Delhi, India",
    "noida uttar pradesh india": "Noida, Uttar Pradesh, India",
}


def _normalize_location(location: str) -> str:
    """LinkedIn's free-text location search has no country scoping — searching
    'Delhi NCR' (a real Indian region, but not a LinkedIn-recognized place name)
    silently resolves to Delhi, Ohio, USA. This app is India-only (see .env
    defaults), so anchor any location lacking a recognizable country to India,
    and special-case the one broken token actually used in this project.

    Separately: LinkedIn's own UI always produces comma-separated 'City,
    State, Country' text (that's the format its autocomplete generates). A
    bare space-separated multi-word query like 'New Delhi India' or 'Noida
    Uttar Pradesh India' — exactly the .env defaults, entered with no commas
    to avoid colliding with .env's own comma-separated location LIST syntax —
    can resolve to an unrelated narrow locality that happens to share a token,
    instead of the intended city. Hardcode the comma-separated form for the
    known-ambiguous .env defaults, same pattern as the NCR special-case above,
    rather than attempting a general space-to-comma parser (splitting on a
    recognized state/country substring is unsafe in general — e.g. 'New Delhi'
    itself ends in 'Delhi', which is also a state name)."""
    import re
    loc = location.strip()
    low = loc.lower()
    if low in _LOCATION_ALIASES:
        return _LOCATION_ALIASES[low]
    if re.search(r"\bncr\b", low):
        return "New Delhi, India"
    if not re.search(r"\b(india|united states|usa|uk|remote)\b", low):
        return f"{loc}, India"
    return loc


def _scrape_linkedin(role: str, location: str, work_codes: str, config: dict, browser_context, start: int = 0) -> tuple[list[dict], int]:
    """Scrapes one page (25 results) of LinkedIn search results, at offset `start`.
    Returns (jobs, raw_card_count) — raw_card_count (pre-filter) lets the caller
    detect "LinkedIn had no more results" (a short/empty page) vs. "this page's
    results just didn't pass our filters" (a full page, worth paging past)."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    jobs = []
    cards = []
    skipped_mismatch = 0
    skipped_unpaid = 0
    skipped_work_type = 0
    skipped_experience = 0
    page = browser_context.new_page()

    query = quote(role.strip())   # search by role title only — avoids over-filtering
    loc = quote(_normalize_location(location))
    selected_work_types = {
        ("on-site" if w.strip().lower() in ("onsite", "on-site") else w.strip().lower())
        for w in (config.get("work_types") or [])
    }

    # LinkedIn f_E values: 1=intern, 2=entry, 3=associate, 4=mid-senior, 5=director, 6=executive
    exp_map = {"internship": "1", "entry": "2", "mid": "4", "senior": "4", "lead": "5", "any": ""}
    exp_code = exp_map.get(config.get("experience", "any"), "")
    min_years = config.get("min_years")
    max_years = config.get("max_years")

    # Use role as keyword only — keywords are for tailoring, not search filtering
    # f_TPR (posted within last week) keeps results fresh across repeated runs
    # without abandoning relevance ranking — sortBy=DD (pure date-sort) was tried
    # here previously but surfaced senior/VP-level postings that merely matched
    # keywords, since date-sort ignores title/relevance match quality entirely.
    url = (
        f"https://www.linkedin.com/jobs/search/?keywords={query}&location={loc}"
        f"&refresh=true&f_TPR=r604800&start={start}"
    )
    if exp_code:
        url += f"&f_E={exp_code}"
    if work_codes:
        url += f"&f_WT={work_codes}"

    try:
        page.goto(url, timeout=30000)
        page.wait_for_load_state("domcontentloaded")
        time.sleep(random.uniform(3, 5))

        # Logged-in LinkedIn selectors (2024/2025)
        card_selectors = [
            "li.jobs-search-results__list-item",
            ".job-card-container",
            "li[class*='jobs-search-results__list-item']",
            ".scaffold-layout__list-container li",
            "ul.jobs-search__results-list > li",
            "[data-job-id]",
        ]

        def _count_cards():
            for sel in card_selectors:
                found = page.query_selector_all(sel)
                if found:
                    return sel, found
            return None, []

        # LinkedIn renders the job list inside its own scrollable side-panel
        # with an obfuscated, build-specific class name (confirmed live —
        # e.g. "QURkANsvhPYVZtx..." — not a stable selector to hardcode), so
        # scrolling `window` or guessing semantic class names does nothing to
        # it: a single scroll only ever rendered the ~7 cards that fit that
        # panel's initial viewport, capping every fetch at 7 regardless of how
        # many the page actually has (~25). Scroll every scrollable element on
        # the page instead of guessing one selector — confirmed live to
        # actually grow the rendered card count — repeating (bounded) until
        # the count stops growing.
        _SCROLL_ALL_JS = """() => {
            document.querySelectorAll('*').forEach(el => {
                if (el.scrollHeight - el.clientHeight > 50 && el.clientHeight > 100) {
                    el.scrollTop = el.scrollHeight;
                }
            });
        }"""
        page.evaluate("window.scrollTo(0, 600)")
        time.sleep(1.5)
        prev_count = -1
        for _ in range(8):
            _, found = _count_cards()
            current = len(found)
            if current <= prev_count or current >= 25:
                break
            prev_count = current
            page.evaluate(_SCROLL_ALL_JS)
            time.sleep(1.2)

        # Take a debug screenshot
        page.screenshot(path="data/jobs_debug.png")

        matched_sel, cards = _count_cards()
        if cards:
            console.print(f"    [dim]Matched selector: {matched_sel!r} ({len(cards)} cards)[/dim]")

        if not cards:
            console.print(f"    [yellow]No cards matched — check data/jobs_debug.png[/yellow]")
            return [], 0

        for card in cards:
            try:
                # Title
                title_el = (
                    card.query_selector(".job-card-list__title--link")
                    or card.query_selector("a[class*='job-card-list__title']")
                    or card.query_selector(".job-card-container__link")
                    or card.query_selector("a[class*='job-card']")
                    or card.query_selector("h3 a")
                    or card.query_selector("h3")
                )
                # Link
                link_el = card.query_selector("a[href*='/jobs/view/']") or card.query_selector("a")

                # Fix title doubling — LinkedIn aria-hidden spans duplicate the text
                title = title_el.inner_text().strip().split("\n")[0].strip() if title_el else "Unknown"

                if title != "Unknown" and not _title_matches_query(title, role):
                    skipped_mismatch += 1
                    continue

                # Extract all leaf-level text spans to find company + location robustly
                spans = card.evaluate("""el => {
                    return [...new Set(
                        Array.from(el.querySelectorAll('span, div, h4, a'))
                            .filter(s => s.children.length === 0 && s.innerText && s.innerText.trim().length > 1)
                            .map(s => s.innerText.trim())
                    )];
                }""")

                # Capture "X days/weeks ago" before filtering it out
                posted_text = ""
                for span in spans:
                    sl = span.lower()
                    if "ago" in sl and len(span) < 30:
                        posted_text = span.strip()
                        break

                skip_words = ["ago", "applicant", "actively", "promoted", "viewed",
                              "easy apply", "save", "full-time", "part-time", "contract",
                              "internship", "with verification", "logo", "avatar",
                              "week", "month", "day", "hour", "minute"]
                location_words = ["india", "area", "delhi", "noida", "bangalore", "mumbai",
                                  "hyderabad", "pune", "chennai", "remote", "hybrid", "on-site",
                                  "gurugram", "gurgaon", "kolkata", "bengaluru", "metropolitan"]

                company = "Unknown"
                location_candidates = []
                for span in spans:
                    sl = span.lower()
                    # Skip if same as title, too short, or contains badge/noise text
                    if sl == title.lower() or len(span) < 2:
                        continue
                    if any(w in sl for w in skip_words):
                        continue
                    if company == "Unknown" and not any(w in sl for w in location_words):
                        company = span.split("\n")[0].strip()
                    elif any(w in sl for w in location_words):
                        location_candidates.append(span.split("\n")[0].strip())

                # LinkedIn renders location as e.g. "Gurugram, Haryana, India (Hybrid)"
                # but sometimes duplicates it into a hidden accessibility span missing
                # the "(Remote)/(Hybrid)/(On-site)" suffix — prefer whichever candidate
                # actually states the workplace type over just taking the first match.
                import re
                with_type = [c for c in location_candidates if re.search(r"\((remote|hybrid|on-site|onsite)\)", c.lower())]
                if with_type:
                    job_loc = with_type[0]
                elif location_candidates:
                    job_loc = location_candidates[0]
                else:
                    job_loc = location

                # LinkedIn's own f_WT filter sometimes under-delivers (e.g. when the
                # location resolved ambiguously) and returns a mix of work types
                # anyway — re-verify each card actually matches what was requested
                # instead of trusting the URL filter alone. Only exclude on positive
                # evidence (an explicitly stated type that doesn't match) — a card
                # with no stated type is just as likely an under-labeled match as a
                # true mismatch, so it's kept rather than assumed on-site.
                detected_type = _detect_work_type(job_loc)
                if selected_work_types and detected_type is not None and detected_type not in selected_work_types:
                    skipped_work_type += 1
                    continue

                link = link_el.get_attribute("href") if link_el else ""
                if link and not link.startswith("http"):
                    link = "https://www.linkedin.com" + link

                if title == "Unknown" and company == "Unknown":
                    continue

                jd = _fetch_jd(browser_context, link) if link else ""

                if jd and _is_unpaid(jd):
                    skipped_unpaid += 1
                    continue

                # Only exclude on positive evidence the JD states a requirement
                # outside the candidate's chosen range — same "no evidence, no
                # exclusion" rule as the work-type re-verification above. A JD
                # that never mentions years of experience is kept, not assumed
                # to be a mismatch.
                if jd and (min_years is not None or max_years is not None):
                    req = _extract_required_years(jd)
                    if req:
                        req_lo, req_hi = req
                        if max_years is not None and req_lo > max_years:
                            skipped_experience += 1
                            continue
                        if min_years is not None and req_hi is not None and req_hi < min_years:
                            skipped_experience += 1
                            continue

                jobs.append({
                    "title": title,
                    "company": company,
                    "location": job_loc,
                    "link": link,
                    "source": "linkedin",
                    "jd": jd,
                    "posted_text": posted_text,
                })
                time.sleep(random.uniform(1, 2))

            except Exception as e:
                console.print(f"    [dim]Card parse error: {e}[/dim]")
                continue

    except PlaywrightTimeout:
        console.print(f"    [yellow]LinkedIn timed out for {role} / {location}[/yellow]")
    except Exception as e:
        console.print(f"    [red]Error: {e}[/red]")
    finally:
        page.close()

    if skipped_mismatch:
        console.print(f"    [dim]Skipped {skipped_mismatch} job(s) whose title didn't match '{role}'[/dim]")
    if skipped_unpaid:
        console.print(f"    [dim]Skipped {skipped_unpaid} unpaid/non-stipend job(s)[/dim]")
    if skipped_work_type:
        console.print(f"    [dim]Skipped {skipped_work_type} job(s) whose actual work type didn't match your selection[/dim]")
    if skipped_experience:
        console.print(f"    [dim]Skipped {skipped_experience} job(s) requiring more/less experience than you selected[/dim]")

    return jobs, len(cards)


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


def _fetch_jd(browser_context, url: str) -> str:
    if not url or "/jobs/view/" not in url:
        return ""
    page = browser_context.new_page()
    try:
        page.goto(url, timeout=25000)
        page.wait_for_load_state("domcontentloaded")
        time.sleep(random.uniform(2, 3))

        # Expand "Show more" / "See more" if present
        for btn_sel in ["button[aria-label*='more']", "button.show-more-less-html__button", "[class*='show-more']"]:
            btn = page.query_selector(btn_sel)
            if btn:
                try:
                    btn.click()
                    time.sleep(0.5)
                    break
                except Exception:
                    pass

        jd_selectors = [
            ".jobs-description__content",
            ".show-more-less-html__markup",
            "#job-details",
            ".jobs-description-content__text",
            "section.jobs-description",
            ".description__text",
            "[class*='job-description']",
            "[class*='description-content']",
        ]

        for sel in jd_selectors:
            el = page.query_selector(sel)
            if el:
                text = el.inner_text().strip()
                if len(text) > 50:
                    return text[:4000]

        # Last resort: grab all visible text from main content area
        text = page.evaluate("""() => {
            const main = document.querySelector('main') || document.querySelector('.scaffold-layout__main') || document.body;
            return main ? main.innerText.trim() : '';
        }""")
        return text[:4000] if len(text) > 100 else ""
    except Exception as e:
        console.print(f"    [dim]JD fetch error: {e}[/dim]")
        return ""
    finally:
        page.close()


def _detect_work_type(location: str) -> str | None:
    """Returns the workplace type only when the location text actually states
    one — None means "unstated", which callers should treat as unknown rather
    than silently assuming on-site (a card missing the marker is just as likely
    to be an under-labeled Remote/Hybrid posting)."""
    loc = location.lower()
    if "remote" in loc:
        return "remote"
    if "hybrid" in loc:
        return "hybrid"
    if "on-site" in loc or "onsite" in loc:
        return "on-site"
    return None


def _job_key(job: dict) -> str:
    """Stable dedup key that survives URL tracking-param churn.
    Uses the LinkedIn job ID (numeric) when present; falls back to title|company."""
    import re
    link = str(job.get("link", "")).strip()
    m = re.search(r"/jobs/view/(\d+)", link)
    if m:
        return f"li:{m.group(1)}"
    return (job.get("title", "") + "|" + job.get("company", "")).lower().strip()


def _filter_and_prioritize(jobs: list[dict]) -> list[dict]:
    import config as cfg

    filtered = []
    skipped = 0

    for job in jobs:
        # Unstated work type defaults to on-site here (unlike the per-card search
        # filter above) — every job still needs a definite bucket for priority
        # ordering and the location allow-list check below.
        work_type = _detect_work_type(job.get("location", "")) or "on-site"
        job["work_type"] = work_type
        job["priority"] = cfg.JOB_PRIORITY.get(work_type, 0)

        allowed_locations = cfg.JOB_LOCATION_RULES.get(work_type, [])
        if allowed_locations:
            loc = job.get("location", "").lower()
            if not any(city in loc for city in allowed_locations):
                skipped += 1
                continue  # filtered out

        filtered.append(job)

    # Sort highest priority first
    filtered.sort(key=lambda j: j["priority"], reverse=True)

    if skipped:
        console.print(f"  [dim]Filtered out {skipped} job(s) outside allowed locations.[/dim]")

    return filtered


def _read_resume_text() -> str:
    import config as cfg
    from pathlib import Path
    path = Path(cfg.RESUME_DOCX_PATH) if cfg.RESUME_DOCX_PATH else None
    if not path or not path.exists():
        # Try scanning data/ as fallback
        candidates = sorted(Path("data").glob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
        path = candidates[0] if candidates else None
    if not path:
        return ""
    try:
        from docx import Document
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception:
        return ""


def _ats_score(resume: str, job: dict) -> dict:
    """
    ATS-style confidence score. Mirrors the 5 criteria real ATS systems use.

    Weights:
      Skills match      35%  — required tools/technologies found in resume
      Keyword density   30%  — important JD terms found in resume
      Experience        20%  — years-of-experience requirement met
      Education         10%  — degree requirement met
      Title relevance    5%  — role title similarity to candidate's past titles
    """
    import re

    jd = job.get("jd", "")
    if not jd or len(jd) < 50:
        return {"score": None, "label": "No JD", "breakdown": {}}

    r = resume.lower()
    j = jd.lower()

    # ── 1. Skills match (35%) ──────────────────────────────────────────────────
    SKILLS = [
        "sql", "python", "excel", "tableau", "power bi", "powerbi", "jira",
        "confluence", "agile", "scrum", "kanban", "salesforce", "crm", "erp",
        "sap", "figma", "google analytics", "looker", "dax", "spark", "airflow",
        "stakeholder", "product roadmap", "user stories", "brd", "frd", "uml",
        "a/b testing", "kpi", "okr", "go-to-market", "gtm", "b2b", "saas",
        "api", "rest api", "data analysis", "market research", "competitive analysis",
    ]
    jd_skills  = [s for s in SKILLS if s in j]
    hit_skills = [s for s in jd_skills if s in r]
    skills_score = (len(hit_skills) / max(len(jd_skills), 1)) * 35

    # ── 2. Keyword density (30%) ───────────────────────────────────────────────
    top_kw      = top_jd_keywords(jd, 40)
    hit_kw      = [w for w in top_kw if w in r]
    kw_score    = (len(hit_kw) / max(len(top_kw), 1)) * 30

    # ── 3. Experience match (20%) ──────────────────────────────────────────────
    req_match   = re.search(r'(\d+)\+?\s*(?:to\s*\d+\s*)?years?\s*(?:of\s+)?(?:experience|exp)', j)
    has_match   = re.search(r'(\d+)\+?\s*(?:to\s*\d+\s*)?years?\s*(?:of\s+)?(?:experience|exp)', r)
    if req_match and has_match:
        req_yr  = int(req_match.group(1))
        has_yr  = int(has_match.group(1))
        exp_score = min(has_yr / max(req_yr, 1), 1.2) * 20   # 1.2 cap = slight bonus for overqualified
    elif req_match:
        req_yr  = int(req_match.group(1))
        exp_score = 20 if req_yr <= 1 else (14 if req_yr <= 3 else 8)
    else:
        exp_score = 15  # neutral — JD didn't specify

    # ── 4. Education match (10%) ───────────────────────────────────────────────
    EDU_TIERS = [
        (["mba", "master", "m.tech", "m.e", "mca", "pgdm"], 10),
        (["bachelor", "b.tech", "b.e", "bca", "b.sc", "degree"],  8),
        (["diploma", "graduate", "graduation"],                     6),
    ]
    edu_score = 5  # baseline
    for terms, pts in EDU_TIERS:
        if any(t in j for t in terms) and any(t in r for t in terms):
            edu_score = pts
            break
        elif any(t in j for t in terms):
            edu_score = max(pts - 4, 3)
            break

    # ── 5. Title relevance (5%) ────────────────────────────────────────────────
    title_words = set(re.findall(r'\b[a-z]{3,}\b', job.get("title", "").lower())) - STOPWORDS_SET
    title_score = min(sum(1 for w in title_words if w in r) / max(len(title_words), 1), 1) * 5

    # ── Total ──────────────────────────────────────────────────────────────────
    total = skills_score + kw_score + exp_score + edu_score + title_score
    total = round(min(total, 100))

    label = (
        "Excellent" if total >= 80 else
        "Good"      if total >= 65 else
        "Fair"      if total >= 50 else
        "Low"
    )

    return {
        "score": total,
        "label": label,
        "breakdown": {
            "skills":     round(skills_score),
            "keywords":   round(kw_score),
            "experience": round(exp_score),
            "education":  round(edu_score),
            "title":      round(title_score),
        },
        "matched_skills":  hit_skills,
        "missing_skills":  [s for s in jd_skills if s not in hit_skills],
        "matched_keywords": hit_kw[:10],
    }


def _save_discovered(jobs: list[dict]):
    import json
    from pathlib import Path
    from datetime import datetime
    out = Path("data/discovered_jobs.json")
    out.parent.mkdir(exist_ok=True)
    records = []
    if out.exists():
        try:
            records = json.loads(out.read_text(encoding="utf-8"))
        except Exception:
            pass
    # Add today's batch tagged with run timestamp
    ts = datetime.now().isoformat(timespec="seconds")
    for job in jobs:
        records.append({**job, "discovered_at": ts})
    out.write_text(json.dumps(records, indent=2), encoding="utf-8")
    console.print(f"  [dim]Saved {len(jobs)} jobs to {out}[/dim]")


def _display_jobs(jobs: list[dict]):
    table = Table(title=f"Jobs Found ({len(jobs)})", show_lines=True)
    table.add_column("#", style="cyan", width=4)
    table.add_column("Title", style="white")
    table.add_column("Company", style="yellow")
    table.add_column("Location", style="green")
    table.add_column("Type", width=8)
    table.add_column("Pri", style="cyan", width=4)
    table.add_column("ATS", width=14)
    table.add_column("Link", style="dim")

    for i, job in enumerate(jobs, 1):
        wtype = job.get("work_type", "")
        pri   = str(job.get("priority", ""))
        link  = job.get("link", "")
        type_color = {"remote": "green", "hybrid": "yellow", "on-site": "red"}.get(wtype, "white")

        ats   = job.get("ats", {})
        score = ats.get("score")
        label = ats.get("label", "")
        if score is None:
            ats_str = "[dim]No JD[/dim]"
        else:
            score_color = (
                "bold green"  if score >= 80 else
                "green"       if score >= 65 else
                "yellow"      if score >= 50 else
                "red"
            )
            ats_str = f"[{score_color}]{score}% {label}[/{score_color}]"

        table.add_row(
            str(i), job["title"], job["company"], job["location"],
            f"[{type_color}]{wtype}[/{type_color}]", pri, ats_str, link,
        )

    console.print("\n", table)

    # Print score breakdown for top 3 jobs
    scored = [j for j in jobs if j.get("ats", {}).get("score") is not None]
    if scored:
        console.print("\n[bold]ATS Breakdown — Top Matches:[/bold]")
        for job in scored[:3]:
            ats = job["ats"]
            bd  = ats.get("breakdown", {})
            console.print(
                f"  [cyan]{job['company']}[/cyan] — [bold]{ats['score']}%[/bold] "
                f"| Skills {bd.get('skills',0)}/35 "
                f"| Keywords {bd.get('keywords',0)}/30 "
                f"| Exp {bd.get('experience',0)}/20 "
                f"| Edu {bd.get('education',0)}/10 "
                f"| Title {bd.get('title',0)}/5"
            )
            if ats.get("matched_skills"):
                console.print(f"    [green]Matched:[/green] {', '.join(ats['matched_skills'])}")
            if ats.get("missing_skills"):
                console.print(f"    [red]Missing:[/red] {', '.join(ats['missing_skills'])}")


def _user_select_jobs(jobs: list[dict]) -> list[dict]:
    console.print("\nEnter job numbers to apply to (e.g. [cyan]1,3,5[/cyan]) or [cyan]all[/cyan]:")
    choice = Prompt.ask("Selection", default="all")

    if choice.strip().lower() == "all":
        return jobs

    seen, selected = set(), []
    for part in choice.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(jobs):
                job = jobs[idx]
                key = job.get("link") or job.get("title", "") + job.get("company", "")
                if key not in seen:
                    seen.add(key)
                    selected.append(job)

    return selected
