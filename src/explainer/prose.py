"""Prose helpers — the name-candidate gazetteer regex, stopwords, and page locator.

The extraction logic itself now lives in the composable primitives `recurring-proper-nouns`
and `co-occurrence` (primitives.py); this module keeps only the shared, reusable pieces so
the surfacer doesn't reinvent them. (Historically this held a single `extract_prose` blob;
ADR-036 split it into registry primitives.)
"""
from __future__ import annotations

import re

# Capitalized 1–3 word candidate (a name / proper noun): "Paul", "Lady Jessica".
# Allow an internal apostrophe/hyphen so "Muad'Dib" and "Feyd-Rautha" stay whole.
_CAND = re.compile(r"\b([A-Z][a-z]{2,}(?:['’\-][A-Z][a-z]+)?(?:\s+[A-Z][a-z]+){0,2})\b")

# Marks an entity as created by the prose surfacer — used to clear its output (regardless of
# post-typing etype) on idempotent re-ingest, without touching write-door ('extracted') nodes.
ORIGIN = "prose"

# Words that get capitalized at sentence start / structurally — not names.
_STOP = {
    "The", "A", "An", "And", "But", "Or", "So", "If", "As", "At", "In", "On", "Of", "To",
    "For", "With", "By", "From", "He", "She", "It", "They", "We", "You", "His", "Her",
    "Their", "My", "Your", "Our", "Its", "This", "That", "These", "Those", "There", "Here",
    "When", "Then", "Now", "What", "Who", "Why", "How", "Where", "While", "After", "Before",
    "Once", "Yet", "Not", "No", "Yes", "Chapter", "Part", "Book", "Page", "Contents",
    "Introduction", "Prologue", "Epilogue", "Section", "Figure", "Table", "Note",
}


def _page_of(name: str | None) -> int | None:
    if name and re.fullmatch(r"p\d+", name):
        return int(name[1:])
    return None
