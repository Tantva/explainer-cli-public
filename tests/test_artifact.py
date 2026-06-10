"""Knowledge artifact rendering: markdown (+mermaid) → standalone HTML, and an
engine-drawn mermaid graph of the workspace's cross-repo bindings.
"""
from pathlib import Path

from explainer import artifact
from explainer.ingest import ingest_path


def test_render_html_mermaid_and_markdown():
    body = (
        "## Heading\n\n"
        "Some prose with a `code` span.\n\n"
        "```mermaid\nflowchart LR\n  a-->|\"http /x\"| b\n```\n\n"
        "| col | val |\n|---|---|\n| a | 1 |\n"
    )
    html = artifact.render_html("My Title", body, subtitle="sub")
    # mermaid fence became a client-rendered div (NOT an escaped <pre><code>)
    assert '<div class="mermaid">' in html
    assert "flowchart LR" in html
    assert "language-mermaid" not in html
    # markdown rendered: heading, table, title
    assert "<h2>Heading</h2>" in html
    assert "<table>" in html
    assert "<title>My Title</title>" in html
    # arrow not HTML-escaped inside the mermaid block (would break rendering)
    assert "a--&gt;" not in html.split('<div class="mermaid">')[1].split("</div>")[0]


def test_mermaid_bindings_from_corpus(tmp_path: Path):
    client = tmp_path / "client"
    client.mkdir()
    (client / "c.py").write_text(
        "import requests\n\ndef f():\n    return requests.post('/api/v1/orders', json={})\n"
    )
    server = tmp_path / "server"
    server.mkdir()
    (server / "s.py").write_text(
        "from flask import Flask\napp = Flask(__name__)\n\n"
        "@app.route('/api/v1/orders', methods=['POST'])\ndef create():\n    return 'ok'\n"
    )
    db = tmp_path / "e.db"
    ingest_path(client, workspace="t", db=db)
    ingest_path(server, workspace="t", db=db)

    g = artifact.mermaid_bindings("t", cross_repo_only=True, db=db)
    assert g.startswith("flowchart")
    assert "/api/v1/orders" in g
    assert "c.py" in g and "s.py" in g

    out = artifact.write_artifact("t", "Test Artifact", f"```mermaid\n{g}\n```", db=db)
    assert Path(out).exists()
    assert '<div class="mermaid">' in Path(out).read_text()
