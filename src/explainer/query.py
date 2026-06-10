"""Retrieval helpers used by the MCP tools (and the direct CLI).

Lean v1: keyword (SQL LIKE) + graph traversal over the synthesized edges. Local
embeddings are an opt-in extra, wired here later if time permits (ADR-033).
Outputs are compact, citation-ready dicts — Claude Code reads these.
"""
from __future__ import annotations

import json

from . import store


def _conn(db=store.DEFAULT_DB):
    return store.connect(db)


# ----------------------------------------------------------------- workspace lifecycle

def create_workspace(name: str, db=store.DEFAULT_DB) -> dict:
    """Set up a workspace (idempotent)."""
    conn = _conn(db)
    created = store.create_workspace(conn, name)
    conn.close()
    return {"workspace": name, "created": bool(created)}


def list_workspaces(db=store.DEFAULT_DB) -> list[dict]:
    """All configured workspaces with artifact counts (answers 'how many workspaces')."""
    conn = _conn(db)
    rows = conn.execute("SELECT name, created_at FROM workspaces ORDER BY created_at").fetchall()
    out = []
    for r in rows:
        bk = conn.execute(
            "SELECT kind, COUNT(*) n FROM artifacts WHERE workspace=? GROUP BY kind",
            (r["name"],),
        ).fetchall()
        by_kind = {x["kind"]: x["n"] for x in bk}
        out.append({
            "name": r["name"],
            "created_at": r["created_at"],
            "artifacts": sum(by_kind.values()),
            "by_kind": by_kind,
        })
    conn.close()
    return out


def set_intent(workspace: str, intent: str, db=store.DEFAULT_DB) -> dict:
    """Record what the user wants to ask of this workspace — this shapes the lens at
    ingest (which entities/relations to extract and type). Stored for provenance and
    so the indexing can be re-shaped later if the questions change."""
    conn = _conn(db)
    store.ensure_workspace(conn, workspace)
    store.set_intent(conn, workspace, intent)
    conn.close()
    return {"workspace": workspace, "intent": intent}


