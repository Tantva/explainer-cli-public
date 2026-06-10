"""`inspect` — sample an artifact so the ingest runtime can choose a lens on
*evidence*, not a filename guess (ADR-035).

Returns a cheap, structured peek: a directory's file tree shape + extension
histogram; a PDF's page count, table-of-contents, and first-page text; or a
file's head. The session reads this alongside `list_lenses` and decides which
lens matches (or that a new one must be induced).
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .ingestors import IGNORE_DIRS

_MAX_FILES = 5000


def inspect_artifact(path: str) -> dict:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return {"path": str(p), "error": "path does not exist"}

    if p.is_dir():
        exts: Counter = Counter()
        sample: list[str] = []
        n = 0
        for f in p.rglob("*"):
            if not f.is_file() or any(part in IGNORE_DIRS for part in f.parts):
                continue
            n += 1
            exts[f.suffix.lower() or "(none)"] += 1
            if len(sample) < 20:
                sample.append(str(f.relative_to(p)))
            if n >= _MAX_FILES:
                break
        return {"path": str(p), "kind": "directory", "file_count": n,
                "extensions": dict(exts.most_common(15)), "sample_files": sample}

    ext = p.suffix.lower()
    if ext == ".pdf":
        try:
            import fitz
            doc = fitz.open(p)
            toc = [t[1] for t in (doc.get_toc() or [])][:25]
            sample = doc.load_page(0).get_text("text")[:1500] if doc.page_count else ""
            return {"path": str(p), "kind": "pdf", "pages": doc.page_count,
                    "toc": toc, "sample_text": sample}
        except Exception as e:  # noqa: BLE001
            return {"path": str(p), "kind": "pdf", "error": f"{type(e).__name__}: {e}"}

    try:
        head = p.read_text("utf-8", "ignore")[:1500]
    except OSError as e:
        return {"path": str(p), "error": str(e)}
    return {"path": str(p), "kind": "file", "ext": ext, "sample_text": head}
