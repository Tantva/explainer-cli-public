"""Smoke test: the walking skeleton ingests a tiny mixed corpus and synthesizes
at least one cross-source edge (code symbol mentioned in a doc).
"""
from pathlib import Path

from explainer.ingest import ingest_path
from explainer.query import overview, cross_edges


def test_ingest_and_cross_source_edge(tmp_path: Path):
    corpus = tmp_path / "corpus"
    (corpus / "src").mkdir(parents=True)
    (corpus / "docs").mkdir(parents=True)
    (corpus / "src" / "auth.py").write_text("def verify_jwt(token):\n    return True\n")
    (corpus / "docs" / "design.md").write_text(
        "# Auth flow\n\nThe gateway calls `verify_jwt` to validate the token.\n"
    )

    db = tmp_path / "explainer.db"
    counts = ingest_path(corpus, workspace="t", db=db)

    assert counts["code"] == 1
    assert counts["docs"] == 1
    # The wedge: `verify_jwt` defined in code AND mentioned in the doc -> cross-source edge.
    assert counts["cross_source_edges"] >= 1

    ov = overview("t", db=db)
    assert ov["cross_source_edges"] >= 1

    edges = cross_edges("t", "verify_jwt", db=db)
    assert any(e["edge_type"] == "doc_describes_code" for e in edges)
