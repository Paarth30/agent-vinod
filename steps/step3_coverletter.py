import difflib
import hashlib
import re
from pathlib import Path
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
import anthropic
import config as cfg
from steps.step1_discover import _job_key
from steps.llm import gemini_call
from steps.scoring import top_jd_keywords

console = Console()


def run(jobs: list[dict]) -> list[dict]:
    console.print("\n[bold]Step 3: Cover Letter Generation[/bold]")

    client = anthropic.Anthropic(api_key=cfg.GEMINI_API_KEY)
    out_dir = Path("data/cover_letters")
    out_dir.mkdir(exist_ok=True)

    resume_text = _read_resume_text(jobs)

    # ── Phase 1: write every letter back-to-back, no prompts ────────────────
    console.print(f"  Writing {len(jobs)} cover letter(s)...\n")
    for i, job in enumerate(jobs, 1):
        letter = _generate(client, resume_text, job)
        if not letter:
            console.print(f"  [{i}/{len(jobs)}] [yellow]{job['company']} — Claude returned empty, skipping[/yellow]")
            job["_letter_text"] = None
            continue

        job["_letter_text"] = letter
        s = _letter_kw_score(letter, job)
        score_str = f"{s['score']}% {s['label']}" if s else "n/a"
        console.print(f"  [{i}/{len(jobs)}] [green]OK[/green] {job['company']} — {job['title']}  Keyword match: {score_str}")

    for job in jobs:
        _save_letter(job, out_dir)

    # ── Phase 2: review list — open a specific one to see it and chat ──────
    _review_loop(jobs, client, resume_text, out_dir)

    if not Confirm.ask("\n[bold green]Cover letters ready — proceed to finding contacts?[/bold green]"):
        console.print("[red]Aborted.[/red]")
        raise SystemExit(0)

    return jobs


def _save_letter(job: dict, out_dir: Path):
    current = job.get("_letter_text")
    if not current:
        job["cover_letter"] = None
        job["cover_letter_path"] = None
        return

    def _safe(s):
        return "".join(c if c.isalnum() or c in "-_ " else "" for c in s).strip().replace(" ", "_")[:50]

    key_hash = hashlib.md5(_job_key(job).encode()).hexdigest()[:8]
    path = out_dir / f"{_safe(job['company'])}_{_safe(job['title'])}_{key_hash}.txt"
    path.write_text(current, encoding="utf-8")
    job["cover_letter"] = current
    job["cover_letter_path"] = str(path)


def _review_loop(jobs: list[dict], client, resume_text: str, out_dir: Path):
    while True:
        _show_letters_table(jobs)
        console.print(
            "\n  [dim]Enter a job number to review/edit its cover letter, "
            "or press Enter to accept all and continue.[/dim]"
        )
        choice = Prompt.ask("  Selection", default="").strip()

        if not choice or choice.lower() == "done":
            return
        if not choice.isdigit() or not (1 <= int(choice) <= len(jobs)):
            console.print("[yellow]  Invalid selection.[/yellow]")
            continue

        _review_letter_job(jobs[int(choice) - 1], client, resume_text, out_dir)


def _show_letters_table(jobs: list[dict]):
    t = Table(title="Cover Letters", show_lines=True)
    t.add_column("#", style="cyan", width=4)
    t.add_column("Company", style="yellow")
    t.add_column("Title", style="white")
    t.add_column("Keyword Match")
    t.add_column("Status")

    for i, job in enumerate(jobs, 1):
        letter = job.get("_letter_text")
        if letter is None:
            t.add_row(str(i), job["company"], job["title"], "[dim]n/a[/dim]", "[red]Skipped[/red]")
            continue
        s = _letter_kw_score(letter, job)
        score_str = f"{s['score']}% {s['label']}" if s else "n/a"
        t.add_row(str(i), job["company"], job["title"], score_str, "[green]Ready[/green]")

    console.print("\n", t)


def _review_letter_job(job: dict, client, resume_text: str, out_dir: Path):
    current = job.get("_letter_text")
    if current is None:
        console.print("[yellow]  No cover letter for this job — nothing to review.[/yellow]")
        return

    prev = None
    while True:
        if prev is None:
            console.print(Panel(current, title=f"[dim]Cover Letter — {job['company']}[/dim]", expand=False))
        else:
            _show_diff(prev, current)

        _show_letter_score(current, job)
        console.print(
            "\n  [dim]Type feedback to refine (e.g. 'make the opening punchier'), "
            "[cyan]regen[/cyan] to regenerate from scratch, [cyan]skip[/cyan] to drop the letter, "
            "or press Enter to go back to the list.[/dim]"
        )
        action = Prompt.ask("  Feedback", default="").strip()

        if not action or action.lower() == "done":
            break
        elif action.lower() == "skip":
            current = None
            break
        elif action.lower() == "regen":
            console.print("  [dim]Regenerating...[/dim]")
            new = _generate(client, resume_text, job)
            if new:
                prev = current
                current = new
            else:
                console.print("[yellow]  Regeneration failed — keeping current version.[/yellow]")
        else:
            console.print("  [dim]Applying your changes...[/dim]")
            revised = _apply_feedback(client, current, action, job)
            if revised:
                prev = current
                current = revised
            else:
                console.print("[yellow]  Edit failed — keeping current version.[/yellow]")

    job["_letter_text"] = current
    _save_letter(job, out_dir)
    if current is None:
        console.print("  [yellow]Dropped — will apply without a cover letter for this job.[/yellow]")
    else:
        console.print(f"  [green]OK[/green] Saved to [dim]{job.get('cover_letter_path')}[/dim]")


