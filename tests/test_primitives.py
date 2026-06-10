"""Primitive registry (ADR-036): extraction is composed from named primitives, dispatched
without any lens-name branch; declared-but-unimplemented primitives surface as pending."""
from pathlib import Path

from explainer import primitives, store


def test_implemented_primitives_registered():
    reg = set(primitives.registered())
    assert {"recurring-proper-nouns", "co-occurrence", "doc-cross-source",
            "structural-binding", "ast-callgraph"} <= reg
    # ast-callgraph graduated from PLANNED to implemented (code is no longer a privileged path)
    assert "ast-callgraph" not in primitives.PLANNED


def test_callgraph_is_registry_driven_not_inline(tmp_path):
    """The code call-graph is built by the ast-callgraph primitive over the store, not
    inline in the chunker. Running it standalone on an already-chunked workspace produces
    the calls edges."""
    from explainer.ingest import ingest_path
    repo = tmp_path / "r"; repo.mkdir()
    (repo / "m.py").write_text("def helper():\n    return 1\n\ndef main():\n    return helper()\n")
    db = tmp_path / "e.db"
    ingest_path(repo, workspace="c", db=db)  # default composition includes ast-callgraph
    conn = store.connect(db)
    pairs = {(r["src"], r["dst"]) for r in conn.execute(
        "SELECT s.name src, d.name dst FROM edges e JOIN entities s ON s.id=e.src_id "
        "JOIN entities d ON d.id=e.dst_id WHERE e.workspace='c' AND e.edge_type='calls'").fetchall()}
    assert ("main", "helper") in pairs
    conn.close()


def test_run_extractors_reports_pending(tmp_path: Path):
    conn = store.connect(tmp_path / "e.db")
    store.ensure_workspace(conn, "w")
    # a not-yet-implemented brick the lens might declare (still in PLANNED)
    counts = primitives.run_extractors(conn, "w", str(tmp_path), ["sequence"])
    assert counts.get("pending_extractors") == ["sequence"]
    assert "sequence" in primitives.PLANNED
    conn.close()


def test_run_extractors_runs_implemented(tmp_path: Path):
    conn = store.connect(tmp_path / "e.db")
    store.ensure_workspace(conn, "w")
    counts = primitives.run_extractors(conn, "w", str(tmp_path), ["doc-cross-source", "structural-binding"])
    # both implemented → no pending, and their counts surface
    assert "pending_extractors" not in counts
    assert "cross_source_edges" in counts and "structural_bindings" in counts
    conn.close()


def test_llm_primitives_marked_skill_orchestrated(tmp_path):
    """LLM extraction (the general core) is the ingest skill's phase, not engine-run — declared
    in a lens, it's recorded as skill-orchestrated, not pending/broken."""
    conn = store.connect(tmp_path / "e.db")
    store.ensure_workspace(conn, "w")
    counts = primitives.run_extractors(conn, "w", str(tmp_path), ["llm-extract", "sequence"])
    assert counts.get("skill_extractors") == ["llm-extract"]      # skill fulfills it
    assert counts.get("pending_extractors") == ["sequence"]       # deterministic, not yet built
    conn.close()
