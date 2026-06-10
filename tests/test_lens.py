"""Lens registry: seed lenses exist, induced lenses register once and freeze."""
from pathlib import Path

from explainer import lens


def test_seed_lenses_present(tmp_path: Path):
    db = tmp_path / "e.db"
    names = {l["name"] for l in lens.list_lenses(db=db)}
    assert {"code", "prose"} <= names

    code = lens.get_lens("code", db=db)
    assert code["kind"] == "coded"
    assert "function" in code["entity_types"]
    assert "calls" in code["relation_types"]

    prose = lens.get_lens("prose", db=db)
    assert "character" in prose["entity_types"]
    assert "co_occurs" in prose["relation_types"]
    assert "first_page" in prose["properties"]["character"]


def test_get_missing_lens_is_none(tmp_path: Path):
    assert lens.get_lens("does-not-exist", db=tmp_path / "e.db") is None


def test_seed_lenses_declare_spine_anchors_and_extractors(tmp_path: Path):
    """ADR-036: every seed type anchors to the upper spine; lenses declare a primitive
    composition; soft-reuse refs are optional."""
    db = tmp_path / "e.db"

    prose = lens.get_lens("prose", db=db)
    assert prose["parents"]["character"] == "agent"          # anchored to the spine
    assert prose["parents"]["character"] in lens.SPINE
    assert prose["aligns"]["character"] == "schema:Person"   # soft reuse, term-level
    # registry-driven extraction; first brick surfaces characters
    assert prose["extractors"][0] == {"use": "recurring-proper-nouns", "etype": "character"}
    assert "co-occurrence" in prose["extractors"]

    code = lens.get_lens("code", db=db)
    assert all(p in lens.SPINE for p in code["parents"].values())
    assert "doc-cross-source" in code["extractors"]

    # the spine is small and on purpose
    assert 6 <= len(lens.SPINE) <= 12


def test_extractors_for_reads_on_connection(tmp_path: Path):
    from explainer import store
    conn = store.connect(tmp_path / "e.db")
    lens.ensure_seeded(conn)
    assert lens.extractors_for(conn, "prose") == [
        {"use": "recurring-proper-nouns", "etype": "character"}, "co-occurrence",
        "doc-cross-source", "structural-binding"]
    assert lens.extractors_for(conn, "nope") is None
    conn.close()


def test_induce_and_freeze(tmp_path: Path):
    db = tmp_path / "e.db"
    schema = {
        "discriminators": "A collection of poems.",
        "entity_types": ["poem", "motif", "form"],
        "relation_types": ["shares_motif", "same_form"],
        "properties": {"poem": ["title", "form"]},
        "signals": ["motif co-occurrence", "semantic"],
        "method": "stanza chunking + motif gazetteer",
    }
    res = lens.register_lens("poetry", "A book of poems — motifs and forms.", schema, db=db)
    assert res["ok"] and res["lens"]["kind"] == "induced"
    assert "poem" in res["lens"]["entity_types"]

    # frozen: re-registering the same name does not overwrite
    again = lens.register_lens("poetry", "different desc", {"entity_types": ["x"]}, db=db)
    assert again["ok"] is False
    assert "motif" in again["lens"]["entity_types"]  # original schema intact

    # seed lenses are frozen too
    assert lens.register_lens("code", "hijack", {}, db=db)["ok"] is False

    assert "poetry" in {l["name"] for l in lens.list_lenses(db=db)}
