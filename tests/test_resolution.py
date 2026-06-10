"""Entity resolution / alias-merge (ADR-036 §B3): surface forms of one entity collapse to a
single canonical node — the fusion stage that stops aliases inflating counts (Dune's cast
count, a contract's "the Borrower"/"Borrower"). Deterministic path tested (embeddings off)."""
import json
from pathlib import Path

from explainer.query import add_entity, add_relation
from explainer import store, primitives


def test_alias_merge_collapses_surface_forms(tmp_path: Path):
    db = tmp_path / "e.db"
    # three surface forms of one party + a distinct party
    add_entity("w", "Borrower", "party", {}, db=db)
    add_entity("w", "the Borrower", "party", {}, db=db)
    add_entity("w", "BORROWER", "party", {}, db=db)
    add_entity("w", "Lender", "party", {}, db=db)
    # an edge on a duplicate, to verify re-pointing onto the canonical node
    add_relation("w", "the Borrower", "Lender", "pays", db=db)

    conn = store.connect(db)
    res = primitives._alias_merge(conn, "w", str(tmp_path), {"embeddings": False})
    conn.commit()

    parties = [r["name"] for r in conn.execute(
        "SELECT name FROM entities WHERE workspace='w' AND etype='party'").fetchall()]
    borrower_forms = [p for p in parties if p.lower().replace("the ", "").strip() == "borrower"]
    assert len(borrower_forms) == 1            # three forms collapsed to one canonical node
    assert "Lender" in parties                 # distinct entity untouched
    assert res["merged_entities"] == 2

    canon = borrower_forms[0]
    props = json.loads(conn.execute(
        "SELECT props FROM entities WHERE workspace='w' AND name=? AND etype='party'", (canon,)).fetchone()["props"])
    assert len(set(props["aliases"])) >= 2     # dropped names recorded as aliases

    # the edge from a dropped form now points at the canonical node
    src = conn.execute(
        "SELECT s.name FROM edges e JOIN entities s ON s.id=e.src_id "
        "WHERE e.workspace='w' AND e.edge_type='pays'").fetchone()["name"]
    assert src == canon
    conn.close()


def test_alias_merge_resolves_within_type_only(tmp_path: Path):
    """A 'Mercury' planet and a 'mercury' element must NOT merge — resolution is within etype."""
    db = tmp_path / "e.db"
    add_entity("w", "Mercury", "planet", {}, db=db)
    add_entity("w", "mercury", "element", {}, db=db)
    conn = store.connect(db)
    primitives._alias_merge(conn, "w", str(tmp_path), {"embeddings": False})
    conn.commit()
    types = {r["etype"] for r in conn.execute("SELECT etype FROM entities WHERE workspace='w'").fetchall()}
    assert types == {"planet", "element"}      # both survive — different types don't fuse
    conn.close()


def test_merge_entities_by_name_llm_confirmed(tmp_path):
    """The agent-confirmed merge path (resolution can't catch 'Sunja' == 'Madam Baek')."""
    from explainer.query import add_entity, add_relation, merge_entities, neighbors
    db = tmp_path / "e.db"
    add_entity("w", "Sunja", "character", {"count": 50}, db=db)
    add_entity("w", "Madam Baek", "character", {"count": 8}, db=db)
    add_entity("w", "Isak", "character", {"count": 20}, db=db)
    add_relation("w", "Madam Baek", "Isak", "married", db=db)
    res = merge_entities("w", keep="Sunja", drop=["Madam Baek"], db=db)
    assert res["ok"] and res["merged"] == 1
    # the marriage edge now hangs off Sunja
    assert "Isak" in {n["entity"] for n in neighbors("w", "Sunja", db=db)}
    from explainer import store
    conn = store.connect(db)
    names = {r["name"] for r in conn.execute("SELECT name FROM entities WHERE workspace='w' AND etype='character'").fetchall()}
    assert names == {"Sunja", "Isak"}     # Madam Baek folded in
    conn.close()
