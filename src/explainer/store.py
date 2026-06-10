"""SQLite-backed store for the explainer engine.

One DB per machine (default: ~/.explainer/explainer.db); rows are scoped by
``workspace``. The shape is deliberately a **grounded typed property-graph over a
document store**, so *any* lens (code, prose, recipe, …) fits without schema
changes:

- documents:  artifacts → chunks (text + a locator)
- graph:      entities (typed nodes) ──edges (typed relations)──> entities
- grounding:  mentions (entity ⇄ chunk)
- attributes: a generic ``props`` JSON bag on every table — a lens declares its
              own fields (a recipe's ``quantity``, a character's ``first_page``)
              with no migration.

There are **no privileged per-lens tables**: structural "bindings" and
"connectors" (the code lens's cross-repo wiring) are just rows in the generic
``edges`` table (``edge_type`` = 'binding' / 'connector', details in ``props``).
Code is one lens among peers.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DEFAULT_DB = Path.home() / ".explainer" / "explainer.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces (
    name        TEXT PRIMARY KEY,
    intent      TEXT,                   -- the questions the user wants to answer here; shapes the lens
    created_at  TEXT DEFAULT (datetime('now'))
);

-- An ingested file/source. `kind` is free-form (a lens chooses it): code|docs|pdf|spec|...
CREATE TABLE IF NOT EXISTS artifacts (
    id          INTEGER PRIMARY KEY,
    workspace   TEXT NOT NULL,
    path        TEXT NOT NULL,
    kind        TEXT NOT NULL,
    lang        TEXT,
    sha         TEXT,
    lens        TEXT,                   -- which lens indexed this artifact
    props       TEXT,                   -- generic JSON attribute bag
    ingested_at TEXT DEFAULT (datetime('now')),
    UNIQUE (workspace, path)
);

-- A retrievable span of an artifact (function, section, page, step, ...).
CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY,
    workspace   TEXT NOT NULL,
    artifact_id INTEGER NOT NULL REFERENCES artifacts(id),
    kind        TEXT,                   -- free-form: function|class|section|page|endpoint|...
    name        TEXT,
    start_line  INTEGER,                -- text locator (nullable for non-line media)
    end_line    INTEGER,
    text        TEXT NOT NULL,
    props       TEXT                    -- generic JSON attribute bag
);
CREATE INDEX IF NOT EXISTS idx_chunks_ws ON chunks(workspace);
CREATE INDEX IF NOT EXISTS idx_chunks_name ON chunks(workspace, name);

-- A typed node in the graph (symbol, service, character, ingredient, route, ...).
CREATE TABLE IF NOT EXISTS entities (
    id          INTEGER PRIMARY KEY,
    workspace   TEXT NOT NULL,
    name        TEXT NOT NULL,
    etype       TEXT,                   -- free-form node type (a lens chooses it)
    props       TEXT,                   -- generic JSON attribute bag
    UNIQUE (workspace, name, etype)
);
CREATE INDEX IF NOT EXISTS idx_entities_ws ON entities(workspace);

-- Where an entity was observed (graph ⇄ document grounding).
CREATE TABLE IF NOT EXISTS mentions (
    id          INTEGER PRIMARY KEY,
    workspace   TEXT NOT NULL,
    entity_id   INTEGER NOT NULL REFERENCES entities(id),
    chunk_id    INTEGER NOT NULL REFERENCES chunks(id),
    surface     TEXT
);

-- THE universal relation table. Entity↔entity edges (calls, co_occurs, doc_describes_code,
-- …) AND site-level relations a lens asserts (a code 'binding'/'connector' carries its
-- endpoints + channel in `props`, with src/dst NULL). No per-lens tables.
CREATE TABLE IF NOT EXISTS edges (
    id           INTEGER PRIMARY KEY,
    workspace    TEXT NOT NULL,
    src_id       INTEGER REFERENCES entities(id),   -- nullable: site-level edges
    dst_id       INTEGER REFERENCES entities(id),
    edge_type    TEXT NOT NULL,         -- calls|imports|doc_describes_code|binding|connector|...
    cross_source INTEGER DEFAULT 0,     -- 1 if it spans artifact kinds (the doc↔code wedge)
    confidence   REAL,
    method       TEXT,                  -- exact|fuzzy|structural|llm|...
    provenance   TEXT,                  -- JSON: contributing chunk_ids / evidence (the claim's source)
    asserted     INTEGER DEFAULT 1,     -- ADR-036 §A4: 0 = reported/contradicted, NOT committed as true
    props        TEXT,                  -- generic JSON attribute bag (endpoints, channel, ...)
    created_at   TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(workspace, src_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(workspace, dst_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(workspace, edge_type);

-- Ingested source roots per workspace (drives the semble content retriever).
CREATE TABLE IF NOT EXISTS sources (
    id          INTEGER PRIMARY KEY,
    workspace   TEXT NOT NULL,
    root_path   TEXT NOT NULL,
    added_at    TEXT DEFAULT (datetime('now')),
    UNIQUE (workspace, root_path)
);

-- PDF (and other binary) pages extracted to text on disk so semble can index them.
CREATE TABLE IF NOT EXISTS derived (
    id           INTEGER PRIMARY KEY,
    workspace    TEXT NOT NULL,
    derived_path TEXT NOT NULL,
    orig_path    TEXT NOT NULL,
    page         INTEGER,
    UNIQUE (workspace, derived_path)
);

-- The lens registry: a named, reusable indexing strategy (entity/relation/property
-- vocabulary + signals + extraction method). Global (reused across workspaces). Seed
-- lenses are 'coded'; the ingest runtime 'induces' new ones for unknown artifact types
-- and they are FROZEN on register so the wedge keeps a shared, joinable schema.
CREATE TABLE IF NOT EXISTS lenses (
    name        TEXT PRIMARY KEY,
    description TEXT,
    schema      TEXT NOT NULL,          -- JSON: entity_types/relation_types/properties/signals/method/discriminators
    kind        TEXT DEFAULT 'coded',   -- coded | induced
    version     INTEGER DEFAULT 1,
    frozen      INTEGER DEFAULT 1,
    created_at  TEXT DEFAULT (datetime('now'))
);
"""

