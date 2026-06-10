"""Pluggable media: an OpenAPI spec is a first-class artifact in the wedge.

A spec declares the routes a service *serves*; a separate repo has client code that
*calls* one of those routes. The structural binder should connect them across repos —
proving a non-code medium, slotted in via the Ingestor registry, makes a connection.
"""
from pathlib import Path

from explainer.ingest import ingest_path
from explainer.ingestors import resolve, OpenApiIngestor
from explainer.query import connections, list_artifacts


def test_openapi_spec_binds_to_code_client(tmp_path: Path):
    # client repo: code that POSTs to /api/v1/orders (a client http connector)
    client_repo = tmp_path / "client_repo"
    client_repo.mkdir()
    (client_repo / "client.py").write_text(
        "import requests\n\n"
        "def push_order(order):\n"
        "    return requests.post('/api/v1/orders', json=order)\n"
    )
    # contract repo: an OpenAPI spec declaring the server side of that route
    spec_repo = tmp_path / "contract"
    spec_repo.mkdir()
    (spec_repo / "openapi.yaml").write_text(
        "openapi: 3.0.0\n"
        "info:\n  title: Orders API\n  version: '1.0'\n"
        "paths:\n"
        "  /api/v1/orders:\n"
        "    post:\n"
        "      summary: Create an order\n"
        "      operationId: createOrder\n"
        "  /api/v1/orders/{id}:\n"
        "    get:\n"
        "      summary: Fetch an order\n"
    )

    db = tmp_path / "e.db"
    ingest_path(client_repo, workspace="t", db=db)
    spec_counts = ingest_path(spec_repo, workspace="t", db=db)

    # the spec was ingested as its own medium ('spec'), not skipped
    assert spec_counts["spec"] == 1

    # the spec shows up as a first-class artifact of kind 'spec'
    arts = list_artifacts("t", db=db)
    assert any(a["kind"] == "spec" and a["path"].endswith("openapi.yaml") for a in arts)

    # the wedge connects the spec's server route to the code client, across repos
    conns = connections("t", cross_repo_only=True, db=db)
    m = [c for c in conns if c["key"] == "/api/v1/orders"]
    assert m, f"expected a cross-repo binding on /api/v1/orders, got {conns}"
    b = m[0]
    assert b["kind"] == "http"
    assert b["client_path"].endswith("client.py")
    assert b["server_path"].endswith("openapi.yaml")   # the spec serves it
    assert b["cross_repo"] == 1


def test_registry_resolves_spec_over_skip(tmp_path: Path):
    spec = tmp_path / "s.yaml"
    spec.write_text("openapi: 3.0.0\npaths: {}\n")
    plain = tmp_path / "data.yaml"
    plain.write_text("just: some\nrandom: yaml\n")
    assert isinstance(resolve(spec), OpenApiIngestor)
    assert resolve(plain) is None   # non-spec yaml isn't claimed by any ingestor
