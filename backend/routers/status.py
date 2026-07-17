from fastapi import APIRouter

from steps.step_excel import update_from_discovered
from backend.services.run_state import run_state

router = APIRouter(prefix="/api", tags=["status"])


@router.get("/status")
def get_status():
    return {
        "run_id": run_state.run_id,
        "stage": run_state.stage,
        "job_count": len(run_state.jobs),
        "active_discovery_run_id": run_state.active_discovery_run_id,
        "active_resume_run_id": run_state.active_resume_run_id,
        "active_letter_run_id": run_state.active_letter_run_id,
        "active_contacts_run_id": run_state.active_contacts_run_id,
        "active_apply_run_id": run_state.active_apply_run_id,
    }


@router.post("/excel/sync")
def sync_excel():
    count = update_from_discovered()
    return {"ok": True, "count": count}
