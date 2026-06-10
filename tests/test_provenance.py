"""Provenance: primary (user corpus) vs synthesized (generated wiki). One graph,
distinguished by a flag — so regeneration targets only generated content and trust
stays honest.
"""
from pathlib import Path

from explainer.ingest import ingest_path
from explainer.query import list_artifacts, clear_synthesized
from explainer import lens


def test_provenance_flag_and_clear(tmp_path: Path):
    db = tmp_path / "e.db"
    # primary corpus
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("def f():\n    return 1\n")
    ingest_path(src, workspace="w", db=db)  # default provenance=primary

    # a generated wiki, indexed back as synthesized
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "overview.md").write_text("# Overview\nThe `f` function returns 1.\n")
    ingest_path(wiki, workspace="w", db=db, provenance="synthesized")

    arts = {a["path"].split("/")[-1]: a["provenance"] for a in list_artifacts("w", db=db)}
    assert arts["a.py"] == "primary"
    assert arts["overview.md"] == "synthesized"

    # clear_synthesized removes only the generated content
    res = clear_synthesized("w", db=db)
    assert res["removed"] == 1
    left = {a["path"].split("/")[-1]: a["provenance"] for a in list_artifacts("w", db=db)}
    assert "a.py" in left and "overview.md" not in left


def test_seed_lenses_ship_thin_no_baked_synthesis(tmp_path: Path):
    """ADR-036 correction: domain synthesis plans (factions-and-power, architecture-overview)
    are NOT engine constants — they're induced per corpus / live as induction-prompt exemplars.
    Seed lenses ship thin so they don't bias every corpus toward the ones we first tested."""
    db = tmp_path / "e.db"
    for name in ("code", "prose"):
        l = lens.get_lens(name, db=db)
        assert not l.get("synthesis")   # no baked domain content
