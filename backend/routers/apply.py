import threading

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from steps.step1_discover import _job_key
from steps.step5_apply import _send_email, _linkedin_easy_apply
from steps.step_excel import update_job_status
from steps import step6_track

from backend.schemas.apply import ApplyStartRequest, ApplySummary, ResolveManualRequest, PendingManual
from backend.schemas.jobs import RunIdResponse
from backend.services.run_state import run_state
from backend.services.sse import broker, parse_last_event_id
from backend.services.browser_worker import browser_worker

router = APIRouter(prefix="/api/apply", tags=["apply"])

# job_key -> threading.Event, only while that job is waiting on a manual-apply
# decision from the frontend. In-memory only, same reasoning as the
# active_*_run_id fields — a backend restart means that browser tab/thread is
# gone anyway, so there's nothing to resume across a restart.
_PENDING_MANUAL: dict[str, threading.Event] = {}
_PENDING_MANUAL_RESULT: dict[str, bool] = {}
_PENDING_MANUAL_JOB: dict[str, dict] = {}


def _resolve_job_keys(job_keys: list[str] | None) -> list[str]:
    if job_keys:
        return [k for k in job_keys if k in run_state.jobs]
    # Default to jobs not already successfully applied — never silently
    # re-send a real email / re-submit a real LinkedIn application on a
    # second "Send" click (e.g. after a partial-batch error, or adding a
    # newly-selected job later). Jobs that were attempted but failed are
    # still included, since retrying a failure is a deliberate action.
    return [k for k, j in run_state.jobs.items() if not j.get("applied")]


def _find_job_or_404(job_key: str) -> dict:
    job = run_state.get(job_key)
    if not job:
        raise HTTPException(404, "job not found in current run")
    return job


def _summary_for(job: dict) -> dict:
    key = _job_key(job)
    results = job.get("application_results")
    if key in _PENDING_MANUAL:
        status = "needs_manual"
    elif results is None:
        status = "pending"
    elif job.get("applied"):
        status = "applied"
    elif not results:
        status = "no_method"  # no contact email and not a LinkedIn posting — nothing to send
    else:
        status = "failed"
    return {
        "job_key": key,
        "company": job["company"],
        "title": job["title"],
        "link": job.get("link", ""),
        "status": status,
        "methods_sent": [m for m, ok in (results or []) if ok],
        "methods_failed": [m for m, ok in (results or []) if not ok],
    }


def _apply_one(job: dict, run_id: str, methods: list[str]):
    key = _job_key(job)
    results = []

    if "email" in methods and job.get("contact") and job["contact"].get("email"):
        ok = _send_email(job)
        results.append(("email", ok))

    email_sent = any(m == "email" and ok for m, ok in results)
    if "linkedin" in methods and not email_sent and job.get("source") == "linkedin" and job.get("link"):
        def on_wait(job):
            event = threading.Event()
            _PENDING_MANUAL[key] = event
            _PENDING_MANUAL_JOB[key] = job
            broker.publish(run_id, {
                "type": "needs_manual_apply", "job_key": key,
                "company": job["company"], "title": job["title"], "link": job.get("link", ""),
            })
            event.wait()
            _PENDING_MANUAL.pop(key, None)
            _PENDING_MANUAL_JOB.pop(key, None)
            return _PENDING_MANUAL_RESULT.pop(key, False)

        ok = browser_worker.submit(lambda: _linkedin_easy_apply(job, browser_worker.context, on_wait=on_wait))
        results.append(("linkedin", ok))

    job["application_results"] = results
    job["applied"] = any(ok for _, ok in results)
    return results


def _apply_worker(run_id: str, job_keys: list[str], methods: list[str]):
    run_state.active_apply_run_id = run_id
    try:
        if not browser_worker.started:
            broker.publish(run_id, {"type": "log", "message": "Launching browser..."})
            browser_worker.start()

        # Defensive skip even for explicitly-passed keys — a job already
        # successfully applied must never be re-applied by this worker.
        jobs = [run_state.jobs[k] for k in job_keys if k in run_state.jobs and not run_state.jobs[k].get("applied")]
        for i, job in enumerate(jobs, 1):
            key = _job_key(job)
            broker.publish(run_id, {
                "type": "log", "message": f"[{i}/{len(jobs)}] Applying to {job['title']} at {job['company']}...",
            })
            results = _apply_one(job, run_id, methods)
            run_state.save()  # persist application_results/applied immediately, per job —
            # if the process dies partway through the batch, already-applied jobs must
            # not look "pending" again on restart and get re-applied.

            if job.get("applied"):
                try:
                    update_job_status(job.get("link", ""), "Applied")
                except Exception as e:
                    broker.publish(run_id, {"type": "log", "message": f"Warning: couldn't update tracker status ({e}) — close job_tracker.xlsx if it's open in Excel."})

            broker.publish(run_id, {
                "type": "progress", "index": i, "total": len(jobs), "job_key": key,
                "company": job["company"], "title": job["title"],
                "methods_sent": [m for m, ok in results if ok],
                "methods_failed": [m for m, ok in results if not ok],
            })

        try:
            step6_track.run(jobs)
        except Exception as e:
            broker.publish(run_id, {"type": "log", "message": f"Warning: application tracking log failed ({e})."})

        run_state.stage = "done"
        run_state.save()
        broker.finish(run_id, {"type": "done", "count": len(jobs)})
    except Exception as e:
        broker.finish(run_id, {"type": "error", "message": str(e)})
    finally:
        if run_state.active_apply_run_id == run_id:
            run_state.active_apply_run_id = None


@router.post("/start", response_model=RunIdResponse)
def start_apply(body: ApplyStartRequest):
    job_keys = _resolve_job_keys(body.job_keys)
    if not job_keys:
        raise HTTPException(400, "No jobs selected")
    methods = body.methods or ["linkedin", "email"]
    run_id = broker.new_run()
    threading.Thread(target=_apply_worker, args=(run_id, job_keys, methods), daemon=True).start()
    return {"run_id": run_id}


@router.get("/stream/{run_id}")
async def stream_apply(run_id: str, request: Request):
    last_event_id = parse_last_event_id(request.headers.get("last-event-id"))
    return StreamingResponse(broker.stream(run_id, last_event_id), media_type="text/event-stream")


@router.get("", response_model=list[ApplySummary])
def list_apply():
    return [_summary_for(job) for job in run_state.list_jobs()]


@router.get("/pending", response_model=list[PendingManual])
def list_pending_manual():
    """Jobs currently waiting on a manual-apply decision — lets the frontend
    show these again after navigating away and back, same as any other
    in-flight run."""
    out = []
    for key, job in _PENDING_MANUAL_JOB.items():
        out.append({"job_key": key, "company": job["company"], "title": job["title"], "link": job.get("link", "")})
    return out


@router.post("/{job_key}/resolve")
def resolve_manual(job_key: str, body: ResolveManualRequest):
    event = _PENDING_MANUAL.get(job_key)
    if not event:
        raise HTTPException(404, "no pending manual apply for this job")
    _PENDING_MANUAL_RESULT[job_key] = body.applied
    event.set()
    return {"ok": True}
