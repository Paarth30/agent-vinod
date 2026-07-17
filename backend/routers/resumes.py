import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse

import config as cfg
from steps.step1_discover import _job_key
from steps.step2_resume import _tailor, _apply_feedback, _ats_score, _save_resume

from backend.schemas.resumes import TailorRequest, ResumeSummary, ResumeDetail, FeedbackRequest
from backend.schemas.jobs import RunIdResponse
from backend.services.run_state import run_state
from backend.services.sse import broker, parse_last_event_id
from backend.services.diffing import build_diff
from backend.services.claude_client import get_client
from backend.services.thread_safety import com_initialized

router = APIRouter(prefix="/api/resumes", tags=["resumes"])

RESUMES_DIR = Path("data/resumes")


def _save_resume_safe(job: dict, resume_docx: Path, output_dir: Path):
    """_save_resume, but safe to call from any thread (see thread_safety.py)."""
    with com_initialized():
        _save_resume(job, resume_docx, output_dir)


def _resolve_job_keys(job_keys: list[str] | None) -> list[str]:
    if job_keys:
        return [k for k in job_keys if k in run_state.jobs]
    return list(run_state.jobs.keys())


def _status_for(job: dict) -> str:
    if job.get("_resume_text"):
        return "tailored"
    if not job.get("jd"):
        return "no_jd"
    return "original"


def _detail_for(job: dict) -> dict:
    original_text = run_state.ensure_original_resume_text()
    current = job.get("_resume_text") or original_text
    has_tailored = bool(job.get("_resume_text"))
    return {
        "job_key": _job_key(job),
        "company": job["company"],
        "title": job["title"],
        "resume_text": job.get("_resume_text"),
        "diff": build_diff(original_text, current) if (has_tailored and original_text) else [],
        "ats_before": _ats_score(original_text, job) if original_text else {},
        "ats_after": _ats_score(current, job) if original_text else {},
    }


def _find_job_or_404(job_key: str) -> dict:
    job = run_state.get(job_key)
    if not job:
        raise HTTPException(404, "job not found in current run")
    return job


def _tailor_worker(run_id: str, job_keys: list[str]):
    run_state.active_resume_run_id = run_id
    try:
        client = get_client()
        original_text = run_state.ensure_original_resume_text()
        resume_docx = Path(cfg.RESUME_DOCX_PATH)
        jobs = [run_state.jobs[k] for k in job_keys if k in run_state.jobs]

        for i, job in enumerate(jobs, 1):
            key = _job_key(job)
            if not job.get("jd"):
                job["_resume_text"] = None
                broker.publish(run_id, {
                    "type": "progress", "index": i, "total": len(jobs), "job_key": key,
                    "company": job["company"], "title": job["title"], "message": "no JD, using original",
                })
                continue

            text = _tailor(client, original_text, job)
            if not text:
                job["_resume_text"] = None
                broker.publish(run_id, {
                    "type": "progress", "index": i, "total": len(jobs), "job_key": key,
                    "company": job["company"], "title": job["title"], "message": "Claude returned empty, using original",
                })
                continue

            job["_resume_text"] = text
            before = _ats_score(original_text, job)
            after = _ats_score(text, job)
            _save_resume_safe(job, resume_docx, RESUMES_DIR)
            broker.publish(run_id, {
                "type": "progress", "index": i, "total": len(jobs), "job_key": key,
                "company": job["company"], "title": job["title"],
                "ats_before": before.get("score"), "ats_after": after.get("score"),
            })

        run_state.stage = "reviewing_resumes"
        run_state.save()
        broker.finish(run_id, {"type": "done", "count": len(jobs)})
    except Exception as e:
        broker.finish(run_id, {"type": "error", "message": str(e)})
    finally:
        if run_state.active_resume_run_id == run_id:
            run_state.active_resume_run_id = None


@router.post("/tailor", response_model=RunIdResponse)
def tailor_resumes(body: TailorRequest):
    job_keys = _resolve_job_keys(body.job_keys)
    if not job_keys:
        raise HTTPException(400, "No jobs selected")
    run_id = broker.new_run()
    threading.Thread(target=_tailor_worker, args=(run_id, job_keys), daemon=True).start()
    return {"run_id": run_id}


@router.get("/stream/{run_id}")
async def stream_tailoring(run_id: str, request: Request):
    last_event_id = parse_last_event_id(request.headers.get("last-event-id"))
    return StreamingResponse(broker.stream(run_id, last_event_id), media_type="text/event-stream")


@router.get("", response_model=list[ResumeSummary])
def list_resumes():
    original_text = run_state.ensure_original_resume_text()
    out = []
    for job in run_state.list_jobs():
        text = job.get("_resume_text")
        ats_before = _ats_score(original_text, job).get("score") if original_text else None
        ats_after = _ats_score(text, job).get("score") if (text and original_text) else ats_before
        out.append({
            "job_key": _job_key(job), "company": job["company"], "title": job["title"],
            "ats_before": ats_before, "ats_after": ats_after, "status": _status_for(job),
        })
    return out


@router.get("/{job_key}", response_model=ResumeDetail)
def get_resume_detail(job_key: str):
    return _detail_for(_find_job_or_404(job_key))


@router.get("/{job_key}/pdf")
def get_resume_pdf(job_key: str):
    """Serves the tailored resume file so the frontend can preview it before
    it's used to apply. Falls back to the .docx if PDF conversion failed
    (e.g. Word isn't installed) — better an editable file than nothing."""
    job = _find_job_or_404(job_key)
    pdf_path = job.get("resume_pdf")
    if pdf_path and Path(pdf_path).exists():
        return FileResponse(pdf_path, media_type="application/pdf", filename=Path(pdf_path).name)
    docx_path = job.get("resume_docx")
    if docx_path and Path(docx_path).exists():
        return FileResponse(
            docx_path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=Path(docx_path).name,
        )
    raise HTTPException(404, "No resume file available yet for this job")


@router.post("/{job_key}/feedback", response_model=ResumeDetail)
def resume_feedback(job_key: str, body: FeedbackRequest):
    job = _find_job_or_404(job_key)
    original_text = run_state.ensure_original_resume_text()
    current = job.get("_resume_text") or original_text
    revised = _apply_feedback(get_client(), current, body.feedback, job)
    if revised:
        job["_resume_text"] = revised
        _save_resume_safe(job, Path(cfg.RESUME_DOCX_PATH), RESUMES_DIR)
    return _detail_for(job)


@router.post("/{job_key}/regen", response_model=ResumeDetail)
def resume_regen(job_key: str):
    job = _find_job_or_404(job_key)
    original_text = run_state.ensure_original_resume_text()
    regenerated = _tailor(get_client(), original_text, job)
    if regenerated:
        job["_resume_text"] = regenerated
        _save_resume_safe(job, Path(cfg.RESUME_DOCX_PATH), RESUMES_DIR)
    return _detail_for(job)


@router.post("/{job_key}/skip", response_model=ResumeDetail)
def resume_skip(job_key: str):
    job = _find_job_or_404(job_key)
    job["_resume_text"] = None
    _save_resume_safe(job, Path(cfg.RESUME_DOCX_PATH), RESUMES_DIR)
    return _detail_for(job)


@router.post("/proceed")
def resume_proceed():
    run_state.stage = "tailoring_letters"
    run_state.save()
    return {"ok": True}
