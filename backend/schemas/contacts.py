from pydantic import BaseModel


class FindContactsRequest(BaseModel):
    job_keys: list[str] | None = None


class ContactSummary(BaseModel):
    job_key: str
    company: str
    title: str
    contact_name: str | None = None
    contact_title: str | None = None
    contact_email: str | None = None
    source: str | None = None
    status: str  # "found" | "not_found"


class SetContactRequest(BaseModel):
    name: str = ""
    title: str = ""
    email: str
