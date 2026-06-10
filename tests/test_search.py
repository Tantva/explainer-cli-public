"""search() routing: semble when available, keyword fallback otherwise.

We force the keyword path (deterministic, no model download) by disabling semble;
the semble path is validated manually/at runtime.
"""
from pathlib import Path

from explainer.ingest import ingest_path


def test_keyword_fallback(tmp_path: Path, monkeypatch):
    from explainer import retriever
    monkeypatch.setattr(retriever, "available", lambda: False)

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "auth.py").write_text("def verify_jwt(token):\n    return True\n")
    db = tmp_path / "e.db"
    ingest_path(repo, workspace="w", db=db)

    from explainer.query import search
    res = search("w", "verify_jwt", db=db)
    assert res, "expected keyword hits"
    assert all(r["retriever"] == "keyword" for r in res)
    assert any((r.get("name") == "verify_jwt") or ("verify_jwt" in (r.get("preview") or "")) for r in res)
