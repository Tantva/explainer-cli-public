"""LLM-assist binding: when patterns miss a dynamic connection, the agent can
record it and it becomes a durable, queryable cross-repo edge.
"""
from pathlib import Path

from explainer.ingest import ingest_path
from explainer.query import connections, binding_candidates, assert_binding


def test_llm_assert_closes_dynamic_gap(tmp_path: Path):
    svc_a = tmp_path / "svcA"
    svc_a.mkdir()
    # dynamic client: URL built at runtime → literal pattern can't extract it
    (svc_a / "client.py").write_text(
        "import requests\n"
        "BASE = '/api/v1'\n\n"
        "def push_order(order):\n"
        "    return requests.post(f'{BASE}/orders', json=order)\n"
    )
    svc_b = tmp_path / "svcB"
    svc_b.mkdir()
    (svc_b / "server.py").write_text(
        "from flask import Flask\napp = Flask(__name__)\n\n"
        "@app.route('/api/v1/orders', methods=['POST'])\n"
        "def create_order():\n    return 'ok'\n"
    )
    db = tmp_path / "e.db"
    ingest_path(svc_a, workspace="t", db=db)
    ingest_path(svc_b, workspace="t", db=db)

    # patterns alone can't bind it (client URL is an f-string)
    auto = connections("t", cross_repo_only=True, db=db)
    assert not any(c["key"] == "/api/v1/orders" for c in auto)

    # the route shows up as an unbound server (the worklist)
    cand = binding_candidates("t", db=db)
    assert any(s["key"] == "/api/v1/orders" for s in cand["unbound_servers"])

    # agent confirms in the code and records the binding
    res = assert_binding(
        "t", "http", "/api/v1/orders",
        client_path=str(svc_a / "client.py"), client_line=5,
        server_path=str(svc_b / "server.py"), server_line=4,
        confidence=0.85, rationale="client builds f'{BASE}/orders' == server route /api/v1/orders",
        db=db,
    )
    assert res["ok"] and res["cross_repo"] == 1

    # now it's a durable cross-repo edge, tagged as llm
    conns = connections("t", cross_repo_only=True, db=db)
    m = [c for c in conns if c["key"] == "/api/v1/orders"]
    assert m and m[0]["method"] == "llm"

    # and it survives a re-ingest (structural rebuild preserves llm bindings)
    ingest_path(svc_a, workspace="t", db=db)
    conns2 = connections("t", cross_repo_only=True, db=db)
    assert any(c["key"] == "/api/v1/orders" and c["method"] == "llm" for c in conns2)
