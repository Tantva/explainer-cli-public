"""Tree-sitter code graph: function/class chunks + call edges."""
from pathlib import Path

from explainer.ingest import ingest_path
from explainer import store


def test_python_callgraph(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "m.py").write_text(
        "class Service:\n"
        "    def handle(self):\n"
        "        return helper()\n"
        "\n"
        "def helper():\n"
        "    return 1\n"
        "\n"
        "def main():\n"
        "    return helper()\n"
    )
    db = tmp_path / "e.db"
    counts = ingest_path(repo, workspace="c", db=db)
    assert counts["code"] == 1

    conn = store.connect(db)

    # function + class chunks extracted via tree-sitter
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM chunks WHERE workspace='c' AND kind IN ('function','class')"
    ).fetchall()}
    assert {"helper", "main", "handle", "Service"} <= names

    # call edges: main -> helper, handle -> helper
    pairs = {(r["src"], r["dst"]) for r in conn.execute(
        "SELECT s.name src, d.name dst FROM edges e "
        "JOIN entities s ON s.id=e.src_id JOIN entities d ON d.id=e.dst_id "
        "WHERE e.workspace='c' AND e.edge_type='calls'"
    ).fetchall()}
    assert ("main", "helper") in pairs
    assert ("handle", "helper") in pairs
    conn.close()
