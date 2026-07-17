from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich.table import Table
import config as cfg

console = Console()


def run(interactive: bool = True) -> dict:
    if interactive:
        console.print(Panel("[bold cyan]Job Application Agent[/bold cyan]\nLet's set up this application run.", expand=False))
        console.print("\n[bold]Step 0: Job Search Preferences[/bold]")

    # Build config from .env defaults
    role = cfg.JOB_TITLES[0] if cfg.JOB_TITLES else "Business Analyst"
    location = cfg.JOB_LOCATIONS[0] if cfg.JOB_LOCATIONS else "Remote"
    keywords = cfg.JOB_KEYWORDS
    experience = cfg.JOB_EXPERIENCE
    max_jobs = cfg.MAX_JOBS_PER_RUN
    min_ats_score = cfg.MIN_ATS_SCORE
    min_years = cfg.MIN_YEARS_EXPERIENCE
    max_years = cfg.MAX_YEARS_EXPERIENCE

    if interactive:
        role = Prompt.ask("\n[yellow]Job title / role[/yellow]", default=role)
        location = Prompt.ask("[yellow]Location[/yellow]", default=location)
        experience = Prompt.ask(
            "[yellow]Experience level[/yellow]",
            choices=["internship", "entry", "mid", "senior", "lead", "any"],
            default=experience if experience in ["internship","entry","mid","senior","lead","any"] else "any",
        )
        years_input = Prompt.ask(
            "[yellow]Years of experience you have (e.g. 1-2, blank = no filter)[/yellow]",
            default=(f"{min_years}-{max_years}" if min_years is not None and max_years is not None else ""),
        )
        if years_input.strip():
            parts = [p.strip() for p in years_input.replace("to", "-").split("-") if p.strip()]
            min_years = int(parts[0]) if parts else None
            max_years = int(parts[1]) if len(parts) > 1 else min_years
        kw_input = Prompt.ask("[yellow]Keywords (comma-separated)[/yellow]", default=", ".join(keywords))
        keywords = [k.strip() for k in kw_input.split(",") if k.strip()]
        max_jobs = int(Prompt.ask("[yellow]Max jobs to find[/yellow]", default=str(max_jobs)))
        min_ats_score = int(Prompt.ask("[yellow]Minimum ATS score to keep a job (%)[/yellow]", default=str(min_ats_score)))

    config = {
        "role": role,
        "location": location,
        "experience": experience,
        "min_years": min_years,
        "max_years": max_years,
        "keywords": keywords,
        "max_jobs": max_jobs,
        "min_ats_score": min_ats_score,
        "methods": ["linkedin", "email", "website"],
        "all_titles": cfg.JOB_TITLES,
        "all_locations": cfg.JOB_LOCATIONS,
        "work_types": getattr(cfg, "JOB_WORK_TYPES", ["Remote", "Hybrid"]),
    }

    if interactive:
        table = Table(title="Run Configuration", show_header=False, box=None)
        table.add_column("Field", style="cyan")
        table.add_column("Value", style="white")
        table.add_row("Roles", ", ".join(cfg.JOB_TITLES))
        table.add_row("Locations", ", ".join(cfg.JOB_LOCATIONS))
        table.add_row("Experience", experience)
        if min_years is not None or max_years is not None:
            table.add_row("Years of experience", f"{min_years or 0}-{max_years if max_years is not None else '+'}")
        table.add_row("Keywords", ", ".join(keywords))
        table.add_row("Max jobs", str(max_jobs))
        table.add_row("Min ATS score", f"{min_ats_score}%")
        console.print("\n", table)

        if not Confirm.ask("\n[bold green]Proceed?[/bold green]"):
            raise SystemExit(0)

    return config
