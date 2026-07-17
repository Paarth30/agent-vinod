"""Structured diff builder for the frontend — same difflib call the CLI's
_show_diff uses, but returning JSON-friendly rows instead of Rich output."""
import difflib


def build_diff(original: str, revised: str) -> list[dict]:
    orig_lines = original.splitlines()
    rev_lines = revised.splitlines()
    diff = list(difflib.unified_diff(orig_lines, rev_lines, lineterm="", n=2))

    if not diff:
        return []

    rows = []
    for line in diff[2:]:  # skip the --- / +++ header lines
        if line.startswith("+"):
            rows.append({"type": "add", "text": line[1:]})
        elif line.startswith("-"):
            rows.append({"type": "del", "text": line[1:]})
        elif line.startswith("@@"):
            rows.append({"type": "hunk", "text": line})
        else:
            rows.append({"type": "context", "text": line})
    return rows
