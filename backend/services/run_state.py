"""Process-wide singleton holding the current run's job list and stage.

Single-user tool -> a singleton, not a history table (starting a new discovery
run overwrites it). Persists only what can't be derived from disk (which job
keys are selected + what stage we're at) to data/web_state/current_run.json;
everything else (job metadata, tailored resume/letter text) is reconstructed
from discovered_jobs.json and the saved .docx/.txt files, which are already
written to disk immediately by _save_resume/_save_letter.
"""
import hashlib
import json
import threading
from pathlib import Path

import config as cfg
from steps.step1_discover import _job_key

CURRENT_RUN_PATH = Path("data/web_state/current_run.json")
DISCOVERED_JSON = Path("data/discovered_jobs.json")
RESUMES_DIR = Path("data/resumes")
LETTERS_DIR = Path("data/cover_letters")

STAGES = [
    "idle", "discovering", "selecting", "tailoring_resumes", "reviewing_resumes",
    "tailoring_letters", "reviewing_letters", "finding_contacts", "reviewing_contacts",
    "applying", "done",
]


def _key_hash(job: dict) -> str:
    return hashlib.md5(_job_key(job).encode()).hexdigest()[:8]


def _find_saved_file(directory: Path, job: dict, suffix: str) -> Path | None:
    if not directory.exists():
        return None
    matches = list(directory.glob(f"*_{_key_hash(job)}{suffix}"))
    return matches[0] if matches else None


class RunState:
    def __init__(self):
        self._lock = threading.Lock()
        self.run_id: str | None = None
        self.stage: str = "idle"
        self.jobs: dict[str, dict] = {}
        self.original_resume_text: str = ""
        # In-memory only, never persisted — a backend restart always kills the
        # actual background thread doing the work, so there's nothing
        # meaningful to "resume" across a restart. These only track activity
        # within the current process, so the frontend can reconnect after
        # navigating away and back without losing the live view of a run
        # still in flight (discovery scraping, resume/letter batch tailoring).
        self.active_discovery_run_id: str | None = None
        self.active_resume_run_id: str | None = None
        self.active_letter_run_id: str | None = None
        self.active_contacts_run_id: str | None = None
        self.active_apply_run_id: str | None = None
        self._load()

    # ── persistence ──────────────────────────────────────────────────────────
    def _load(self):
        data = {}
        if CURRENT_RUN_PATH.exists():
            try:
                data = json.loads(CURRENT_RUN_PATH.read_text(encoding="utf-8"))
            except Exception:
                data = {}

        self.run_id = data.get("run_id")
        self.stage = data.get("stage", "idle")
        selected_keys = data.get("selected_job_keys", [])
        if selected_keys:
            self._reconstruct(selected_keys, data.get("contacts"), data.get("applications"))

    def save(self):
        with self._lock:
            CURRENT_RUN_PATH.parent.mkdir(parents=True, exist_ok=True)
            # Contacts and application results only ever live in-memory on the
            # job dicts (never written back to discovered_jobs.json or the
            # saved resume/letter files) — persist them here explicitly, or a
            # backend restart silently forgets who was contacted and which
            # jobs were already applied to.
            contacts = {k: j["contact"] for k, j in self.jobs.items() if j.get("contact")}
            applications = {
                k: {"application_results": j["application_results"], "applied": j.get("applied", False)}
                for k, j in self.jobs.items() if j.get("application_results") is not None
            }
            CURRENT_RUN_PATH.write_text(json.dumps({
                "run_id": self.run_id,
                "stage": self.stage,
                "selected_job_keys": list(self.jobs.keys()),
                "contacts": contacts,
                "applications": applications,
            }, indent=2), encoding="utf-8")

    def _reconstruct(self, selected_keys: list[str], contacts: dict | None = None, applications: dict | None = None):
        from steps.step2_resume import _extract_docx_text

        contacts = contacts or {}
        applications = applications or {}

        by_key: dict[str, dict] = {}
        if DISCOVERED_JSON.exists():
            try:
                records = json.loads(DISCOVERED_JSON.read_text(encoding="utf-8"))
            except Exception:
                records = []
            for r in records:
                by_key[_job_key(r)] = r  # last occurrence wins, same as update_from_discovered

        for key in selected_keys:
            record = by_key.get(key)
            if not record:
                continue
            job = dict(record)

            resume_file = _find_saved_file(RESUMES_DIR, job, ".docx")
            if resume_file:
                try:
                    job["_resume_text"] = _extract_docx_text(resume_file)
                    job["resume_docx"] = str(resume_file)
                except Exception:
                    job["_resume_text"] = None
                pdf_file = resume_file.with_suffix(".pdf")
                if pdf_file.exists():
                    job["resume_pdf"] = str(pdf_file)

            letter_file = _find_saved_file(LETTERS_DIR, job, ".txt")
            if letter_file:
                try:
                    job["_letter_text"] = letter_file.read_text(encoding="utf-8")
                    job["cover_letter"] = job["_letter_text"]
                    job["cover_letter_path"] = str(letter_file)
                except Exception:
                    job["_letter_text"] = None

            if key in contacts:
                job["contact"] = contacts[key]
            if key in applications:
                job["application_results"] = applications[key]["application_results"]
                job["applied"] = applications[key]["applied"]

            self.jobs[key] = job

    # ── mutation ─────────────────────────────────────────────────────────────
    def set_jobs(self, jobs: list[dict]):
        with self._lock:
            self.jobs = {_job_key(j): j for j in jobs}

    def set_selection(self, job_keys: list[str]):
        """Narrow run_state.jobs down to exactly this selection (jobs must already be
        present, e.g. from a prior discovery run in this process, or reconstructed)."""
        with self._lock:
            self.jobs = {k: v for k, v in self.jobs.items() if k in job_keys}

    def replace_jobs(self, jobs_by_key: dict[str, dict]):
        with self._lock:
            self.jobs = jobs_by_key

    def get(self, job_key: str) -> dict | None:
        return self.jobs.get(job_key)

    def list_jobs(self) -> list[dict]:
        return list(self.jobs.values())

    def ensure_original_resume_text(self):
        if self.original_resume_text:
            return self.original_resume_text
        from steps.step2_resume import _extract_docx_text
        path = Path(cfg.RESUME_DOCX_PATH)
        if path.exists():
            self.original_resume_text = _extract_docx_text(path)
        return self.original_resume_text


run_state = RunState()
