from pydantic import BaseModel


class DiscoveryStartRequest(BaseModel):
    titles: list[str] | None = None
    locations: list[str] | None = None
    work_types: list[str] | None = None
    max_jobs: int | None = None
    min_ats_score: int | None = None
    experience: str | None = None
    min_years: int | None = None
    max_years: int | None = None


class RunIdResponse(BaseModel):
    run_id: str


class JobSelectRequest(BaseModel):
    job_keys: list[str]


class QuickApplyStartRequest(BaseModel):
    link: str


class SuggestTitlesResponse(BaseModel):
    titles: list[str]


class JobOut(BaseModel):
    job_key: str
    title: str
    company: str
    location: str
    link: str
    work_type: str | None = None
    priority: int | None = None
    posted_text: str | None = None
    ats: dict | None = None
