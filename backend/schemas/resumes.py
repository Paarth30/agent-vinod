from pydantic import BaseModel


class TailorRequest(BaseModel):
    job_keys: list[str] | None = None


class ResumeSummary(BaseModel):
    job_key: str
    company: str
    title: str
    ats_before: int | None = None
    ats_after: int | None = None
    status: str  # "tailored" | "original" | "no_jd"


class ResumeDetail(BaseModel):
    job_key: str
    company: str
    title: str
    resume_text: str | None
    diff: list[dict]
    ats_before: dict
    ats_after: dict


class FeedbackRequest(BaseModel):
    feedback: str
