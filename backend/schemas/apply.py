from pydantic import BaseModel


class ApplyStartRequest(BaseModel):
    job_keys: list[str] | None = None
    methods: list[str] | None = None


class ApplySummary(BaseModel):
    job_key: str
    company: str
    title: str
    link: str = ""
    status: str  # "pending" | "applied" | "failed" | "needs_manual" | "no_method"
    methods_sent: list[str] = []
    methods_failed: list[str] = []


class ResolveManualRequest(BaseModel):
    applied: bool


class PendingManual(BaseModel):
    job_key: str
    company: str
    title: str
    link: str
