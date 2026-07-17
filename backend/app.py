import sys
import os

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config as cfg
from backend.routers import discovery, resumes, coverletters, contacts, apply, status, quick_apply
from backend.services.browser_worker import browser_worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Same resume-file scan main.py does at startup — every reused step function
    # that reads cfg.RESUME_DOCX_PATH depends on this being set.
    docx_files = sorted(Path("data").glob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
    if docx_files:
        cfg.RESUME_DOCX_PATH = str(docx_files[0])

    yield

    if browser_worker.started:
        browser_worker.stop()


app = FastAPI(title="Agent Vinod API", lifespan=lifespan)

# Local single-user tool — permissive CORS so the Vite dev server (a different
# port) can call the API directly if its proxy doesn't cover something (e.g. SSE).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(discovery.router)
app.include_router(discovery.jobs_router)
app.include_router(resumes.router)
app.include_router(coverletters.router)
app.include_router(contacts.router)
app.include_router(apply.router)
app.include_router(status.router)
app.include_router(quick_apply.router)
