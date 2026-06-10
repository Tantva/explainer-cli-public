"""Cross-source synthesis (the wedge): exact + fuzzy entity resolution."""
from pathlib import Path

from explainer.ingest import ingest_path
from explainer.query import cross_edges


def test_exact_and_fuzzy_cross_source(tmp_path: Path):
    corpus = tmp_path / "c"
    (corpus / "src").mkdir(parents=True)
    (corpus / "docs").mkdir(parents=True)
    (corpus / "src" / "auth.py").write_text(
        "def verify_jwt(token):\n    return True\n\n"
        "def issue_token(user):\n    return 'x'\n"
    )
    (corpus / "docs" / "design.md").write_text(
        "# Auth flow\n\n"
        "The gateway calls `verify_jwt` to validate the token.\n"   # exact
        "Then `verifyJwt` is reused, and `issueToken` mints a new one.\n"  # fuzzy x2
    )
    db = tmp_path / "e.db"
    counts = ingest_path(corpus, workspace="t", db=db)
    assert counts["cross_source_edges"] >= 2

    e_vj = cross_edges("t", "verify_jwt", db=db)
    assert any(e["edge_type"] == "doc_describes_code" and e["method"] == "exact" for e in e_vj)

    # fuzzy: doc said `issueToken`, code defines `issue_token`
    e_it = cross_edges("t", "issue_token", db=db)
    assert any(e["method"] == "fuzzy" for e in e_it)


def test_idempotent_reingest(tmp_path: Path):
    corpus = tmp_path / "c"
    corpus.mkdir()
    (corpus / "a.py").write_text("def foo():\n    return 1\n")
    (corpus / "a.md").write_text("Doc mentions `foo`.\n")
    db = tmp_path / "e.db"
    c1 = ingest_path(corpus, workspace="t", db=db)["cross_source_edges"]
    c2 = ingest_path(corpus, workspace="t", db=db)["cross_source_edges"]
    assert c1 == c2  # re-ingest doesn't duplicate cross-source edges
