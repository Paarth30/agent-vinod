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
    # scrape_single_job opens a page via browser_context.new_page() before it
    # reaches the (stubbed) field extraction — give it a mock context/page so no
    # real browser is touched. time.sleep is patched to keep the test instant.
    fake_ctx = mock.MagicMock()
    with mock.patch.object(step1_discover, "_fetch_jd", return_value="We need SQL, Agile, JIRA. 2 years experience. Bachelor degree."), \
         mock.patch.object(step1_discover, "_read_resume_text", return_value="SQL Agile JIRA 3 years experience bachelor"), \
         mock.patch.object(step1_discover.time, "sleep", lambda *_: None), \
         mock.patch.object(step1_discover, "_extract_job_view_fields",
                           return_value={"title": "Business Analyst", "company": "Acme",
                                         "location": "Noida, India (Hybrid)", "posted_text": "2 days ago"}):
        job = step1_discover.scrape_single_job(fake_ctx, "https://www.linkedin.com/jobs/view/123456/")
    check("returns a job dict", isinstance(job, dict))
    check("job has link", job and job.get("link", "").endswith("/jobs/view/123456/"))
    check("job has work_type hybrid", job and job.get("work_type") == "hybrid")
    check("job is ATS scored", job and isinstance(job.get("ats"), dict) and job["ats"].get("score") is not None)

test_rejects_non_job_view_url()
test_scrapes_and_scores()

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
