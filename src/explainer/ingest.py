"""Ingestion driver: walk a corpus, dispatch each file to the Ingestor that
handles it (see ``ingestors.py``), then run synthesis + structural binding (the
wedge).

The per-medium logic lives in ``ingestors.py`` (a pluggable registry); this module
just walks, dispatches, counts, and kicks off cross-source resolution.
"""
from __future__ import annotations

from pathlib import Path

from . import ingestors, store
from .ingestors import IGNORE_DIRS, IngestContext


def _walk(root: Path) -> list[Path]:
    root = root.expanduser().resolve()
    if root.is_file():
        return [root]
    return [
        p for p in root.rglob("*")
        if p.is_file() and not any(part in IGNORE_DIRS for part in p.parts)
    ]


def ingest_path(path, workspace: str = "default", db=store.DEFAULT_DB, lens: str | None = None,
                provenance: str = "primary") -> dict:
    conn = store.connect(db)
    store.ensure_workspace(conn, workspace)
    root = str(Path(path).expanduser().resolve())
    store.add_source(conn, workspace, root)
    ctx = IngestContext(conn, workspace)

    counts = {ing.name: 0 for ing in ingestors.REGISTRY}
    counts["skipped"] = 0
    for f in _walk(Path(path)):
        ing = ingestors.resolve(f)
        if ing is None:
            counts["skipped"] += 1
            continue
        ing.ingest(ctx, f)
        counts[ing.name] += 1
    if lens:
        conn.execute("UPDATE artifacts SET lens=? WHERE workspace=? AND path LIKE ?",
                     (lens, workspace, f"{root}%"))
    # Provenance: 'primary' = the user's corpus (code + human docs, authoritative);
    # 'synthesized' = content WE generated (e.g. the wiki). Keeps trust honest, lets
    # regeneration target only generated content, and stops synthesis grounding on itself.
    conn.execute(
        "UPDATE artifacts SET props = json_set(COALESCE(props,'{}'), '$.provenance', ?) "
        "WHERE workspace=? AND path LIKE ?",
        (provenance, workspace, f"{root}%"))
    conn.commit()

    # ADR-036: extraction is registry-driven by the lens's declared primitives — no
    # name-based branches in the driver. A lens supplies its `extractors`; with no lens,
    # the default composition (doc↔code synthesis + structural binding) runs — the
    # historical behavior for mixed code/doc corpora. (Code chunks + call-graph are
    # emitted at chunk time by the code chunker; that becomes an `ast-callgraph`
    # primitive in P0.2.)
    from . import lens as _lens
    from . import primitives
    _lens.ensure_seeded(conn)
    extractors = (_lens.extractors_for(conn, lens) if lens else None) \
        or ["ast-callgraph", "doc-cross-source", "structural-binding"]
    counts.update(primitives.run_extractors(conn, workspace, root, extractors))
    conn.commit()
    conn.close()
    return counts