def list_artifacts(workspace: str, db=store.DEFAULT_DB) -> list[dict]:
    """Everything ingested in a workspace (answers 'what artifacts are ingested')."""
    conn = _conn(db)
    rows = conn.execute(
        "SELECT id, path, kind, lang, lens, json_extract(props,'$.provenance') AS provenance, "
        "ingested_at FROM artifacts WHERE workspace=? ORDER BY kind, path",
        (workspace,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def clear_synthesized(workspace: str, db=store.DEFAULT_DB) -> dict:
    """Remove generated (provenance='synthesized') artifacts + their chunks/mentions —
    so the wiki can be regenerated cleanly. Primary (user) content is untouched. The
    caller re-ingests afterward, which rebuilds the doc↔code edges."""
    conn = _conn(db)
    arts = [r["id"] for r in conn.execute(
        "SELECT id FROM artifacts WHERE workspace=? AND json_extract(props,'$.provenance')='synthesized'",
        (workspace,)).fetchall()]
    for aid in arts:
        cids = [r["id"] for r in conn.execute("SELECT id FROM chunks WHERE artifact_id=?", (aid,)).fetchall()]
        if cids:
            marks = ",".join("?" * len(cids))
            conn.execute(f"DELETE FROM mentions WHERE chunk_id IN ({marks})", cids)
        conn.execute("DELETE FROM chunks WHERE artifact_id=?", (aid,))
        conn.execute("DELETE FROM artifacts WHERE id=?", (aid,))
    conn.commit()
    conn.close()
    return {"removed": len(arts)}


def _keyword_search(workspace: str, q: str, k: int, db) -> list[dict]:
    conn = _conn(db)
    rows = conn.execute(
        """
        SELECT c.id, c.kind, c.name, c.start_line, c.end_line, a.path, a.kind AS artifact_kind,
               substr(c.text, 1, 600) AS preview
        FROM chunks c JOIN artifacts a ON a.id = c.artifact_id
        WHERE c.workspace = ? AND (c.text LIKE ? OR c.name LIKE ?)
        LIMIT ?
        """,
        (workspace, f"%{q}%", f"%{q}%", k),
    ).fetchall()
    conn.close()
    return [{**dict(r), "retriever": "keyword"} for r in rows]


_CODE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go", ".java", ".rb"}


def _kind_for(path: str) -> str:
    from pathlib import Path
    return "code" if Path(path).suffix.lower() in _CODE_EXTS else "docs"


def search(workspace: str, q: str, k: int = 8, db=store.DEFAULT_DB) -> list[dict]:
    """Find relevant chunks. Uses **semble** (Model2Vec + BM25 + code-aware rerank)
    over the workspace's source roots (code, docs, config, and derived PDF text) when
    available; falls back to keyword search otherwise. PDF hits are mapped back to the
    original PDF + page for citation."""
    from . import retriever
    if retriever.available():
        conn = _conn(db)
        roots = store.list_sources(conn, workspace)
        dmap = store.derived_map(conn, workspace)
        conn.close()
        hits = retriever.search_roots(roots, q, k) if roots else []
        if hits:
            for h in hits:
                d = dmap.get(h.get("path"))
                if d:  # a derived PDF page → cite the original PDF + page
                    h["path"] = d["orig_path"]
                    h["page"] = d["page"]
                    h["artifact_kind"] = "pdf"
                else:
                    h["artifact_kind"] = _kind_for(h.get("path") or "")
            return hits
    return _keyword_search(workspace, q, k, db)


def cross_edges(workspace: str, name: str, min_confidence: float = 0.0, db=store.DEFAULT_DB) -> list[dict]:
    """The wedge at query time: cross-source edges touching an entity by name."""
    conn = _conn(db)
    rows = conn.execute(
        """
        SELECT e.edge_type, e.confidence, e.method, e.provenance, e.asserted,
               s.name AS src, s.etype AS src_type,
               d.name AS dst, d.etype AS dst_type
        FROM edges e
        JOIN entities s ON s.id = e.src_id
        JOIN entities d ON d.id = e.dst_id
        WHERE e.workspace = ? AND e.cross_source = 1 AND e.confidence >= ?
          AND (s.name = ? OR d.name = ?)
        """,
        (workspace, min_confidence, name, name),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def chunks(workspace: str, kind: str | None = None, limit: int = 200, offset: int = 0,
           db=store.DEFAULT_DB) -> list[dict]:
    """Paginated access to the workspace's chunks — the substrate the ingest skill iterates for
    the schema-guided LLM extraction phase (ADR-036). Returns id + locator + a preview; pull full
    text with get_chunk. `kind` filters by artifact kind (code/docs/pdf/spec)."""
    conn = _conn(db)
    sql = ("SELECT c.id, c.kind, c.name, c.start_line, c.end_line, a.path, a.kind AS artifact_kind, "
           "substr(c.text,1,400) AS preview FROM chunks c JOIN artifacts a ON a.id=c.artifact_id "
           "WHERE c.workspace=?")
    args: list = [workspace]
    if kind:
        sql += " AND a.kind=?"
        args.append(kind)
    sql += " ORDER BY c.id LIMIT ? OFFSET ?"
    args += [limit, offset]
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_chunk(workspace: str, chunk_id: int, db=store.DEFAULT_DB) -> dict | None:
    conn = _conn(db)
    r = conn.execute(
        "SELECT c.*, a.path, a.kind AS artifact_kind FROM chunks c "
        "JOIN artifacts a ON a.id = c.artifact_id WHERE c.workspace=? AND c.id=?",
        (workspace, chunk_id),
    ).fetchone()
    conn.close()
    return dict(r) if r else None


def overview(workspace: str, db=store.DEFAULT_DB) -> dict:
    """Workspace summary: artifact counts by kind + top cross-source connections."""
    conn = _conn(db)
    arts = conn.execute(
        "SELECT kind, COUNT(*) n FROM artifacts WHERE workspace=? GROUP BY kind",
        (workspace,),
    ).fetchall()
    xedges = conn.execute(
        "SELECT COUNT(*) n FROM edges WHERE workspace=? AND cross_source=1", (workspace,)
    ).fetchone()
    binds = conn.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(json_extract(props,'$.cross_repo')),0) x "
        "FROM edges WHERE workspace=? AND edge_type=?",
        (workspace, store.BINDING),
    ).fetchone()
    intent = store.get_intent(conn, workspace)
    conn.close()
    return {
        "workspace": workspace,
        "intent": intent,
        "artifacts_by_kind": {r["kind"]: r["n"] for r in arts},
        "cross_source_edges": xedges["n"] if xedges else 0,
        "structural_bindings": binds["n"] if binds else 0,
        "cross_repo_bindings": binds["x"] if binds else 0,
    }


def connections(workspace: str, kind: str | None = None, min_confidence: float = 0.0,
                cross_repo_only: bool = False, db=store.DEFAULT_DB) -> list[dict]:
    """Structural cross-repo connections (the binder's output): client site → server
    site over an HTTP route or queue topic, with confidence + both code locations."""
    conn = _conn(db)
    sql = """
        SELECT json_extract(e.props,'$.kind') AS kind,
               json_extract(e.props,'$.key') AS key,
               json_extract(e.props,'$.cross_repo') AS cross_repo,
               e.confidence, e.method,
               ca.path AS client_path, json_extract(e.props,'$.client_line') AS client_line,
               sa.path AS server_path, json_extract(e.props,'$.server_line') AS server_line
        FROM edges e
        JOIN artifacts ca ON ca.id = json_extract(e.props,'$.client_artifact')
        JOIN artifacts sa ON sa.id = json_extract(e.props,'$.server_artifact')
        WHERE e.workspace = ? AND e.edge_type = ? AND e.confidence >= ?
    """
    args: list = [workspace, store.BINDING, min_confidence]
    if kind:
        sql += " AND json_extract(e.props,'$.kind') = ?"
        args.append(kind)
    if cross_repo_only:
        sql += " AND json_extract(e.props,'$.cross_repo') = 1"
    sql += " ORDER BY cross_repo DESC, e.confidence DESC, kind"
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ----------------------------------------------------------------- LLM-assist binding

def _root_of(path: str, roots: list[str]) -> str | None:
    best = None
    for r in roots:
        if path.startswith(r) and (best is None or len(r) > len(best)):
            best = r
    return best


def _resolve_artifact(conn, workspace: str, path: str) -> int | None:
    r = conn.execute(
        "SELECT id FROM artifacts WHERE workspace=? AND path=?", (workspace, path)
    ).fetchone()
    if r:
        return r["id"]
    # lenient: match by suffix (agent may pass a relative path)
    r = conn.execute(
        "SELECT id FROM artifacts WHERE workspace=? AND path LIKE ? ORDER BY length(path) LIMIT 1",
        (workspace, f"%{path}"),
    ).fetchone()
    return r["id"] if r else None


def binding_candidates(workspace: str, kind: str | None = None, limit: int = 25,
                       db=store.DEFAULT_DB) -> dict:
    """Worklist for LLM-assisted binding: connector endpoints that pattern-matching
    left UNconnected — `unbound_servers` (routes/topics defined but no literal caller
    found) and `unbound_clients` (calls with no literal server). The agent finds the
    dynamic other side (via search/get_chunk) and records it with assert_binding."""
    from collections import defaultdict
    from pathlib import Path
    from . import connectors

    conn = _conn(db)
    arts = conn.execute(
        "SELECT id, path FROM artifacts WHERE workspace=? AND kind='code'", (workspace,)
    ).fetchall()
    conn.close()

    servers: dict[tuple, list] = defaultdict(list)
    clients: dict[tuple, list] = defaultdict(list)
    for a in arts:
        try:
            text = Path(a["path"]).read_text("utf-8", "ignore")
        except OSError:
            continue
        for k, role, key_norm, _raw, line in connectors.extract(text):
            if kind and k != kind:
                continue
            (servers if role == "server" else clients)[(k, key_norm)].append(
                {"kind": k, "key": key_norm, "path": a["path"], "line": line}
            )

    unbound_servers = [occ[0] for key, occ in servers.items() if key not in clients]
    unbound_clients = [occ[0] for key, occ in clients.items() if key not in servers]
    return {
        "unbound_servers": unbound_servers[:limit],
        "unbound_clients": unbound_clients[:limit],
    }


# ----------------------------------------------------------------- generic graph traversal
# Schema-free door to the graph: the session reasons in domain terms (entities, types,
# neighbors), never SQL. Works for ANY lens (a code 'function', a prose 'place').

def entities(workspace: str, etype: str | None = None, limit: int = 100,
             db=store.DEFAULT_DB) -> list[dict]:
    """List entities (graph nodes), optionally filtered by type — e.g. the 'place's or
    'character's of a book, the 'function's of a repo. Ranked by mention count."""
    conn = _conn(db)
    sql = "SELECT name, etype, props FROM entities WHERE workspace=?"
    args: list = [workspace]
    if etype:
        sql += " AND etype=?"
        args.append(etype)
    sql += " ORDER BY COALESCE(json_extract(props,'$.count'),0) DESC, name LIMIT ?"
    args.append(limit)
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    out = []
    for r in rows:
        p = json.loads(r["props"] or "{}")
        out.append({"name": r["name"], "type": r["etype"],
                    "count": p.get("count"), "first_page": p.get("first_page")})
    return out


def neighbors(workspace: str, name: str, relation: str | None = None,
              etype: str | None = None, limit: int = 50, db=store.DEFAULT_DB) -> list[dict]:
    """Entities connected to `name` in the graph — optionally filtered by `relation`
    (e.g. 'co_occurs', 'calls') and/or neighbor `etype` (e.g. 'place'). Answers
    'what places does Paul go', 'what calls verify_jwt'. Ranked by edge weight."""
    conn = _conn(db)
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM entities WHERE workspace=? AND name=?", (workspace, name)).fetchall()]
    if not ids:
        conn.close()
        return []
    marks = ",".join("?" * len(ids))
    sql = f"""
        SELECT CASE WHEN e.src_id IN ({marks}) THEN d.name ELSE s.name END AS other,
               CASE WHEN e.src_id IN ({marks}) THEN d.etype ELSE s.etype END AS other_type,
               e.edge_type, e.confidence, e.props
        FROM edges e JOIN entities s ON s.id=e.src_id JOIN entities d ON d.id=e.dst_id
        WHERE e.workspace=? AND (e.src_id IN ({marks}) OR e.dst_id IN ({marks}))
    """
    args: list = [*ids, *ids, workspace, *ids, *ids]
    if relation:
        sql += " AND e.edge_type=?"
        args.append(relation)
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    out = []
    for r in rows:
        if etype and r["other_type"] != etype:
            continue
        p = json.loads(r["props"] or "{}")
        out.append({"entity": r["other"], "type": r["other_type"], "relation": r["edge_type"],
                    "weight": p.get("shared"), "confidence": r["confidence"],
                    "first_page": p.get("first_page")})
    out.sort(key=lambda d: (d.get("weight") or d.get("confidence") or 0), reverse=True)
    return out[:limit]


# ----------------------------------------------------------------- entity typing (ingest)
# The ingest runtime classifies the cheap gazetteer into the lens's entity_types and
# drops noise — one bounded reasoning pass, no SQL crossing the boundary.

def pending_entities(workspace: str, limit: int = 120, db=store.DEFAULT_DB) -> list[dict]:
    """Provisional (untyped) entities a lens extracted, each with a sample context, for
    the ingest runtime to classify. Returns name + current_type + count + sample."""
    conn = _conn(db)
    rows = conn.execute(
        """
        SELECT e.name, e.etype, e.props,
            (SELECT substr(replace(replace(c.text, char(10), ' '), char(13), ' '), 1, 220)
             FROM mentions m JOIN chunks c ON c.id=m.chunk_id WHERE m.entity_id=e.id LIMIT 1) AS sample
        FROM entities e
        WHERE e.workspace=? AND json_extract(e.props,'$.provisional')=1
        ORDER BY COALESCE(json_extract(e.props,'$.count'),0) DESC LIMIT ?
        """,
        (workspace, limit),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        p = json.loads(r["props"] or "{}")
        out.append({"name": r["name"], "current_type": r["etype"],
                    "count": p.get("count"), "sample": r["sample"]})
    return out


def classify_entities(workspace: str, types: dict, db=store.DEFAULT_DB) -> dict:
    """Apply the ingest runtime's typing: `types` maps entity name -> a lens entity_type
    ('place'/'character'/'concept'/...) or 'drop' to remove noise (entity + its mentions
    + edges). Only affects provisional entities. Returns counts."""
    conn = _conn(db)
    typed = dropped = 0
    for name, t in types.items():
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM entities WHERE workspace=? AND name=? AND json_extract(props,'$.provisional')=1",
            (workspace, name)).fetchall()]
        if not ids:
            continue
        marks = ",".join("?" * len(ids))
        if t == "drop":
            conn.execute(f"DELETE FROM mentions WHERE entity_id IN ({marks})", ids)
            conn.execute(f"DELETE FROM edges WHERE src_id IN ({marks}) OR dst_id IN ({marks})", [*ids, *ids])
            conn.execute(f"DELETE FROM entities WHERE id IN ({marks})", ids)
            dropped += 1
        else:
            for rid in ids:
                conn.execute(
                    "UPDATE entities SET etype=?, props=json_remove(props,'$.provisional') WHERE id=?",
                    (t, rid))
            typed += 1
    conn.commit()
    conn.close()
    return {"typed": typed, "dropped": dropped}


