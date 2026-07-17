import json
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from steps import step0_intake, step1_discover
from steps.step1_discover import _job_key
from steps.step_excel import update_from_discovered, get_job_statuses, update_job_status

from backend.schemas.jobs import DiscoveryStartRequest, RunIdResponse, JobSelectRequest, JobOut, SuggestTitlesResponse
from backend.services.run_state import run_state
from backend.services.sse import broker, strip_rich_markup, parse_last_event_id
from backend.services.browser_worker import browser_worker
from backend.services.claude_client import get_client
from backend.services.title_suggester import suggest_titles

router = APIRouter(prefix="/api/discovery", tags=["discovery"])
jobs_router = APIRouter(prefix="/api/jobs", tags=["jobs"])

DISCOVERED_JSON = Path("data/discovered_jobs.json")

_active_stop_events: dict[str, threading.Event] = {}


def _build_config(body: DiscoveryStartRequest) -> dict:
    base = step0_intake.run(interactive=False)
    if body.titles:
        base["all_titles"] = body.titles
        base["role"] = body.titles[0]
    if body.locations:
        base["all_locations"] = body.locations
        base["location"] = body.locations[0]
    if body.work_types:
        base["work_types"] = body.work_types
    if body.max_jobs:
        base["max_jobs"] = body.max_jobs
    if body.min_ats_score is not None:
        base["min_ats_score"] = body.min_ats_score
    if body.experience is not None:
        base["experience"] = body.experience
    if body.min_years is not None:
        base["min_years"] = body.min_years
    if body.max_years is not None:
        base["max_years"] = body.max_years
    return base


def _find_job_by_key(job_key: str) -> dict | None:
    job = run_state.jobs.get(job_key)
    if job:
        return job
    if DISCOVERED_JSON.exists():
        all_jobs = json.loads(DISCOVERED_JSON.read_text(encoding="utf-8"))
        by_key = {_job_key(j): j for j in all_jobs}  # last occurrence wins
        return by_key.get(job_key)
    return None


def _job_to_out(job: dict) -> dict:
    return {
        "job_key": _job_key(job),
        "title": job.get("title", ""),
        "company": job.get("company", ""),
        "location": job.get("location", ""),
        "link": job.get("link", ""),
        "work_type": job.get("work_type"),
        "priority": job.get("priority"),
        "posted_text": job.get("posted_text"),
        "ats": job.get("ats"),
    }


def _discovery_worker(run_id: str, config: dict, stop_event: threading.Event):
    def on_progress(msg: str):
        broker.publish(run_id, {"type": "log", "message": strip_rich_markup(msg)})

    run_state.active_discovery_run_id = run_id
    run_state.stage = "discovering"
    run_state.save()
    try:
        if not browser_worker.started:
            broker.publish(run_id, {"type": "log", "message": "Launching browser and logging into LinkedIn..."})
            browser_worker.start()
        jobs = browser_worker.submit(
            lambda: step1_discover.run_headless(config, browser_worker.context, stop_event, on_progress)
        )
        run_state.set_jobs(jobs)
        run_state.stage = "selecting"
        run_state.save()
        try:
            update_from_discovered()
        except Exception:
            pass
        broker.finish(run_id, {"type": "done", "count": len(jobs)})
    except Exception as e:
        run_state.stage = "idle"
        run_state.save()
        broker.finish(run_id, {"type": "error", "message": str(e)})
    finally:
        _active_stop_events.pop(run_id, None)
        if run_state.active_discovery_run_id == run_id:
            run_state.active_discovery_run_id = None


@router.get("/defaults")
def discovery_defaults():
    """.env-derived defaults, for the frontend to pre-fill the search form."""
    config = step0_intake.run(interactive=False)
    return {
        "titles": config["all_titles"],
        "locations": config["all_locations"],
        "work_types": config["work_types"],
        "max_jobs": config["max_jobs"],
        "min_ats_score": config["min_ats_score"],
        "experience": config["experience"],
        "min_years": config["min_years"],
        "max_years": config["max_years"],
    }


@router.post("/suggest-titles", response_model=SuggestTitlesResponse)
def discovery_suggest_titles():
    """Reads the candidate's resume and suggests LinkedIn search titles suited
    to their actual experience level, for the Discovery form's suggest button."""
    resume_text = run_state.ensure_original_resume_text()
    if not resume_text:
        raise HTTPException(400, "Resume not readable — check data/*.docx exists")
    config = step0_intake.run(interactive=False)
    titles = suggest_titles(get_client(), resume_text, config["all_titles"])
    if not titles:
        raise HTTPException(502, "Claude did not return usable title suggestions")
    return {"titles": titles}


@router.post("/start", response_model=RunIdResponse)
def start_discovery(body: DiscoveryStartRequest):
    config = _build_config(body)
    run_id = broker.new_run()
    stop_event = threading.Event()
    _active_stop_events[run_id] = stop_event
    threading.Thread(target=_discovery_worker, args=(run_id, config, stop_event), daemon=True).start()
    return {"run_id": run_id}


@router.get("/stream/{run_id}")
async def stream_discovery(run_id: str, request: Request):
    last_event_id = parse_last_event_id(request.headers.get("last-event-id"))
    return StreamingResponse(broker.stream(run_id, last_event_id), media_type="text/event-stream")


@router.post("/stop/{run_id}")
def stop_discovery(run_id: str):
    ev = _active_stop_events.get(run_id)
    if ev:
        ev.set()
    return {"ok": True}


@jobs_router.get("", response_model=list[JobOut])
def list_jobs():
    return [_job_to_out(j) for j in run_state.list_jobs()]


@jobs_router.get("/previous", response_model=list[JobOut])
def list_previous_jobs():
    if not DISCOVERED_JSON.exists():
        return []
    all_jobs = json.loads(DISCOVERED_JSON.read_text(encoding="utf-8"))

    seen, jobs = {}, []
    for j in all_jobs:
        key = _job_key(j)
        if key not in seen:
            seen[key] = True
            jobs.append(j)

    prev_statuses = get_job_statuses()
    skip_statuses = {"Applied", "Rejected"}
    jobs = [j for j in jobs if prev_statuses.get(_job_key(j)) not in skip_statuses]

    jobs.sort(key=lambda j: (-((j.get("ats") or {}).get("score") or 0), -(j.get("priority") or 0)))
    return [_job_to_out(j) for j in jobs]


@jobs_router.post("/select")
def select_jobs(body: JobSelectRequest):
    by_key: dict[str, dict] = {}
    if DISCOVERED_JSON.exists():
        all_jobs = json.loads(DISCOVERED_JSON.read_text(encoding="utf-8"))
        for j in all_jobs:
            by_key[_job_key(j)] = j  # last occurrence wins, same as update_from_discovered

    selected = {}
    for key in body.job_keys:
        job = run_state.jobs.get(key) or by_key.get(key)
        if job:
            selected[key] = job

    run_state.replace_jobs(selected)
    run_state.stage = "tailoring_resumes"
    run_state.save()
    return {"ok": True, "count": len(selected)}


@jobs_router.post("/{job_key}/reject")
def reject_job(job_key: str):
    job = _find_job_by_key(job_key)
    if not job:
        raise HTTPException(404, "job not found")
    # Guarantee the tracker has a row for this job before updating its Status —
    # update_job_status() is a silent no-op if the link isn't in the sheet yet
    # (e.g. a job discovered in this run before the post-discovery Excel sync ran).
    if job_key not in get_job_statuses():
        update_from_discovered()
    update_job_status(job.get("link", ""), "Rejected")
    run_state.jobs.pop(job_key, None)
    return {"ok": True}
