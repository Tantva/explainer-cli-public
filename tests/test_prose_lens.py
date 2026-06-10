"""Prose lens: a book becomes a character co-occurrence graph in the SAME generic
store the code lens uses — no new tables, just entities + edges + props.
"""
from pathlib import Path

from explainer.ingest import ingest_path
from explainer import store


def _book(d: Path):
    (d / "book.md").write_text(
        "# Chapter One\n"
        "Alice met Bob in the garden. Alice smiled at Bob. Bob told Alice a secret.\n\n"
        "# Chapter Two\n"
        "Carol joined Alice. Alice and Carol walked far. Carol admired Alice greatly.\n\n"
        "# Chapter Three\n"
        "Bob and Carol argued. Bob left angry. Carol stayed. Alice returned to Bob and Carol.\n"
    )


def _cooccur_pairs(conn, ws):
    rows = conn.execute(
        "SELECT s.name a, d.name b, e.props FROM edges e "
        "JOIN entities s ON s.id=e.src_id JOIN entities d ON d.id=e.dst_id "
        "WHERE e.workspace=? AND e.edge_type='co_occurs'", (ws,)).fetchall()
    return {frozenset((r["a"], r["b"])) for r in rows}


def test_prose_builds_character_cooccurrence(tmp_path: Path):
    _book(tmp_path)
    db = tmp_path / "e.db"
    counts = ingest_path(tmp_path, workspace="novel", db=db, lens="prose")

    assert counts["surfaced"] >= 3
    assert counts["co_occurs"] >= 2

    conn = store.connect(db)
    chars = {r["name"] for r in conn.execute(
        "SELECT name FROM entities WHERE workspace='novel' AND etype='character'").fetchall()}
    assert {"Alice", "Bob", "Carol"} <= chars

    # the recurring relationships are edges in the generic graph
    pairs = _cooccur_pairs(conn, "novel")
    assert frozenset(("Alice", "Bob")) in pairs
    assert frozenset(("Alice", "Carol")) in pairs

    # entities carry lens-specific props (the property bag in action)
    import json
    p = conn.execute(
        "SELECT props FROM entities WHERE workspace='novel' AND name='Alice' AND etype='character'"
    ).fetchone()["props"]
    assert json.loads(p)["count"] >= 4

    # the artifact records which lens indexed it
    lens = conn.execute(
        "SELECT lens FROM artifacts WHERE workspace='novel' AND path LIKE '%book.md'").fetchone()["lens"]
    assert lens == "prose"
    conn.close()


def test_prose_reingest_idempotent(tmp_path: Path):
    _book(tmp_path)
    db = tmp_path / "e.db"
    c1 = ingest_path(tmp_path, workspace="n", db=db, lens="prose")
    c2 = ingest_path(tmp_path, workspace="n", db=db, lens="prose")
    assert c1["surfaced"] == c2["surfaced"]
    assert c1["co_occurs"] == c2["co_occurs"]


def test_reingest_after_typing_no_collision(tmp_path: Path):
    """Re-ingest must clear entities a prior typing pass re-typed (by origin), so they
    don't collide with the fresh provisional ones on the unique constraint."""
    from explainer.query import classify_entities
    _book(tmp_path)
    db = tmp_path / "e.db"
    ingest_path(tmp_path, workspace="n", db=db, lens="prose")
    classify_entities("n", {"Alice": "place"}, db=db)          # re-type to a non-default type
    ingest_path(tmp_path, workspace="n", db=db, lens="prose")  # was: UNIQUE constraint failure
    res = classify_entities("n", {"Alice": "place"}, db=db)    # still works
    assert res["typed"] == 1
