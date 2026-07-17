import threading

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from steps.step1_discover import _job_key
from steps.step4_contacts import _guess_domain, _hunter_search, _apollo_search, _permutation_search
import config as cfg

from backend.schemas.contacts import FindContactsRequest, ContactSummary, SetContactRequest
from backend.schemas.jobs import RunIdResponse
from backend.services.run_state import run_state
from backend.services.sse import broker, parse_last_event_id

router = APIRouter(prefix="/api/contacts", tags=["contacts"])


def _resolve_job_keys(job_keys: list[str] | None) -> list[str]:
    if job_keys:
        return [k for k in job_keys if k in run_state.jobs]
    return list(run_state.jobs.keys())


def _find_job_or_404(job_key: str) -> dict:
    job = run_state.get(job_key)
    if not job:
        raise HTTPException(404, "job not found in current run")
    return job


def _find_contact_for(job: dict) -> dict | None:
    domain = _guess_domain(job["company"])
    contact = None
    if cfg.HUNTER_API_KEY:
        contact = _hunter_search(job["company"], domain)
    if not contact and cfg.APOLLO_API_KEY:
        contact = _apollo_search(job["company"])
    if not contact and domain:
        contact = _permutation_search(domain)
    return contact


def _summary_for(job: dict) -> dict:
    contact = job.get("contact")
    return {
        "job_key": _job_key(job),
        "company": job["company"],
        "title": job["title"],
        "contact_name": (contact or {}).get("name") or None,
        "contact_title": (contact or {}).get("title") or None,
        "contact_email": (contact or {}).get("email") if contact else None,
        "source": (contact or {}).get("source") if contact else None,
        "status": "found" if contact else "not_found",
    }


def _find_contacts_worker(run_id: str, job_keys: list[str]):
    run_state.active_contacts_run_id = run_id
    run_state.stage = "finding_contacts"
    run_state.save()
    try:
        jobs = [run_state.jobs[k] for k in job_keys if k in run_state.jobs]
        for i, job in enumerate(jobs, 1):
            key = _job_key(job)
            contact = _find_contact_for(job)
            job["contact"] = contact
            broker.publish(run_id, {
                "type": "progress", "index": i, "total": len(jobs), "job_key": key,
                "company": job["company"], "title": job["title"],
                "message": f"found {contact['email']}" if contact else "no HR/recruiter contact found",
            })
        run_state.stage = "reviewing_contacts"
        run_state.save()
        broker.finish(run_id, {"type": "done", "count": len(jobs)})
    except Exception as e:
        run_state.stage = "reviewing_contacts"
        run_state.save()
        broker.finish(run_id, {"type": "error", "message": str(e)})
    finally:
        if run_state.active_contacts_run_id == run_id:
            run_state.active_contacts_run_id = None


@router.post("/find", response_model=RunIdResponse)
def find_contacts(body: FindContactsRequest):
    job_keys = _resolve_job_keys(body.job_keys)
    if not job_keys:
        raise HTTPException(400, "No jobs selected")
    run_id = broker.new_run()
    threading.Thread(target=_find_contacts_worker, args=(run_id, job_keys), daemon=True).start()
    return {"run_id": run_id}


@router.get("/stream/{run_id}")
async def stream_contacts(run_id: str, request: Request):
    last_event_id = parse_last_event_id(request.headers.get("last-event-id"))
    return StreamingResponse(broker.stream(run_id, last_event_id), media_type="text/event-stream")


@router.get("", response_model=list[ContactSummary])
def list_contacts():
    return [_summary_for(job) for job in run_state.list_jobs()]


@router.post("/{job_key}/refresh", response_model=ContactSummary)
def refresh_contact(job_key: str):
    job = _find_job_or_404(job_key)
    job["contact"] = _find_contact_for(job)
    run_state.save()
    return _summary_for(job)


@router.post("/{job_key}/set", response_model=ContactSummary)
def set_contact(job_key: str, body: SetContactRequest):
    """Manually specify a contact — e.g. when auto-search found no HR/recruiter
    match but you know who to reach out to. Never auto-fills a non-HR contact;
    this is an explicit, deliberate override by the user."""
    job = _find_job_or_404(job_key)
    job["contact"] = {"name": body.name, "title": body.title, "email": body.email, "source": "manual"}
    run_state.save()
    return _summary_for(job)


@router.post("/{job_key}/clear", response_model=ContactSummary)
def clear_contact(job_key: str):
    job = _find_job_or_404(job_key)
    job["contact"] = None
    run_state.save()
    return _summary_for(job)


@router.post("/proceed")
def contacts_proceed():
    run_state.stage = "applying"
    run_state.save()
    return {"ok": True}
