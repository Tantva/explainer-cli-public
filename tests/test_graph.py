"""Generic graph traversal (entities/neighbors) + the ingest-time entity typing
round-trip (pending_entities/classify_entities) — both schema-free at the boundary.
"""
from pathlib import Path

from explainer.ingest import ingest_path
from explainer.query import entities, neighbors, pending_entities, classify_entities


def _book(d: Path):
    (d / "book.md").write_text(
        "# One\nAlice met Bob in Wonderland. Alice smiled at Bob in Wonderland. Bob told Alice a tale.\n\n"
        "# Two\nCarol joined Alice in Wonderland. Alice and Carol walked through Wonderland. Carol liked Alice.\n\n"
        "# Three\nBob and Carol met there. Alice greeted Bob and Carol in Wonderland again.\n"
    )


def test_entities_and_neighbors(tmp_path: Path):
    _book(tmp_path)
    db = tmp_path / "e.db"
    ingest_path(tmp_path, workspace="b", db=db, lens="prose")

    names = {e["name"] for e in entities("b", db=db)}
    assert {"Alice", "Bob", "Carol"} <= names

    nb = {n["entity"] for n in neighbors("b", "Alice", relation="co_occurs", db=db)}
    assert {"Bob", "Carol"} <= nb


def test_typing_round_trip(tmp_path: Path):
    _book(tmp_path)
    db = tmp_path / "e.db"
    ingest_path(tmp_path, workspace="b", db=db, lens="prose")

    # provisional worklist carries a sample context for the session to classify
    pend = pending_entities("b", db=db)
    pend_names = {p["name"] for p in pend}
    assert {"Alice", "Bob", "Carol"} <= pend_names
    assert all("sample" in p for p in pend)

    # the ingest runtime types them: Alice/Bob are characters, "Wonderland" a place,
    # Carol gets dropped as (pretend) noise
    res = classify_entities("b", {"Alice": "character", "Bob": "character",
                                   "Wonderland": "place", "Carol": "drop"}, db=db)
    assert res["typed"] == 3 and res["dropped"] == 1

    # now type-filtered queries are first-class
    chars = {e["name"] for e in entities("b", etype="character", db=db)}
    assert {"Alice", "Bob"} <= chars and "Carol" not in chars
    places = {e["name"] for e in entities("b", etype="place", db=db)}
    assert "Wonderland" in places

    # dropped entity is gone from the graph
    assert "Carol" not in {n["entity"] for n in neighbors("b", "Alice", db=db)}
    # nothing provisional remains
    assert pending_entities("b", db=db) == []

    # neighbor type filter works
    p = neighbors("b", "Alice", etype="place", db=db)
    assert all(n["type"] == "place" for n in p)
