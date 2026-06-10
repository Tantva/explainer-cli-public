"""Code graph beyond Python: Rust + TypeScript via the spec-driven tree-sitter
path. The corpus (relay, snuba) is Rust-heavy, so the call graph must be real
there, not a naive whole-file fallback.
"""
from pathlib import Path

from explainer.ingest import ingest_path
from explainer import store


def _names(conn, ws, lang, kinds):
    marks = ",".join("?" * len(kinds))
    rows = conn.execute(
        f"SELECT c.name FROM chunks c JOIN artifacts a ON a.id=c.artifact_id "
        f"WHERE c.workspace=? AND a.lang=? AND c.kind IN ({marks})",
        (ws, lang, *kinds),
    ).fetchall()
    return {r["name"] for r in rows}


def _calls(conn, ws):
    rows = conn.execute(
        "SELECT e1.name src, e2.name dst FROM edges ed "
        "JOIN entities e1 ON e1.id=ed.src_id JOIN entities e2 ON e2.id=ed.dst_id "
        "WHERE ed.workspace=? AND ed.edge_type='calls'",
        (ws,),
    ).fetchall()
    return {(r["src"], r["dst"]) for r in rows}


def test_rust_and_typescript_graph(tmp_path: Path):
    (tmp_path / "lib.rs").write_text(
        "struct Writer { url: String }\n"
        "fn build_url(host: &str) -> String { format!(\"{}\", host) }\n"
        "impl Writer {\n"
        "    fn write_batch(&self, rows: Vec<u8>) -> bool {\n"
        "        let u = build_url(&self.url);\n"
        "        send(u, rows)\n"
        "    }\n"
        "}\n"
        "fn send(url: String, body: Vec<u8>) -> bool { true }\n"
    )
    (tmp_path / "app.ts").write_text(
        "class OrderClient {\n"
        "  pushOrder(order: any) { return this.post(\"/api/v1/orders\", order); }\n"
        "  post(path: string, b: any) { return fetch(path, b); }\n"
        "}\n"
        "function makeClient(): OrderClient { return new OrderClient(); }\n"
    )
    db = tmp_path / "e.db"
    counts = ingest_path(tmp_path, workspace="g", db=db)
    assert counts["code"] == 2

    conn = store.connect(db)
    # Rust: function + struct definitions are chunked (not a single whole-file chunk)
    assert {"build_url", "send", "write_batch"} <= _names(conn, "g", "rust", ("function",))
    assert "Writer" in _names(conn, "g", "rust", ("struct",))
    # TypeScript: class + methods + function
    assert "OrderClient" in _names(conn, "g", "typescript", ("class",))
    assert {"pushOrder", "post"} <= _names(conn, "g", "typescript", ("method",))
    # call edges resolved across both grammars (callee by trailing name)
    calls = _calls(conn, "g")
    assert ("write_batch", "build_url") in calls
    assert ("write_batch", "send") in calls
    assert ("pushOrder", "post") in calls
    conn.close()
