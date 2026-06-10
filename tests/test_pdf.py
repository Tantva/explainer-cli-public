"""PDF → text in our layer, wired so semble can index it.

Validates the parts our code owns (extraction, derived files, mapping, source
registration). The semble-over-derived-text path is validated at runtime.
"""
from pathlib import Path


def test_pdf_derived_text(tmp_path: Path, monkeypatch):
    import fitz  # PyMuPDF
    from explainer import ingest as ing, ingestors, store

    # keep derived files inside the tmp dir (DERIVED_ROOT lives on the pdf ingestor)
    monkeypatch.setattr(ingestors, "DERIVED_ROOT", tmp_path / "derived")

    corpus = tmp_path / "c"
    corpus.mkdir()
    pdf = corpus / "spec.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "The verify_jwt function validates the auth token.")
    doc.save(pdf)
    doc.close()

    db = tmp_path / "e.db"
    counts = ing.ingest_path(corpus, workspace="w", db=db)
    assert counts["pdf"] == 1

    conn = store.connect(db)

    # derived text file written + mapped back to (pdf, page)
    dmap = store.derived_map(conn, "w")
    assert len(dmap) >= 1
    dpath = next(iter(dmap))
    assert Path(dpath).exists()
    assert "verify_jwt" in Path(dpath).read_text()
    assert dmap[dpath]["orig_path"] == str(pdf)
    assert dmap[dpath]["page"] == 1

    # derived root registered as a semble source
    assert any("derived" in s for s in store.list_sources(conn, "w"))
    conn.close()
