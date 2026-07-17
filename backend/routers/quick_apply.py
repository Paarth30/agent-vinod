import re
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from steps import step1_discover
from steps.step1_discover import _job_key
from steps.step_excel import get_job_statuses, get_title_company_statuses

from backend.schemas.jobs import QuickApplyStartRequest, RunIdResponse
from backend.routers.discovery import _job_to_out
from backend.services.run_state import run_state
from backend.services.sse import broker, strip_rich_markup, parse_last_event_id
from backend.services.browser_worker import browser_worker

router = APIRouter(prefix="/api/quick-apply", tags=["quick-apply"])

DISCOVERED_JSON = Path("data/discovered_jobs.json")

_JOB_VIEW_RE = re.compile(r"linkedin\.com/jobs/view/\d+", re.IGNORECASE)


def _warning_for(job: dict) -> str | None:
    """Warn (but don't block) if this job is already in the tracker."""
    skip = {"Applied", "Rejected"}
    key = _job_key(job)
    tc = (job.get("title", "").strip().lower(), job.get("company", "").strip().lower())
    status = get_job_statuses().get(key) or get_title_company_statuses().get(tc)
    if status in skip:
        return f"You already marked this job {status} in a previous run."
    if DISCOVERED_JSON.exists():
        try:
            import json
            existing = {_job_key(j) for j in json.loads(DISCOVERED_JSON.read_text(encoding="utf-8"))}
            if key in existing:
                return "This job is already in your discovered list."
        except Exception:
            pass
    return None


def _quick_apply_worker(run_id: str, link: str):
    def on_progress(msg: str):
        broker.publish(run_id, {"type": "log", "message": strip_rich_markup(msg)})

    try:
        if not browser_worker.started:
            broker.publish(run_id, {"type": "log", "message": "Launching browser and logging into LinkedIn..."})
            browser_worker.start()
        job = browser_worker.submit(
            lambda: step1_discover.scrape_single_job(browser_worker.context, link, on_progress)
        )
        if not job:
            broker.finish(run_id, {"type": "error",
                                   "message": "Couldn't read that job — check the link is a public LinkedIn job posting."})
            return
        # The duplicate warning is display-only — a locked/corrupt tracker must
        # not turn a successful scrape into an error and discard the job (the
        # discovery worker guards its Excel call the same way).
        try:
            warning = _warning_for(job)
        except Exception:
            warning = None
        step1_discover._save_discovered([job])
        run_state.set_jobs([job])
        run_state.stage = "selecting"
        run_state.save()
        broker.finish(run_id, {"type": "done", "job": _job_to_out(job), "warning": warning})
    except Exception as e:
        broker.finish(run_id, {"type": "error", "message": str(e)})


@router.post("/start", response_model=RunIdResponse)
def start_quick_apply(body: QuickApplyStartRequest):
    link = (body.link or "").strip()
    if not _JOB_VIEW_RE.search(link):
        raise HTTPException(400, "Not a LinkedIn job link. Paste a linkedin.com/jobs/view/... URL.")
    run_id = broker.new_run()
    threading.Thread(target=_quick_apply_worker, args=(run_id, link), daemon=True).start()
    return {"run_id": run_id}


@router.get("/stream/{run_id}")
async def stream_quick_apply(run_id: str, request: Request):
    last_event_id = parse_last_event_id(request.headers.get("last-event-id"))
    return StreamingResponse(broker.stream(run_id, last_event_id), media_type="text/event-stream")
