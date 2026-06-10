"""Targeted extraction: the session writes non-gazetteer nodes/relations (quotes,
costumes) into the same generic graph the read tools traverse.
"""
from pathlib import Path

from explainer.ingest import ingest_path
from explainer.query import add_entity, add_relation, entities, neighbors


def test_write_then_read(tmp_path: Path):
    db = tmp_path / "e.db"
    add_entity("w", "Paul", "character", {"count": 100}, db=db)
    add_entity("w", "stillsuit", "costume", {"description": "Fremen desert suit", "page": 110}, db=db)
    add_entity("w", "fear is the mind-killer", "quote",
               {"text": "I must not fear. Fear is the mind-killer.", "speaker": "Litany Against Fear", "page": 8}, db=db)
    assert add_relation("w", "Paul", "stillsuit", "wears", db=db)["ok"]

    assert "stillsuit" in {e["name"] for e in entities("w", etype="costume", db=db)}
    assert "fear is the mind-killer" in {e["name"] for e in entities("w", etype="quote", db=db)}
    # the relation is first-class — "what does Paul wear" is now answerable
    assert "stillsuit" in {n["entity"] for n in neighbors("w", "Paul", etype="costume", db=db)}
    # relating to a missing entity fails cleanly
    assert add_relation("w", "Paul", "ghost", "wears", db=db)["ok"] is False


def test_extracted_survives_lens_reingest(tmp_path: Path):
    """Extracted nodes (origin='extracted') must survive a prose re-ingest, which only
    clears origin='prose'."""
    (tmp_path / "book.md").write_text("# C\nAlice met Bob. Alice and Bob walked. Alice, Bob, Alice.\n")
    db = tmp_path / "e.db"
    ingest_path(tmp_path, workspace="w", db=db, lens="prose")
    add_entity("w", "robe", "costume", {"page": 3}, db=db)
    ingest_path(tmp_path, workspace="w", db=db, lens="prose")  # re-extract gazetteer
    assert "robe" in {e["name"] for e in entities("w", etype="costume", db=db)}


def test_claim_asserted_flag(tmp_path):
    """ADR-036 A4: a reported-but-contradicted claim is stored unasserted, still citable."""
    from explainer.query import add_entity, add_relation, cross_edges
    db = tmp_path / "e.db"
    # two doc/code views in conflict; store both, one not committed as true
    add_entity("w", "envelope route", "concept", db=db)
    add_entity("w", "/v2/envelope", "endpoint", db=db)
    r = add_relation("w", "envelope route", "/v2/envelope", "doc_describes_code",
                     confidence=0.5, asserted=False, db=db)
    assert r["asserted"] is False
    edges = cross_edges("w", "envelope route", db=db)
    # not a cross_source edge here, so check directly via the store
    from explainer import store
    conn = store.connect(db)
    a = conn.execute("SELECT asserted FROM edges WHERE workspace='w' AND edge_type='doc_describes_code'").fetchone()["asserted"]
    assert a == 0
    conn.close()