# edge_type values that carry their endpoints in `props` (src/dst NULL), i.e. the
# code lens's cross-repo wiring living in the generic edges table.
BINDING = "binding"
CONNECTOR = "connector"


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring an older DB up to the generic property-graph shape: add `props`/`lens`
    bags, allow NULL edge endpoints, and fold the legacy `bindings`/`connectors`
    tables into `edges` (preserving data) before dropping them."""
    def cols(t):
        return {r["name"]: r for r in conn.execute(f"PRAGMA table_info({t})").fetchall()}
    tables = {r["name"] for r in
              conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

    for t in ("entities", "chunks", "artifacts"):
        c = cols(t)
        if "props" not in c:
            conn.execute(f"ALTER TABLE {t} ADD COLUMN props TEXT")
    if "lens" not in cols("artifacts"):
        conn.execute("ALTER TABLE artifacts ADD COLUMN lens TEXT")
    if "intent" not in cols("workspaces"):
        conn.execute("ALTER TABLE workspaces ADD COLUMN intent TEXT")
    if "edges" in tables and "asserted" not in cols("edges"):
        conn.execute("ALTER TABLE edges ADD COLUMN asserted INTEGER DEFAULT 1")

    # edges: rebuild if it still has NOT NULL endpoints or lacks `props`.
    ec = cols("edges")
    if ec and (("props" not in ec) or ec["src_id"]["notnull"] == 1):
        conn.executescript("""
            CREATE TABLE edges_new (
                id INTEGER PRIMARY KEY, workspace TEXT NOT NULL,
                src_id INTEGER REFERENCES entities(id), dst_id INTEGER REFERENCES entities(id),
                edge_type TEXT NOT NULL, cross_source INTEGER DEFAULT 0, confidence REAL,
                method TEXT, provenance TEXT, props TEXT, created_at TEXT DEFAULT (datetime('now')));
            INSERT INTO edges_new (id,workspace,src_id,dst_id,edge_type,cross_source,confidence,method,provenance,created_at)
                SELECT id,workspace,src_id,dst_id,edge_type,cross_source,confidence,method,provenance,created_at FROM edges;
            DROP TABLE edges;
            ALTER TABLE edges_new RENAME TO edges;
            CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(workspace, src_id, edge_type);
            CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(workspace, dst_id, edge_type);
            CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(workspace, edge_type);
        """)

    if "bindings" in tables:
        for b in conn.execute("SELECT * FROM bindings").fetchall():
            props = json.dumps({
                "kind": b["kind"], "key": b["key"],
                "client_artifact": b["client_artifact"], "client_line": b["client_line"],
                "server_artifact": b["server_artifact"], "server_line": b["server_line"],
                "cross_repo": b["cross_repo"]})
            conn.execute(
                "INSERT INTO edges(workspace,edge_type,cross_source,confidence,method,provenance,props) "
                "VALUES (?,?,0,?,?,?,?)",
                (b["workspace"], BINDING, b["confidence"], b["method"], b["provenance"], props))
        conn.execute("DROP TABLE bindings")
    if "connectors" in tables:
        for c in conn.execute("SELECT * FROM connectors").fetchall():
            props = json.dumps({"kind": c["kind"], "role": c["role"], "key_norm": c["key_norm"],
                                "key_raw": c["key_raw"], "artifact_id": c["artifact_id"], "line": c["line"]})
            conn.execute(
                "INSERT INTO edges(workspace,edge_type,method,props) VALUES (?,?,?,?)",
                (c["workspace"], CONNECTOR, "ingest", props))
        conn.execute("DROP TABLE connectors")
    conn.commit()


def connect(db_path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    """Open (and initialize/migrate) the store."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def ensure_workspace(conn: sqlite3.Connection, workspace: str) -> None:
    conn.execute("INSERT OR IGNORE INTO workspaces(name) VALUES (?)", (workspace,))
    conn.commit()


