import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
HUNTER_API_KEY = os.getenv("HUNTER_API_KEY")
APOLLO_API_KEY = os.getenv("APOLLO_API_KEY")

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

LINKEDIN_EMAIL = os.getenv("LINKEDIN_EMAIL")
LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD")

JOB_TITLES = [t.strip() for t in os.getenv("JOB_TITLES", "").split(",") if t.strip()]
JOB_LOCATIONS = [l.strip() for l in os.getenv("JOB_LOCATION", "India").split(",") if l.strip()]
JOB_WORK_TYPES = [w.strip() for w in os.getenv("JOB_WORK_TYPE", "Remote,Hybrid").split(",") if w.strip()]
JOB_KEYWORDS = [k.strip() for k in os.getenv("JOB_KEYWORDS", "").split(",") if k.strip()]
MAX_JOBS_PER_RUN = int(os.getenv("MAX_JOBS_PER_RUN", "20"))
JOB_EXPERIENCE = os.getenv("JOB_EXPERIENCE", "any")
MIN_ATS_SCORE = int(os.getenv("MIN_ATS_SCORE", "50"))
MIN_YEARS_EXPERIENCE = int(os.getenv("MIN_YEARS_EXPERIENCE")) if os.getenv("MIN_YEARS_EXPERIENCE") else None
MAX_YEARS_EXPERIENCE = int(os.getenv("MAX_YEARS_EXPERIENCE")) if os.getenv("MAX_YEARS_EXPERIENCE") else None

# ── Job priority scores (higher = shown first) ────────────────────────────────
# Change these numbers at any time to re-order which jobs get processed first.
JOB_PRIORITY = {
    "remote":  100,   # highest priority — no location restriction
    "hybrid":   50,   # mid priority — Noida / Delhi / Gurugram only
    "on-site":  10,   # lowest priority — Noida only
}

# ── Location allow-lists per work type ────────────────────────────────────────
# Jobs whose location doesn't match ANY keyword here are filtered out.
# Remote jobs have no restriction (empty list = allow all).
# On-site/hybrid cities are .env-driven (ONSITE_LOCATIONS / HYBRID_LOCATIONS) so a
# different user/city just needs a config change, not a code edit. Independent of
# the Discovery form's search-location field on purpose. Defaults below preserve
# the original Noida-on-site / Delhi-NCR-hybrid behavior.
ONSITE_LOCATIONS = [l.strip().lower() for l in os.getenv("ONSITE_LOCATIONS", "Noida").split(",") if l.strip()]
HYBRID_LOCATIONS = [l.strip().lower() for l in os.getenv("HYBRID_LOCATIONS", "Noida,Delhi,Gurugram,Gurgaon").split(",") if l.strip()]

JOB_LOCATION_RULES = {
    "remote":  [],                  # anywhere
    "hybrid":  HYBRID_LOCATIONS,
    "on-site": ONSITE_LOCATIONS,
}


RESUME_PATH = os.path.join(os.path.dirname(__file__), "data", "resume.pdf")
RESUME_DOCX_PATH = ""  # set at runtime by main.py after scanning data/
APPLICATIONS_PATH = os.path.join(os.path.dirname(__file__), "data", "applications.json")


def validate():
    missing = []
    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        missing.append("EMAIL_ADDRESS / EMAIL_PASSWORD")
    if not LINKEDIN_EMAIL or not LINKEDIN_PASSWORD:
        missing.append("LINKEDIN_EMAIL / LINKEDIN_PASSWORD")
    if not JOB_TITLES:
        missing.append("JOB_TITLES")
    if missing:
        raise EnvironmentError(f"Missing required .env values: {', '.join(missing)}")