# ----------------------------------------------------------------- targeted extraction (ingest)
# The write door, symmetric to entities/neighbors. For entity types the cheap gazetteer
# can't produce (quotes, costumes, events — not proper nouns), the session retrieves the
# passages (search) and writes structured nodes/edges into the SAME generic graph.

def add_entity(workspace: str, name: str, etype: str, props: dict | None = None,
               chunk_ids: list | None = None, db=store.DEFAULT_DB) -> dict:
    """Add/update a typed graph node the session extracted (a quote, a costume, an event).
    `props` is freeform (e.g. {"text":..., "speaker":..., "page":12}); optional `chunk_ids`
    attach provenance. Tagged origin='extracted' so a lens re-ingest won't clear it."""
    conn = _conn(db)
    store.ensure_workspace(conn, workspace)
    p = dict(props or {})
    p.setdefault("origin", "extracted")
    conn.execute(
        "INSERT INTO entities(workspace, name, etype, props) VALUES (?,?,?,?) "
        "ON CONFLICT(workspace, name, etype) DO UPDATE SET props=excluded.props",
        (workspace, name, etype, json.dumps(p)))
    eid = conn.execute("SELECT id FROM entities WHERE workspace=? AND name=? AND etype=?",
                       (workspace, name, etype)).fetchone()["id"]
    for cid in (chunk_ids or []):
        conn.execute("INSERT INTO mentions(workspace, entity_id, chunk_id, surface) VALUES (?,?,?,?)",
                     (workspace, eid, cid, name))
    conn.commit()
    conn.close()
    return {"ok": True, "id": eid, "name": name, "type": etype}


