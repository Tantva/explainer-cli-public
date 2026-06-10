"""P1 deterministic surfacers (ADR-036): defined-term-pattern + structural-markers give the
legal/textbook/screenplay corpora an automatic entity layer the name-gazetteer can't.
"""
from pathlib import Path

from explainer.ingest import ingest_path
from explainer import store, primitives


def _run(db, ws, root, extractors):
    conn = store.connect(db)
    counts = primitives.run_extractors(conn, ws, str(Path(root).resolve()), extractors)
    conn.commit()
    return conn, counts


def test_defined_term_pattern_surfaces_legal_terms(tmp_path: Path):
    d = tmp_path / "c"; d.mkdir()
    (d / "contract.txt").write_text(
        'AMENDED AND RESTATED CREDIT AGREEMENT. '
        '"Borrower" means Six Flags Theme Parks Inc. '
        '"Consolidated EBITDA" means net income plus interest and taxes. '
        'The "Administrative Agent" means Wells Fargo Bank. The banks (the "Lenders") agree.\n'
    )
    db = tmp_path / "e.db"
    ingest_path(d, workspace="k", db=db)
    conn, counts = _run(db, "k", d, ["defined-term-pattern"])

    terms = {r["name"] for r in conn.execute(
        "SELECT name FROM entities WHERE workspace='k' AND etype='defined_term'").fetchall()}
    assert {"Borrower", "Consolidated EBITDA", "Administrative Agent"} <= terms
    # inline parenthetical definitions are the common real-contract form
    assert "Lenders" in terms
    assert counts["defined_terms"] >= 3
    # definitions are captured for citation
    import json
    p = conn.execute("SELECT props FROM entities WHERE workspace='k' AND name='Borrower'").fetchone()["props"]
    assert "means" in json.loads(p)["definition"]
    conn.close()


def test_defined_term_pattern_idempotent(tmp_path: Path):
    d = tmp_path / "c"; d.mkdir()
    (d / "x.txt").write_text('"Foo" means a bar.\n')
    db = tmp_path / "e.db"
    ingest_path(d, workspace="k", db=db)
    _, c1 = _run(db, "k", d, ["defined-term-pattern"])
    conn, c2 = _run(db, "k", d, ["defined-term-pattern"])
    assert c1["defined_terms"] == c2["defined_terms"] == 1   # re-run doesn't duplicate
    conn.close()


def test_structural_markers_sections_and_scenes(tmp_path: Path):
    d = tmp_path / "c"; d.mkdir()
    (d / "contract.txt").write_text(
        "SECTION 1. DEFINITIONS\nblah blah\nSECTION 9.1 Leverage Ratio\nmore text\n"
    )
    (d / "script.txt").write_text(
        "INT. OPERATIONS ROOM - DAY\nCASSIAN enters.\n\nEXT. YAVIN BASE - NIGHT\nThey land.\n"
    )
    db = tmp_path / "e.db"
    ingest_path(d, workspace="k", db=db)
    # contract sections + screenplay scenes — etype-scoped so they don't clear each other
    _run(db, "k", d, [{"use": "structural-markers", "preset": "section", "etype": "section"}])
    conn, _ = _run(db, "k", d, [{"use": "structural-markers", "preset": "slugline", "etype": "scene"}])

    secs = {r["name"] for r in conn.execute(
        "SELECT name FROM entities WHERE workspace='k' AND etype='section'").fetchall()}
    scenes = {r["name"] for r in conn.execute(
        "SELECT name FROM entities WHERE workspace='k' AND etype='scene'").fetchall()}
    assert any("SECTION 1" in s for s in secs) and any("9.1" in s for s in secs)
    assert any("OPERATIONS ROOM" in s for s in scenes)
    assert any("YAVIN" in s for s in scenes)
    conn.close()


