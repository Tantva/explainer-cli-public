"""Content retrieval via **semble** (ADR-002) — Model2Vec embeddings + BM25 +
Reciprocal Rank Fusion + code-aware reranking, CPU-only, disk-cached.

This is the retrieval half of the system; the graph/synthesis (the wedge) is ours.
semble indexes a path (code + text files) and returns ranked chunks with file/line.
Guarded: if semble isn't installed, callers fall back to keyword search. PDFs are
not handled by semble (binary) — their extracted text stays in keyword search.
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

# Set when `import semble` fails, so callers/operators can see *why* search fell
# back to keyword instead of guessing. Surfaced via `why_unavailable()`.
_UNAVAILABLE_REASON: str | None = None


def _model_path() -> str:
    """Which Model2Vec model semble uses. Default: minishlab/potion-retrieval-32M —
    MinishLab's best static *retrieval* model. Chosen because the prose side (docs +
    PDFs) relies wholly on embedding quality (no graph fallback), while code is also
    backed by our tree-sitter call graph. Override via EXPLAINER_MODEL (any Model2Vec
    HF id, or a local model dir)."""
    return os.environ.get("EXPLAINER_MODEL") or "minishlab/potion-retrieval-32M"


def available() -> bool:
    """True if semble can be imported in this process. On failure, records the
    reason (and logs it once to stderr) so a silent keyword fallback is never a
    mystery — the symptom we hit in the plugin's uv env when its venv was wiped
    by a reinstall and `import semble` failed."""
    global _UNAVAILABLE_REASON
    try:
        import semble  # noqa: F401
        _UNAVAILABLE_REASON = None
        return True
    except Exception as e:
        reason = f"{type(e).__name__}: {e}"
        if _UNAVAILABLE_REASON != reason:
            print(f"[explainer] semble unavailable, search falls back to keyword: {reason}",
                  file=sys.stderr, flush=True)
        _UNAVAILABLE_REASON = reason
        return False


def why_unavailable() -> str | None:
    """The last reason semble was unavailable (None if it imported fine)."""
    return _UNAVAILABLE_REASON


@lru_cache(maxsize=64)
def _index(root: str):
    """Build (or load cached) a semble index for a source root. Indexes code, docs,
    config, and plain-text files (so our derived PDF text is covered). Cached per
    process; semble also caches to disk with file-change detection."""
    from semble import ContentType, SembleIndex
    return SembleIndex.from_path(
        root,
        content=(ContentType.CODE, ContentType.DOCS, ContentType.CONFIG),
        model_path=_model_path(),
    )


def search_roots(roots, query: str, k: int = 8) -> list[dict]:
    """Search the workspace's source roots with semble; return normalized,
    citation-ready chunk records sorted by score."""
    out: list[dict] = []
    for root in roots:
        try:
            results = _index(root).search(query, top_k=k)
        except Exception as e:
            # Don't swallow silently — a per-root index/search failure used to look
            # identical to "no matches". Log it; keep searching the other roots.
            print(f"[explainer] semble search failed for root {root!r}: "
                  f"{type(e).__name__}: {e}", file=sys.stderr, flush=True)
            continue
        for r in results:
            ch = getattr(r, "chunk", None)
            if ch is None:
                continue
            content = getattr(ch, "content", "") or ""
            fp = getattr(ch, "file_path", "") or ""
            # semble returns paths relative to the index root; resolve to absolute so
            # the caller can map derived PDF paths back to their original artifact.
            abs_path = str((Path(root) / fp).resolve())
            out.append({
                "path": abs_path,
                "artifact_kind": None,   # set by caller (derived -> pdf, else by ext)
                "name": None,
                "start_line": getattr(ch, "start_line", None),
                "end_line": getattr(ch, "end_line", None),
                "preview": content[:600],
                "score": getattr(r, "score", None),
                "retriever": "semble",
            })
    out.sort(key=lambda d: (d.get("score") or 0.0), reverse=True)
    return out[:k]