def add_relation(workspace: str, src: str, dst: str, relation: str, props: dict | None = None,
                 confidence: float = 0.8, asserted: bool = True, db=store.DEFAULT_DB) -> dict:
    """Add a typed claim between two existing entities (by name) the session related —
    e.g. a character 'wears' a costume, 'allied_with' a faction. Resolves each name to
    its most-mentioned entity. Add the entities first (add_entity) if they're new.

    `asserted` (ADR-036 §A4): pass False for a reported-but-not-committed claim — e.g. a
    doc says X but the code contradicts it. The claim is stored and citable, but the graph
    does not assert it as true. Default True."""
    conn = _conn(db)

    def _rid(n):
        r = conn.execute(
            "SELECT id FROM entities WHERE workspace=? AND name=? "
            "ORDER BY COALESCE(json_extract(props,'$.count'),0) DESC LIMIT 1", (workspace, n)).fetchone()
        return r["id"] if r else None

    s, d = _rid(src), _rid(dst)
    if s is None or d is None:
        conn.close()
        return {"ok": False, "error": f"entity not found: {src if s is None else dst}"}
    conn.execute(
        "INSERT INTO edges(workspace, src_id, dst_id, edge_type, confidence, method, asserted, props) "
        "VALUES (?,?,?,?,?, 'extracted', ?, ?)",
        (workspace, s, d, relation, confidence, 1 if asserted else 0, json.dumps(props or {})))
    conn.commit()
    conn.close()
    return {"ok": True, "src": src, "dst": dst, "relation": relation, "asserted": asserted}