def create_workspace(conn: sqlite3.Connection, name: str) -> bool:
    """Create a workspace explicitly. Returns True if newly created, False if it existed."""
    cur = conn.execute("INSERT OR IGNORE INTO workspaces(name) VALUES (?)", (name,))
    conn.commit()
    return cur.rowcount > 0


def set_intent(conn: sqlite3.Connection, workspace: str, intent: str) -> None:
    """Record the questions the user wants to answer in this workspace (shapes the lens)."""
    conn.execute("UPDATE workspaces SET intent=? WHERE name=?", (intent, workspace))
    conn.commit()


def get_intent(conn: sqlite3.Connection, workspace: str) -> str | None:
    r = conn.execute("SELECT intent FROM workspaces WHERE name=?", (workspace,)).fetchone()
    return r["intent"] if r else None


def add_source(conn: sqlite3.Connection, workspace: str, root_path: str) -> None:
    """Record an ingested source root (for the content retriever)."""
    conn.execute("INSERT OR IGNORE INTO sources(workspace, root_path) VALUES (?,?)",
                 (workspace, root_path))
    conn.commit()


def list_sources(conn: sqlite3.Connection, workspace: str) -> list[str]:
    return [r["root_path"] for r in
            conn.execute("SELECT root_path FROM sources WHERE workspace=?", (workspace,)).fetchall()]


def add_connector(conn, workspace, artifact_id, kind, role, key_norm, key_raw=None, line=None) -> None:
    """Record a connector an ingestor extracted (a route a spec serves, a topic, …) as
    a generic `connector` edge — so a non-code medium can feed the structural binder."""
    props = json.dumps({"kind": kind, "role": role, "key_norm": key_norm,
                        "key_raw": key_raw, "artifact_id": artifact_id, "line": line})
    conn.execute("INSERT INTO edges(workspace, edge_type, method, props) VALUES (?,?,?,?)",
                 (workspace, CONNECTOR, "ingest", props))


def clear_connectors(conn, artifact_id) -> None:
    """Drop an artifact's connector edges (idempotent re-ingest)."""
    conn.execute(
        "DELETE FROM edges WHERE edge_type=? AND json_extract(props,'$.artifact_id')=?",
        (CONNECTOR, artifact_id))


def merge_entities(conn, workspace, keep_id: int, drop_ids: list[int]) -> int:
    """Fuse duplicate entities into `keep_id` (ADR-036 §B3, the knowledge-fusion stage):
    re-point all mentions + edges from the dropped ids to the kept one, fold the dropped
    names into the kept entity's `aliases` prop, then delete the dropped rows. Returns how
    many were merged. Idempotent-safe: drops equal to keep are ignored."""
    drop_ids = [d for d in dict.fromkeys(drop_ids) if d != keep_id]
    if not drop_ids:
        return 0
    marks = ",".join("?" * len(drop_ids))
    names = [r["name"] for r in
             conn.execute(f"SELECT name FROM entities WHERE id IN ({marks})", drop_ids).fetchall()]
    keep = conn.execute("SELECT props FROM entities WHERE id=?", (keep_id,)).fetchone()
    props = json.loads(keep["props"] or "{}") if keep else {}
    aliases = set(props.get("aliases") or [])
    aliases.update(names)
    props["aliases"] = sorted(aliases)
    conn.execute("UPDATE entities SET props=? WHERE id=?", (json.dumps(props), keep_id))
    conn.execute(f"UPDATE mentions SET entity_id=? WHERE entity_id IN ({marks})", (keep_id, *drop_ids))
    conn.execute(f"UPDATE edges SET src_id=? WHERE src_id IN ({marks})", (keep_id, *drop_ids))
    conn.execute(f"UPDATE edges SET dst_id=? WHERE dst_id IN ({marks})", (keep_id, *drop_ids))
    conn.execute(f"DELETE FROM entities WHERE id IN ({marks})", drop_ids)
    return len(drop_ids)


def add_derived(conn, workspace, derived_path, orig_path, page=None) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO derived(workspace, derived_path, orig_path, page) VALUES (?,?,?,?)",
        (workspace, derived_path, orig_path, page))
    conn.commit()


def derived_map(conn, workspace) -> dict:
    """abs derived .txt path -> {orig_path, page} for citation mapping."""
    return {
        r["derived_path"]: {"orig_path": r["orig_path"], "page": r["page"]}
        for r in conn.execute(
            "SELECT derived_path, orig_path, page FROM derived WHERE workspace=?",
            (workspace,)).fetchall()
    }
