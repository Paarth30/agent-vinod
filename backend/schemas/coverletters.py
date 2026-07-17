from pydantic import BaseModel


class GenerateRequest(BaseModel):
    job_keys: list[str] | None = None


class LetterSummary(BaseModel):
    job_key: str
    company: str
    title: str
    keyword_score: int | None = None
    keyword_label: str | None = None
    status: str  # "ready" | "skipped"


class LetterDetail(BaseModel):
    job_key: str
    company: str
    title: str
    letter_text: str | None
    diff: list[dict]
    score: dict


class FeedbackRequest(BaseModel):
    feedback: str
