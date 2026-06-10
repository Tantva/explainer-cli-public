"""Structural cross-repo binder (the wedge's connective tissue).

Scans the **full source** of every code artifact (so it sees route decorators and
module-level registrations that per-function chunks miss), extracts connectors via
the generic `connectors` registry, then binds each `client` to each `server`
sharing the same (kind, normalized key) across artifacts — emitting `bindings`.

This turns "the SDK posts to /api/x" + "Relay handles /api/x" into an asserted
edge, and "X produces topic events" + "Y consumes topic events" likewise.

Idempotent (clears + rebuilds). Generic: no project/language-specific logic — it
operates on whatever `connectors.extract` finds. Precision guard: skips keys that
match too many client×server pairs (likely an over-broad key).
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from . import connectors, store

_MAX_PAIRS_PER_KEY = 40  # noise guard: a key binding more than this is too generic


def _root_of(path: str, roots: list[str]) -> str | None:
    best = None
    for r in roots:
        if path.startswith(r) and (best is None or len(r) > len(best)):
            best = r
    return best


def resolve_structural(conn, workspace: str) -> int:
    """(Re)build cross-repo structural bindings for a workspace. Returns # created."""
    # Only rebuild the pattern-derived bindings; preserve agent-asserted ('llm') ones.
    conn.execute(
        "DELETE FROM edges WHERE workspace=? AND edge_type=? AND method='structural'",
        (workspace, store.BINDING))
    roots = store.list_sources(conn, workspace)
    arts = conn.execute(
        "SELECT id, path FROM artifacts WHERE workspace=? AND kind='code'", (workspace,)
    ).fetchall()

    servers: dict[tuple, list] = defaultdict(list)
    clients: dict[tuple, list] = defaultdict(list)
    for a in arts:
        try:
            text = Path(a["path"]).read_text("utf-8", "ignore")
        except OSError:
            continue
        root = _root_of(a["path"], roots)
        for kind, role, key_norm, _raw, line in connectors.extract(text):
            occ = {"artifact": a["id"], "line": line, "root": root}
            (servers if role == "server" else clients)[(kind, key_norm)].append(occ)

    # Connectors emitted by ingestors (e.g. an OpenAPI spec's server routes), stored as
    # generic `connector` edges. This is how a NON-CODE medium joins the wedge: its
    # declared routes/topics bind to client calls extracted from code, on (kind, key).
    for r in conn.execute(
        "SELECT json_extract(e.props,'$.kind') kind, json_extract(e.props,'$.role') role, "
        "       json_extract(e.props,'$.key_norm') key_norm, json_extract(e.props,'$.line') line, "
        "       json_extract(e.props,'$.artifact_id') artifact_id, a.path "
        "FROM edges e JOIN artifacts a ON a.id = json_extract(e.props,'$.artifact_id') "
        "WHERE e.workspace=? AND e.edge_type=?",
        (workspace, store.CONNECTOR),
    ).fetchall():
        occ = {"artifact": r["artifact_id"], "line": r["line"], "root": _root_of(r["path"], roots)}
        (servers if r["role"] == "server" else clients)[(r["kind"], r["key_norm"])].append(occ)

    created = 0
    seen: set[tuple] = set()
    for (kind, key), cl in clients.items():
        srv = servers.get((kind, key))
        if not srv or len(cl) * len(srv) > _MAX_PAIRS_PER_KEY:
            continue
        for c in cl:
            for s in srv:
                if (c["artifact"], c["line"]) == (s["artifact"], s["line"]):
                    continue
                sig = (kind, key, c["artifact"], c["line"], s["artifact"], s["line"])
                if sig in seen:
                    continue
                seen.add(sig)
                cross = 1 if (c["root"] and s["root"] and c["root"] != s["root"]) else 0
                conf = 0.55 if "{}" in key else 0.7
                props = json.dumps({
                    "kind": kind, "key": key,
                    "client_artifact": c["artifact"], "client_line": c["line"],
                    "server_artifact": s["artifact"], "server_line": s["line"],
                    "cross_repo": cross})
                conn.execute(
                    "INSERT INTO edges(workspace, edge_type, cross_source, confidence, method, provenance, props) "
                    "VALUES (?,?,0,?, 'structural', ?, ?)",
                    (workspace, store.BINDING, conf, json.dumps({"kind": kind, "key": key}), props),
                )
                created += 1
    return created
