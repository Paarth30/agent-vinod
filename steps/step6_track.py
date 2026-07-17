import json
import csv
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.table import Table
import config as cfg

console = Console()

CSV_PATH = Path("data/applications.csv")
JSON_PATH = Path(cfg.APPLICATIONS_PATH)


def run(jobs: list[dict]):
    console.print("\n[bold]Step 6: Tracking Applications[/bold]")

    records = []
    for job in jobs:
        results = job.get("application_results", [])
        methods_sent = [m for m, ok in results if ok]
        methods_failed = [m for m, ok in results if not ok]

        record = {
            "date": datetime.now().isoformat(),
            "company": job.get("company", ""),
            "title": job.get("title", ""),
            "location": job.get("location", ""),
            "link": job.get("link", ""),
            "contact_name": job.get("contact", {}).get("name", "") if job.get("contact") else "",
            "contact_email": job.get("contact", {}).get("email", "") if job.get("contact") else "",
            "resume_path": job.get("resume_pdf") or job.get("resume_docx", ""),
            "cover_letter_path": job.get("cover_letter_path", ""),
            "methods_sent": ", ".join(methods_sent),
            "methods_failed": ", ".join(methods_failed),
            "status": "applied" if methods_sent else "failed",
        }
        records.append(record)

    if not records:
        console.print("[yellow]No applications to track.[/yellow]")
        return

    _write_csv(records)
    _write_json(records)
    _show_summary(records)


def _write_csv(records: list[dict]):
    CSV_PATH.parent.mkdir(exist_ok=True)
    write_header = not CSV_PATH.exists()

    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=records[0].keys())
        if write_header:
            writer.writeheader()
        writer.writerows(records)

    console.print(f"[green]OK[/green] Logged to [cyan]{CSV_PATH}[/cyan]")


def _write_json(records: list[dict]):
    existing = []
    if JSON_PATH.exists():
        try:
            existing = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    existing.extend(records)
    JSON_PATH.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def _show_summary(records: list[dict]):
    table = Table(title="Application Summary", show_lines=True)
    table.add_column("Company", style="yellow")
    table.add_column("Role", style="white")
    table.add_column("Method(s)", style="cyan")
    table.add_column("Status", style="green")

    for r in records:
        status_str = "[green]Applied[/green]" if r["status"] == "applied" else "[red]Failed[/red]"
        table.add_row(r["company"], r["title"], r["methods_sent"] or "—", status_str)

    console.print("\n", table)

    applied = sum(1 for r in records if r["status"] == "applied")
    console.print(f"\n[bold green]{applied}/{len(records)} applications sent successfully.[/bold green]")
    console.print(f"Full log saved to [cyan]{CSV_PATH}[/cyan]")
