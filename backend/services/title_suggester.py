"""One-shot Claude call that reads the candidate's resume and suggests LinkedIn
job-title search queries actually suited to their experience level and skills —
used by the Discovery page's "Suggest roles from my resume" button so search
isn't limited to whatever titles were typed into .env."""
import json
import re


def suggest_titles(client, resume_text: str, current_titles: list[str]) -> list[str]:
    prompt = f"""You are a career advisor helping a candidate find LinkedIn job titles to search for.

Here is the candidate's resume:
<resume>
{resume_text[:4000]}
</resume>

They are currently searching for these titles: {", ".join(current_titles) or "(none yet)"}

Based on the resume's actual experience level, skills, and background, suggest 4-6 specific
job titles this candidate should search for on LinkedIn. Match their real seniority level
(e.g. do not suggest senior/lead/VP/director titles for an intern or entry-level candidate) —
suggest titles they are genuinely qualified for today, plus close adjacent roles.

Output ONLY a JSON array of strings, nothing else. Example:
["Business Analyst", "Product Analyst Intern", "Associate Product Manager"]
"""
    from steps.llm import gemini_call
    raw = gemini_call(client, prompt).strip()

    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        return []
    try:
        titles = json.loads(match.group(0))
        return [t.strip() for t in titles if isinstance(t, str) and t.strip()][:6]
    except Exception:
        return []