# ── Letter keyword score ───────────────────────────────────────────────────────

def _letter_kw_score(letter: str, job: dict) -> dict:
    """How many of the top JD keywords appear in the cover letter."""
    jd = job.get("jd", "")
    if not jd or not letter:
        return {}
    top_kw   = top_jd_keywords(jd, 30)
    letter_l = letter.lower()
    matched  = [w for w in top_kw if w in letter_l]
    score    = round(len(matched) / max(len(top_kw), 1) * 100)
    label    = "Excellent" if score >= 80 else "Good" if score >= 65 else "Fair" if score >= 50 else "Low"
    return {
        "score":   score,
        "label":   label,
        "matched": len(matched),
        "total":   len(top_kw),
        "missing": [w for w in top_kw if w not in letter_l][:6],
    }


def _show_letter_score(letter: str, job: dict):
    s = _letter_kw_score(letter, job)
    if not s:
        return
    color = {"Excellent": "green", "Good": "cyan", "Fair": "yellow", "Low": "red"}.get(s["label"], "white")
    score_line = (
        f"  Keyword match: [{color}]{s['score']}% — {s['label']}[/{color}]"
        f"  ([dim]{s['matched']}/{s['total']} JD keywords covered[/dim])"
    )
    console.print(score_line)
    if s["missing"]:
        console.print(f"  [dim]Missing: {', '.join(s['missing'])}[/dim]")


# ── Diff display ───────────────────────────────────────────────────────────────

def _show_diff(before: str, after: str):
    diff = list(difflib.unified_diff(
        before.splitlines(), after.splitlines(), lineterm="", n=2
    ))
    if not diff:
        console.print(Panel("[dim]No changes.[/dim]", title="Diff", expand=False))
        return
    rich_text = Text()
    for line in diff[2:]:
        if line.startswith("+"):
            rich_text.append(line + "\n", style="green")
        elif line.startswith("-"):
            rich_text.append(line + "\n", style="red strike")
        elif line.startswith("@@"):
            rich_text.append(line + "\n", style="cyan dim")
        else:
            rich_text.append(line + "\n", style="dim")
    console.print(Panel(rich_text, title="[bold][red]-removed[/red]  [green]+added[/green][/bold]", expand=False))


# ── Claude calls ───────────────────────────────────────────────────────────────

def _generate(client, resume_text: str, job: dict) -> str:
    prompt = f"""You are an expert job application writer. Write a short, punchy cover letter.

Job Title: {job['title']}
Company: {job['company']}
Job Description:
{job.get('jd', 'Not available')[:2000]}

Candidate's Resume:
{resume_text[:2000]}

Rules — follow strictly:
- MAXIMUM 150 words total. Short is better. Do not pad.
- 3 tight paragraphs only:
    1. Opening (1-2 sentences): specific hook — why this role at this company, right now.
    2. Value (2-3 sentences): 1-2 concrete achievements from the resume that directly match this JD. Numbers where possible.
    3. Close (1 sentence): clear, confident call to action.
- Tone: direct, human, confident — not corporate or sycophantic.
- Do NOT start with "I am writing to apply for..."
- Do NOT include [placeholders], subject lines, or sign-offs — output the letter body only.
"""
    return gemini_call(client, prompt, max_tokens=1024).strip()


def _apply_feedback(client, current: str, feedback: str, job: dict) -> str:
    prompt = f"""You are editing a cover letter for a {job['title']} role at {job['company']}.

Current letter:
<letter>
{current}
</letter>

Candidate's feedback:
<feedback>
{feedback}
</feedback>

Apply the feedback precisely. Do not change anything not mentioned in the feedback.
Keep the letter under 150 words and output ONLY the updated letter body — no commentary.
"""
    return gemini_call(client, prompt, max_tokens=1024).strip()



def _read_resume_text(jobs: list[dict]) -> str:
    for job in jobs:
        p = job.get("resume_docx") or cfg.RESUME_DOCX_PATH
        path = Path(p)
        if path.exists():
            try:
                from docx import Document
                doc = Document(str(path))
                return "\n".join(para.text for para in doc.paragraphs if para.text.strip())
            except Exception:
                pass
    return ""
