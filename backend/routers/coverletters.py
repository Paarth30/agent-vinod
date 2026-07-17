import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from steps.step1_discover import _job_key
from steps.step3_coverletter import _generate, _apply_feedback, _letter_kw_score, _save_letter, _read_resume_text

from backend.schemas.coverletters import GenerateRequest, LetterSummary, LetterDetail, FeedbackRequest
from backend.schemas.jobs import RunIdResponse
from backend.services.run_state import run_state
from backend.services.sse import broker, parse_last_event_id
from backend.services.diffing import build_diff
from backend.services.claude_client import get_client

router = APIRouter(prefix="/api/letters", tags=["letters"])

LETTERS_DIR = Path("data/cover_letters")


def _resolve_job_keys(job_keys: list[str] | None) -> list[str]:
    if job_keys:
        return [k for k in job_keys if k in run_state.jobs]
    return list(run_state.jobs.keys())


def _find_job_or_404(job_key: str) -> dict:
    job = run_state.get(job_key)
    if not job:
        raise HTTPException(404, "job not found in current run")
    return job


def _detail_for(job: dict) -> dict:
    current = job.get("_letter_text")
    return {
        "job_key": _job_key(job),
        "company": job["company"],
        "title": job["title"],
        "letter_text": current,
        "diff": [],
        "score": _letter_kw_score(current, job) if current else {},
    }


def _generate_worker(run_id: str, job_keys: list[str]):
    run_state.active_letter_run_id = run_id
    try:
        client = get_client()
        jobs = [run_state.jobs[k] for k in job_keys if k in run_state.jobs]
        resume_text = _read_resume_text(jobs)

        for i, job in enumerate(jobs, 1):
            key = _job_key(job)
            letter = _generate(client, resume_text, job)
            if not letter:
                job["_letter_text"] = None
                broker.publish(run_id, {
                    "type": "progress", "index": i, "total": len(jobs), "job_key": key,
                    "company": job["company"], "title": job["title"], "message": "Claude returned empty, skipping",
                })
                continue

            job["_letter_text"] = letter
            s = _letter_kw_score(letter, job)
            _save_letter(job, LETTERS_DIR)
            broker.publish(run_id, {
                "type": "progress", "index": i, "total": len(jobs), "job_key": key,
                "company": job["company"], "title": job["title"],
                "score": s.get("score"), "label": s.get("label"),
            })

        run_state.stage = "reviewing_letters"
        run_state.save()
        broker.finish(run_id, {"type": "done", "count": len(jobs)})
    except Exception as e:
        broker.finish(run_id, {"type": "error", "message": str(e)})
    finally:
        if run_state.active_letter_run_id == run_id:
            run_state.active_letter_run_id = None


@router.post("/generate", response_model=RunIdResponse)
def generate_letters(body: GenerateRequest):
    job_keys = _resolve_job_keys(body.job_keys)
    if not job_keys:
        raise HTTPException(400, "No jobs selected")
    run_id = broker.new_run()
    threading.Thread(target=_generate_worker, args=(run_id, job_keys), daemon=True).start()
    return {"run_id": run_id}


@router.get("/stream/{run_id}")
async def stream_generation(run_id: str, request: Request):
    last_event_id = parse_last_event_id(request.headers.get("last-event-id"))
    return StreamingResponse(broker.stream(run_id, last_event_id), media_type="text/event-stream")


@router.get("", response_model=list[LetterSummary])
def list_letters():
    out = []
    for job in run_state.list_jobs():
        letter = job.get("_letter_text")
        s = _letter_kw_score(letter, job) if letter else {}
        out.append({
            "job_key": _job_key(job), "company": job["company"], "title": job["title"],
            "keyword_score": s.get("score"), "keyword_label": s.get("label"),
            "status": "ready" if letter else "skipped",
        })
    return out


@router.get("/{job_key}", response_model=LetterDetail)
def get_letter_detail(job_key: str):
    return _detail_for(_find_job_or_404(job_key))


@router.post("/{job_key}/feedback", response_model=LetterDetail)
def letter_feedback(job_key: str, body: FeedbackRequest):
    job = _find_job_or_404(job_key)
    current = job.get("_letter_text") or ""
    revised = _apply_feedback(get_client(), current, body.feedback, job)
    detail_diff = build_diff(current, revised) if revised else []
    if revised:
        job["_letter_text"] = revised
        _save_letter(job, LETTERS_DIR)
    detail = _detail_for(job)
    detail["diff"] = detail_diff
    return detail


@router.post("/{job_key}/regen", response_model=LetterDetail)
def letter_regen(job_key: str):
    job = _find_job_or_404(job_key)
    previous = job.get("_letter_text") or ""
    resume_text = _read_resume_text([job])
    regenerated = _generate(get_client(), resume_text, job)
    detail_diff = build_diff(previous, regenerated) if (regenerated and previous) else []
    if regenerated:
        job["_letter_text"] = regenerated
        _save_letter(job, LETTERS_DIR)
    detail = _detail_for(job)
    detail["diff"] = detail_diff
    return detail


@router.post("/{job_key}/skip", response_model=LetterDetail)
def letter_skip(job_key: str):
    job = _find_job_or_404(job_key)
    job["_letter_text"] = None
    _save_letter(job, LETTERS_DIR)
    return _detail_for(job)


@router.post("/proceed")
def letter_proceed():
    run_state.stage = "finding_contacts"
    run_state.save()
    return {"ok": True}
