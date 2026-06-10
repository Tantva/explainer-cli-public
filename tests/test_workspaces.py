"""Workspace lifecycle as independent flows: create → ingest → list → inspect."""
from pathlib import Path

from explainer.query import create_workspace, list_workspaces, list_artifacts
from explainer.ingest import ingest_path


def test_workspace_lifecycle(tmp_path: Path):
    db = tmp_path / "e.db"

    # 1. set up workspaces
    assert create_workspace("alpha", db=db)["created"] is True
    assert create_workspace("alpha", db=db)["created"] is False  # idempotent
    create_workspace("beta", db=db)

    # 3. how many workspaces are configured?
    ws = {w["name"]: w for w in list_workspaces(db=db)}
    assert {"alpha", "beta"} <= set(ws)
    assert ws["alpha"]["artifacts"] == 0

    # 2. ingest into one
    repo = tmp_path / "repo"
    (repo).mkdir()
    (repo / "m.py").write_text("def foo():\n    return 1\n")
    (repo / "r.md").write_text("Docs mention `foo`.\n")
    ingest_path(repo, workspace="alpha", db=db)

    # 4. what artifacts are ingested in the workspace?
    arts = list_artifacts("alpha", db=db)
    kinds = {a["kind"] for a in arts}
    assert {"code", "docs"} <= kinds

    # counts reflected in workspace listing
    ws = {w["name"]: w for w in list_workspaces(db=db)}
    assert ws["alpha"]["artifacts"] == 2
    assert ws["beta"]["artifacts"] == 0
