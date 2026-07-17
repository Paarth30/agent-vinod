"""Shared Claude call wrapper — used by every steps/*.py file that needs a
completion (resume tailoring, cover letters, title suggestions), so retry/
rate-limit handling lives in exactly one place."""
import time
from rich.console import Console

console = Console()


def gemini_call(client, prompt: str, max_tokens: int = 2048, retries: int = 3) -> str:
    for attempt in range(retries):
        try:
            message = client.messages.create(
                model="claude-sonnet-5",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return next((b.text for b in message.content if hasattr(b, "text")), "") or ""
        except Exception as e:
            msg = str(e)
            if "rate_limit" in msg.lower() or "529" in msg or "overloaded" in msg.lower():
                wait = min(30 * (attempt + 1), 60)
                console.print(f"  [yellow]Rate limited — waiting {wait}s...[/yellow]")
                time.sleep(wait)
            else:
                try:
                    console.print(f"  [red]Claude API error: {e}[/red]")
                except Exception:
                    pass
                return ""
    return ""