def resolve_entities(workspace: str, etype: str | None = None, embeddings: bool = True,
                     threshold: float = 0.9, db=store.DEFAULT_DB) -> dict:
    """Run the entity-resolution / canonicalization stage (ADR-036 §B3): collapse alias
    surface forms into canonical nodes, within each type. Deterministic normalization always;
    embedding (Model2Vec) pass when available. Use after ingest/extraction."""
    from . import primitives
    conn = _conn(db)
    cfg: dict = {"embeddings": embeddings, "threshold": threshold}
    if etype:
        cfg["etype"] = etype
    res = primitives._alias_merge(conn, workspace, "", cfg)
    conn.commit()
    conn.close()
    return res


def merge_entities(workspace: str, keep: str, drop: list[str], db=store.DEFAULT_DB) -> dict:
    """LLM-confirmed merge (the human/agent-in-the-loop half of ER): fold the `drop` names into
    the `keep` entity. Use when the agent has confirmed two surface forms are the same entity
    that automated resolution didn't catch. Resolves names to their most-mentioned entity."""
    conn = _conn(db)

    def _rid(n):
        r = conn.execute(
            "SELECT id FROM entities WHERE workspace=? AND name=? "
            "ORDER BY COALESCE(json_extract(props,'$.count'),0) DESC LIMIT 1", (workspace, n)).fetchone()
        return r["id"] if r else None

    k = _rid(keep)
    if k is None:
        conn.close()
        return {"ok": False, "error": f"keep entity not found: {keep}"}
    drops = [d for d in (_rid(n) for n in drop) if d is not None]
    n = store.merge_entities(conn, workspace, k, drops)
    conn.commit()
    conn.close()
    return {"ok": True, "keep": keep, "merged": n}


