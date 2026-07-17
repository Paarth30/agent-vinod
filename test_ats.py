"""
Score all previously discovered jobs against the resume using the ATS engine.
No browser, no Gemini, no LinkedIn — just reads discovered_jobs.json.
"""
import json
from pathlib import Path
from rich.console import Console
from rich.table import Table

console = Console()

# Load discovered jobs
JOBS_FILE = Path("data/discovered_jobs.json")
if not JOBS_FILE.exists():
    console.print("[red]No discovered_jobs.json found. Run the main test first.[/red]")
    raise SystemExit(1)

all_jobs = json.loads(JOBS_FILE.read_text(encoding="utf-8"))

# Deduplicate by link (multiple test runs append duplicates)
seen = set()
jobs = []
for j in all_jobs:
    key = j.get("link", j.get("title", ""))
    if key not in seen:
        seen.add(key)
        jobs.append(j)

console.print(f"\n[bold]ATS Scoring — {len(jobs)} unique jobs[/bold]")

# Load resume
from steps.step1_discover import _read_resume_text, _ats_score
import config as cfg

docx_files = sorted(Path("data").glob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
if docx_files:
    cfg.RESUME_DOCX_PATH = str(docx_files[0])
    console.print(f"  Resume: [cyan]{docx_files[0].name}[/cyan]\n")

resume_text = _read_resume_text()
if not resume_text:
    console.print("[red]Could not read resume.[/red]")
    raise SystemExit(1)

# Score all jobs
for job in jobs:
    job["ats"] = _ats_score(resume_text, job)

# Sort by ATS score descending
scored  = [j for j in jobs if j["ats"].get("score") is not None]
no_jd   = [j for j in jobs if j["ats"].get("score") is None]
scored.sort(key=lambda j: j["ats"]["score"], reverse=True)

# ── Summary table ──────────────────────────────────────────────────────────────
table = Table(title="ATS Confidence Scores", show_lines=True)
table.add_column("#",       style="cyan", width=3)
table.add_column("Company", style="yellow")
table.add_column("Title",   style="white")
table.add_column("Type",    width=8)
table.add_column("Score",   width=14)
table.add_column("Skills", style="dim")
table.add_column("KW",     style="dim", width=4)
table.add_column("Exp",    style="dim", width=4)
table.add_column("Edu",    style="dim", width=4)

for i, job in enumerate(scored, 1):
    ats  = job["ats"]
    sc   = ats["score"]
    bd   = ats.get("breakdown", {})
    wt   = job.get("work_type", "")
    type_color  = {"remote": "green", "hybrid": "yellow", "on-site": "red"}.get(wt, "white")
    score_color = (
        "bold green" if sc >= 80 else
        "green"      if sc >= 65 else
        "yellow"     if sc >= 50 else
        "red"
    )
    table.add_row(
        str(i),
        job.get("company", ""),
        job.get("title", "")[:45],
        f"[{type_color}]{wt}[/{type_color}]",
        f"[{score_color}]{sc}%  {ats['label']}[/{score_color}]",
        f"{bd.get('skills',0)}/35",
        f"{bd.get('keywords',0)}/30",
        f"{bd.get('experience',0)}/20",
        f"{bd.get('education',0)}/10",
    )

console.print(table)

if no_jd:
    console.print(f"\n[dim]{len(no_jd)} job(s) skipped — no JD available: "
                  + ", ".join(j.get("company","?") for j in no_jd) + "[/dim]")

# ── Detailed breakdown for top 5 ───────────────────────────────────────────────
console.print("\n[bold]Detailed Breakdown — Top 5[/bold]")
for job in scored[:5]:
    ats = job["ats"]
    bd  = ats.get("breakdown", {})
    console.print(f"\n  [bold cyan]{job.get('company')}[/bold cyan] — {job.get('title')}")
    console.print(f"  Score: [bold]{ats['score']}% ({ats['label']})[/bold]")
    console.print(f"  Skills     {bd.get('skills',0):>2}/35  | Keywords  {bd.get('keywords',0):>2}/30  | "
                  f"Experience {bd.get('experience',0):>2}/20  | Education {bd.get('education',0):>2}/10  | "
                  f"Title {bd.get('title',0):>2}/5")
    if ats.get("matched_skills"):
        console.print(f"  [green]Matched skills:[/green] {', '.join(ats['matched_skills'])}")
    if ats.get("missing_skills"):
        console.print(f"  [red]Missing skills:[/red]  {', '.join(ats['missing_skills'])}")
    if ats.get("matched_keywords"):
        console.print(f"  [dim]Top keywords matched:[/dim] {', '.join(ats['matched_keywords'][:8])}")
