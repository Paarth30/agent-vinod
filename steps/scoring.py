"""Shared JD-keyword extraction — used by both the discovery-stage ATS score
and the cover-letter keyword score, so the definition of "top JD keywords"
can't silently drift between the two."""
import re

STOPWORDS = {
    "with", "that", "this", "have", "will", "from", "they", "your", "about",
    "their", "more", "also", "when", "what", "which", "been", "were", "each",
    "into", "through", "work", "role", "team", "business", "product", "position",
    "management", "experience", "skills", "ability", "ensure", "strong", "good",
    "excellent", "required", "preferred", "including", "using", "based", "across",
    "within", "other", "such", "both", "must", "should", "would", "could",
}


def top_jd_keywords(jd_text: str, limit: int) -> list[str]:
    """Most frequent significant (4+ letter, non-stopword) words in a JD."""
    words = [w for w in re.findall(r"\b[a-z]{4,}\b", jd_text.lower()) if w not in STOPWORDS]
    counts = {w: words.count(w) for w in set(words)}
    return sorted(counts, key=lambda w: -counts[w])[:limit]
