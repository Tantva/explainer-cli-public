"""Generic cross-repo structural binding — HTTP routes + queue topics.

Deliberately not Sentry-shaped: a generic 'orders' service pair.
"""
from pathlib import Path

from explainer.ingest import ingest_path
from explainer.query import connections, overview


def test_http_route_call_cross_repo(tmp_path: Path):
    svc_a = tmp_path / "svcA"
    svc_a.mkdir()
    (svc_a / "client.py").write_text(
        "import requests\n\n"
        "def push_order(order):\n"
        "    return requests.post('/api/v1/orders', json=order)\n"
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

    conns = connections("t", kind="http", db=db)
    match = [c for c in conns if c["key"] == "/api/v1/orders"]
    assert match, f"expected an /api/v1/orders binding, got {conns}"
    c = match[0]
    assert c["cross_repo"] == 1
    assert "client.py" in c["client_path"] and "server.py" in c["server_path"]

    assert overview("t", db=db)["cross_repo_bindings"] >= 1


def test_topic_produce_consume_cross_repo(tmp_path: Path):
    prod = tmp_path / "producer"
    prod.mkdir()
    (prod / "prod.py").write_text(
        "def emit(p):\n    producer.produce('order-events', p)\n"
    )
    cons = tmp_path / "consumer"
    cons.mkdir()
    (cons / "cons.py").write_text(
        "def run():\n    consumer.subscribe(['order-events'])\n"
    )
    db = tmp_path / "e.db"
    ingest_path(prod, workspace="t2", db=db)
    ingest_path(cons, workspace="t2", db=db)

    conns = connections("t2", kind="topic", db=db)
    assert any(c["key"] == "order-events" and c["cross_repo"] == 1 for c in conns), conns