def test_salient_terms_surfaces_lowercase_domain_terms(tmp_path: Path):
    d = tmp_path / "c"; d.mkdir()
    (d / "recipe.txt").write_text(
        "Heat oil and add asafoetida. The asafoetida blooms in the oil. Add more asafoetida. "
        "For garam masala, grind whole spices. Use garam masala generously. Sprinkle garam masala. "
        "Asafoetida and garam masala are both key.\n"
    )
    db = tmp_path / "e.db"
    ingest_path(d, workspace="k", db=db)
    conn, _ = _run(db, "k", d, [{"use": "salient-terms", "etype": "ingredient", "min_count": 3}])
    terms = {r["name"].lower() for r in conn.execute(
        "SELECT name FROM entities WHERE workspace='k' AND etype='ingredient'").fetchall()}
    assert "asafoetida" in terms                       # lowercase single term the gazetteer would miss
    assert any("garam masala" in t for t in terms)     # multi-word lowercase phrase
    conn.close()


def test_cross_reference_links_sections_for_blast_radius(tmp_path: Path):
    """The §→§ edge that powers 'if I change X, which sections break'."""
    d = tmp_path / "c"; d.mkdir()
    (d / "contract.txt").write_text(
        "SECTION 1. DEFINITIONS\n"
        '"Borrower" means the company.\n'
        "SECTION 9.1 LEVERAGE\n"
        "The Borrower shall comply with Section 1 at all times. See also Section 9.1.\n"
    )
    db = tmp_path / "e.db"
    ingest_path(d, workspace="k", db=db)   # section-aware chunking splits the two sections
    conn, _ = _run(db, "k", d, [{"use": "structural-markers", "preset": "section", "etype": "section"},
                                "cross-reference"])
    pairs = {(r["src"], r["dst"]) for r in conn.execute(
        "SELECT s.name src, d.name dst FROM edges e JOIN entities s ON s.id=e.src_id "
        "JOIN entities d ON d.id=e.dst_id WHERE e.workspace='k' AND e.edge_type='references'").fetchall()}
    assert any("9.1" in s and dd.startswith("SECTION 1") for s, dd in pairs), pairs
    conn.close()


def test_extractor_config_is_parsed(tmp_path: Path):
    """A dict extractor entry passes config through to the primitive."""
    d = tmp_path / "c"; d.mkdir()
    (d / "x.txt").write_text("SECTION 2. SCOPE\ntext\n")
    db = tmp_path / "e.db"
    ingest_path(d, workspace="k", db=db)
    conn, _ = _run(db, "k", d, [{"use": "structural-markers", "preset": "section", "etype": "clause"}])
    clauses = {r["etype"] for r in conn.execute(
        "SELECT etype FROM entities WHERE workspace='k' AND json_extract(props,'$.origin')='structural-markers:clause'").fetchall()}
    assert clauses == {"clause"}   # config etype honored
    conn.close()


def test_chunks_door_paginates_substrate(tmp_path: Path):
    """The ingest skill walks chunks() to run schema-guided extraction."""
    from explainer.query import chunks
    d = tmp_path / "c"; d.mkdir()
    (d / "a.py").write_text("def f():\n    return 1\n")
    (d / "doc.md").write_text("# Title\nSome prose mentioning `f`.\n")
    db = tmp_path / "e.db"
    ingest_path(d, workspace="w", db=db)
    code_chunks = chunks("w", kind="code", db=db)
    assert code_chunks and all(c["artifact_kind"] == "code" for c in code_chunks)
    assert all("preview" in c and "id" in c for c in code_chunks)


def test_defined_term_pattern_catches_colon_list_form(tmp_path: Path):
    """Real credit agreements define terms as a colon list ("Term": …), not just "X" means … —
    the induction agents found this is the dominant form (343 vs 9 in the Six Flags agreement)."""
    d = tmp_path / "c"; d.mkdir()
    (d / "defs.txt").write_text(
        "SECTION 1. DEFINITIONS\n"
        '"Maturity Date": the date set forth in the schedule.\n'
        '"Applicable Margin": the per annum rate determined by the leverage ratio.\n'
        'Inline mention of a "Random Phrase": not at line start, should not match.\n'
    )
    db = tmp_path / "e.db"
    ingest_path(d, workspace="k", db=db)
    conn, _ = _run(db, "k", d, ["defined-term-pattern"])
    terms = {r["name"] for r in conn.execute(
        "SELECT name FROM entities WHERE workspace='k' AND etype='defined_term'").fetchall()}
    assert {"Maturity Date", "Applicable Margin"} <= terms      # colon list entries caught
    assert "Random Phrase" not in terms                          # mid-sentence quoted:colon is not a definition
    conn.close()