def assert_binding(workspace: str, kind: str, key: str,
                   client_path: str, client_line: int,
                   server_path: str, server_line: int,
                   confidence: float = 0.8, rationale: str = "",
                   db=store.DEFAULT_DB) -> dict:
    """Record a cross-repo binding the agent reasoned out (method='llm'). Use after
    confirming, via the code, that a dynamic client (constructed URL / produced topic)
    targets a server (route / consumer) that literal pattern-matching couldn't link."""
    import json
    conn = _conn(db)
    ca = _resolve_artifact(conn, workspace, client_path)
    sa = _resolve_artifact(conn, workspace, server_path)
    if ca is None or sa is None:
        conn.close()
        missing = client_path if ca is None else server_path
        return {"ok": False, "error": f"artifact not found in workspace: {missing}"}
    roots = store.list_sources(conn, workspace)
    cross = 1 if (_root_of(client_path, roots) and _root_of(server_path, roots)
                  and _root_of(client_path, roots) != _root_of(server_path, roots)) else 0
    # idempotent: replace an existing llm binding for the same client/server/key
    conn.execute(
        "DELETE FROM edges WHERE workspace=? AND edge_type=? AND method='llm' "
        "AND json_extract(props,'$.kind')=? AND json_extract(props,'$.key')=? "
        "AND json_extract(props,'$.client_artifact')=? AND json_extract(props,'$.server_artifact')=?",
        (workspace, store.BINDING, kind, key, ca, sa),
    )
    props = json.dumps({"kind": kind, "key": key, "client_artifact": ca, "client_line": client_line,
                        "server_artifact": sa, "server_line": server_line, "cross_repo": cross})
    conn.execute(
        "INSERT INTO edges(workspace, edge_type, cross_source, confidence, method, provenance, props) "
        "VALUES (?,?,0,?, 'llm', ?, ?)",
        (workspace, store.BINDING, confidence,
         json.dumps({"kind": kind, "key": key, "rationale": rationale}), props),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "kind": kind, "key": key, "cross_repo": cross, "confidence": confidence}
