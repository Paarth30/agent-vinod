import re
import smtplib
import requests
from rich.console import Console
from rich.table import Table
from rich.prompt import Confirm
import config as cfg

console = Console()

COMMON_PATTERNS = [
    "{first}.{last}",
    "{first}{last}",
    "{f}{last}",
    "{first}",
    "{first}_{last}",
]

TARGET_TITLES = ["recruiter", "talent acquisition", "hr", "human resources", "ceo", "founder", "hiring manager"]


def run(jobs: list[dict]) -> list[dict]:
    console.print("\n[bold]Step 4: Finding Contacts[/bold]")

    for i, job in enumerate(jobs, 1):
        console.print(f"\n[cyan][{i}/{len(jobs)}][/cyan] Finding contact for [bold]{job['company']}[/bold]")

        domain = _guess_domain(job["company"])
        contact = None

        if cfg.HUNTER_API_KEY:
            contact = _hunter_search(job["company"], domain)

        if not contact and cfg.APOLLO_API_KEY:
            contact = _apollo_search(job["company"])

        if not contact and domain:
            contact = _permutation_search(domain)

        if contact:
            name_display = contact['name'] or "HR/Recruiter"
            title_display = contact['title'] or "Contact"
            console.print(f"  [green]OK[/green] Found: [cyan]{name_display}[/cyan] ({title_display}) -> [yellow]{contact['email']}[/yellow]")
        else:
            console.print("  [yellow]No contact found — will apply via website/LinkedIn only.[/yellow]")

        job["contact"] = contact

    _show_contact_summary(jobs)

    if not Confirm.ask("\n[bold green]Contacts look good — proceed to sending applications?[/bold green]"):
        console.print("[red]Aborted.[/red]")
        raise SystemExit(0)

    return jobs


def _guess_domain(company: str) -> str:
    slug = re.sub(r"[^a-z0-9]", "", company.lower().replace(" ", ""))
    return f"{slug}.com"


def _hunter_search(company: str, domain: str) -> dict | None:
    try:
        r = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "api_key": cfg.HUNTER_API_KEY, "limit": 5},
            timeout=10,
        )
        data = r.json().get("data", {})
        emails = data.get("emails", [])

        def _make_contact(e):
            name = f"{e.get('first_name') or ''} {e.get('last_name') or ''}".strip() or ""
            return {
                "name": name,
                "title": e.get("position") or "",
                "email": e["value"],
                "source": "hunter.io",
            }

        for e in emails:
            pos = (e.get("position") or "").lower()
            if any(t in pos for t in TARGET_TITLES):
                return _make_contact(e)

        # No fallback to emails[0] — never email someone whose title isn't
        # HR/recruiting/leadership just because they're the first result.
    except Exception as ex:
        console.print(f"  [dim]Hunter error: {ex}[/dim]")
    return None


def _apollo_search(company: str) -> dict | None:
    try:
        r = requests.post(
            "https://api.apollo.io/v1/mixed_people/search",
            headers={
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
                "X-Api-Key": cfg.APOLLO_API_KEY,
            },
            json={
                "q_organization_name": company,
                "person_titles": ["recruiter", "talent acquisition", "hr manager", "ceo", "founder"],
                "page": 1,
                "per_page": 5,
            },
            timeout=10,
        )
        people = r.json().get("people", [])
        for p in people:
            email = p.get("email")
            title = (p.get("title") or "").lower()
            # Apollo's person_titles filter is a soft preference, not a guarantee —
            # verify client-side too so we never email an unrelated employee.
            if email and any(t in title for t in TARGET_TITLES):
                return {
                    "name": p.get("name", ""),
                    "title": p.get("title", ""),
                    "email": email,
                    "source": "apollo.io",
                }
    except Exception as ex:
        console.print(f"  [dim]Apollo error: {ex}[/dim]")
    return None


def _permutation_search(domain: str) -> dict | None:
    # Try common first names for generic roles as a last resort
    test_emails = [f"hr@{domain}", f"careers@{domain}", f"jobs@{domain}", f"recruiting@{domain}"]
    for email in test_emails:
        if _smtp_verify(email, domain):
            return {"name": "", "title": "HR/Careers", "email": email, "source": "smtp-verify"}
    return None


def _smtp_verify(email: str, domain: str) -> bool:
    try:
        import dns.resolver
        records = dns.resolver.resolve(domain, "MX")
        mx = str(records[0].exchange).rstrip(".")
        with smtplib.SMTP(mx, 25, timeout=5) as s:
            s.helo("verify.local")
            s.mail("test@verify.local")
            code, _ = s.rcpt(email)
            return code == 250
    except Exception:
        return False


def _show_contact_summary(jobs: list[dict]):
    table = Table(title="Contact Summary", show_lines=True)
    table.add_column("Company", style="yellow")
    table.add_column("Contact", style="white")
    table.add_column("Email", style="cyan")
    table.add_column("Source", style="dim")

    for job in jobs:
        c = job.get("contact")
        if c:
            name_str = c['name'] or "HR/Recruiter"
            title_str = c['title'] or "Contact"
            table.add_row(job["company"], f"{name_str} ({title_str})", c["email"], c["source"])
        else:
            table.add_row(job["company"], "[dim]Not found[/dim]", "[dim]—[/dim]", "[dim]—[/dim]")

    console.print("\n", table)
