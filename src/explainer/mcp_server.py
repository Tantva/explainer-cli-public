"""MCP server — exposes the explainer engine to the user's Claude Code session.

Claude Code is the master agent: it calls these tools to gather cross-artifact
evidence and synthesizes a grounded, cited answer itself.

Run: `explainer-mcp` (or `uv run explainer-mcp`). Registered via the plugin's .mcp.json.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import ingest as _ingest
from . import query as _query

mcp = FastMCP("explainer")


# --- workspace lifecycle ------------------------------------------------------

@mcp.tool()
def create_workspace(name: str) -> dict:
    """Set up a workspace (a named, isolated corpus). Idempotent. Do this first,
    then ingest into it."""
    return _query.create_workspace(name)


@mcp.tool()
def list_workspaces() -> list[dict]:
    """List all configured workspaces with artifact counts — answers
    'how many workspaces are configured' / 'what workspaces exist'."""
    return _query.list_workspaces()


@mcp.tool()
def list_artifacts(workspace: str = "default") -> list[dict]:
    """List everything ingested in a workspace (path, kind, lang, time) — answers
    'what artifacts are ingested in this workspace'."""
    return _query.list_artifacts(workspace)


# --- lens-driven ingestion ----------------------------------------------------

@mcp.tool()
def set_intent(workspace: str, intent: str) -> dict:
    """Record what the user wants to ASK of this workspace (their questions/goals). Do
    this BEFORE choosing a lens — the intent shapes which entity_types and relations the
    lens extracts and types. The artifact says what's *possible*; the intent says what's
    *wanted*; the lens is the intersection. Stored for provenance + later re-shaping."""
    return _query.set_intent(workspace, intent)


@mcp.tool()
def inspect(path: str) -> dict:
    """Sample an artifact (dir tree + extensions, or a PDF's TOC + first page, or a
    file head) so you can choose a lens on evidence. Call this BEFORE ingest for an
    unfamiliar source, then compare against list_lenses()."""
    from . import inspect as _inspect
    return _inspect.inspect_artifact(path)


@mcp.tool()
def list_lenses() -> list[dict]:
    """The registered lenses (indexing strategies) with their discriminators. Match an
    inspected artifact to one of these; if none fits, induce a new lens with
    register_lens, then ingest with it. (Code/docs/specs use the 'code' lens; books
    and long-form prose use 'prose'.)"""
    from . import lens as _lens
    return _lens.list_lenses()


@mcp.tool()
def get_lens(name: str) -> dict | None:
    """A single lens with its full schema — including its `synthesis` plan (what docs to
    generate, how to decompose, what to ground on). The wiki skill reads this."""
    from . import lens as _lens
    return _lens.get_lens(name)


@mcp.tool()
def register_lens(name: str, description: str, schema: dict) -> dict:
    """Register a NEW induced lens for an artifact type no existing lens fits. `schema`
    declares: discriminators, entity_types, relation_types, properties (entity_type ->
    [fields]), signals, method. Lenses are FROZEN once registered (reuse keeps the
    graph joinable) — pick a fresh name. Then ingest with lens=<name>."""
    from . import lens as _lens
    return _lens.register_lens(name, description, schema)


@mcp.tool()
def ingest(path: str, workspace: str = "default", lens: str | None = None,
           provenance: str = "primary") -> dict:
    """Ingest a corpus at `path` into `workspace`, then run cross-artifact synthesis.
    `lens` selects the indexing strategy (see list_lenses): omit for code/docs/specs;
    pass 'prose' for a book/long-form text. `provenance`: 'primary' for the user's corpus
    (default); 'synthesized' when indexing back a generated wiki (the wiki skill uses this).
    Returns counts incl. cross_source_edges."""
    return _ingest.ingest_path(path, workspace, lens=lens, provenance=provenance)


@mcp.tool()
def clear_synthesized(workspace: str = "default") -> dict:
    """Remove generated (provenance='synthesized') artifacts so a wiki can be regenerated
    cleanly. Primary (user) content is untouched. Call before regenerating, then re-ingest."""
    return _query.clear_synthesized(workspace)


@mcp.tool()
def pending_entities(workspace: str = "default", limit: int = 120) -> list[dict]:
    """After a lens ingest, the provisional (untyped) entities it extracted — each with a
    sample context. THE TYPING STEP: read these and classify each into the lens's
    entity_types (place/character/concept/...) or 'drop' for noise, then call
    classify_entities. One bounded pass; be generous, it cleans the graph."""
    return _query.pending_entities(workspace, limit)


@mcp.tool()
def classify_entities(workspace: str, types: dict) -> dict:
    """Apply your typing: `types` maps each entity name -> a lens entity_type
    ('place'/'character'/'concept'/...) or 'drop' to remove noise (sentence-start words,
    fragments). Only affects provisional entities. Makes 'list the places' / 'who does X
    meet' first-class graph queries."""
    return _query.classify_entities(workspace, types)


@mcp.tool()
def add_entity(workspace: str, name: str, etype: str, props: dict | None = None) -> dict:
    """TARGETED EXTRACTION (the write door). Add a typed node you extracted from passages
    that the gazetteer can't find — a `quote`, a `costume`, an `event` (non-proper-noun
    types). `props` is freeform: a quote → {"text":..., "speaker":..., "page":N}; a costume
    → {"description":..., "page":N}. Retrieve passages with search first, then write."""
    return _query.add_entity(workspace, name, etype, props)


@mcp.tool()
def add_relation(workspace: str, src: str, dst: str, relation: str,
                 props: dict | None = None, confidence: float = 0.8, asserted: bool = True) -> dict:
    """Add a typed claim between two existing entities (by name) — e.g. a character `wears`
    a costume, `said` a quote, is `allied_with` a faction. Add the entities first with
    add_entity if new. This is how targeted extraction wires non-gazetteer facts into the
    same graph the read tools (entities/neighbors) traverse. Pass `asserted=False` for a
    reported-but-contradicted claim (e.g. a doc that disagrees with the code): it's stored
    and citable but not committed as true (ADR-036)."""
    return _query.add_relation(workspace, src, dst, relation, props, confidence, asserted)


# --- ask / investigate --------------------------------------------------------

@mcp.tool()
def resolve_entities(workspace: str = "default", etype: str | None = None,
                     embeddings: bool = True, threshold: float = 0.9) -> dict:
    """ENTITY RESOLUTION (the fusion stage): collapse alias surface forms of the same entity
    into one canonical node, within each type — so "the Borrower"/"Borrower" or a character's
    given-name/surname/honorific stop inflating counts and rankings. Deterministic name
    normalization always; an embedding pass catches near-dups. Run after ingest/extraction."""
    return _query.resolve_entities(workspace, etype, embeddings, threshold)


@mcp.tool()
def merge_entities(workspace: str, keep: str, drop: list[str]) -> dict:
    """LLM-confirmed merge: fold the `drop` entity names into the `keep` entity. Use when you've
    confirmed (from the text) that surface forms are the same entity and automated resolution
    missed it — the human/agent-in-the-loop half of entity resolution (ADR-036)."""
    return _query.merge_entities(workspace, keep, drop)


@mcp.tool()
def overview(workspace: str = "default") -> dict:
    """Workspace summary: artifact counts by kind + number of cross-source edges.
    Call this first to orient before answering."""
    return _query.overview(workspace)


@mcp.tool()
def search(query: str, workspace: str = "default", k: int = 8) -> list[dict]:
    """Keyword search over ingested chunks (code/docs/pdf). Returns citation-ready
    records (path, artifact_kind, name, lines, preview)."""
    return _query.search(workspace, query, k)


@mcp.tool()
def cross_edges(name: str, workspace: str = "default", min_confidence: float = 0.0) -> list[dict]:
    """THE WEDGE: cross-source edges touching the entity `name` — e.g. which code a
    doc describes. Each edge carries confidence + provenance (contributing chunks)."""
    return _query.cross_edges(workspace, name, min_confidence)


@mcp.tool()
def connections(workspace: str = "default", kind: str | None = None,
                min_confidence: float = 0.0, cross_repo_only: bool = False) -> list[dict]:
    """THE WEDGE (structural): cross-repo connections — a client (HTTP call / queue
    producer) bound to a server (route handler / consumer) over the same route or
    topic, with both code locations + confidence. Use for 'how do these services
    talk to each other' and for tracing a flow across repos. `kind`='http'|'topic';
    set cross_repo_only=true for just the across-repo links."""
    return _query.connections(workspace, kind, min_confidence, cross_repo_only)


@mcp.tool()
def binding_candidates(workspace: str = "default", kind: str | None = None, limit: int = 25) -> dict:
    """LLM-assist worklist: routes/topics that literal pattern-matching left UNconnected
    (`unbound_servers` / `unbound_clients`). For each, find the dynamic other side with
    search/get_chunk, confirm it in the code, then record it via assert_binding."""
    return _query.binding_candidates(workspace, kind, limit)


@mcp.tool()
def assert_binding(workspace: str, kind: str, key: str,
                   client_path: str, client_line: int,
                   server_path: str, server_line: int,
                   confidence: float = 0.8, rationale: str = "") -> dict:
    """Record a cross-repo binding YOU (the agent) reasoned out — e.g. a dynamically
    constructed URL or produced topic in one repo that targets a route/consumer in
    another, which literal patterns missed. Persists as a durable, queryable edge
    (method='llm') so it isn't re-derived. `kind`='http'|'topic'; `key`=the route/topic."""
    return _query.assert_binding(workspace, kind, key, client_path, client_line,
                                 server_path, server_line, confidence, rationale)


@mcp.tool()
def entities(workspace: str = "default", etype: str | None = None, limit: int = 100) -> list[dict]:
    """List graph nodes, optionally by type — the 'place's or 'character's of a book, the
    'function's of a repo (see a lens's entity_types). Ranked by mention count. Use this
    instead of guessing; the graph knows what's in the corpus."""
    return _query.entities(workspace, etype, limit)


@mcp.tool()
def neighbors(name: str, workspace: str = "default", relation: str | None = None,
              etype: str | None = None, limit: int = 50) -> list[dict]:
    """Entities connected to `name`, optionally filtered by `relation` (e.g. 'co_occurs',
    'calls') and/or neighbor `etype` (e.g. 'place'). Answers 'what places does Paul go'
    (neighbors('Paul', etype='place')) or 'what calls verify_jwt'. Ranked by weight."""
    return _query.neighbors(workspace, name, relation, etype, limit)


@mcp.tool()
def get_chunk(chunk_id: int, workspace: str = "default") -> dict | None:
    """Fetch a chunk's full text + location for citation."""
    return _query.get_chunk(workspace, chunk_id)


@mcp.tool()
def chunks(workspace: str = "default", kind: str | None = None,
           limit: int = 200, offset: int = 0) -> list[dict]:
    """Paginated list of the workspace's chunks (id + locator + preview). Walk these to run the
    schema-guided extraction pass: for each batch, extract the lens's entity_types/relation_types
    and write them with add_entity/add_relation (use get_chunk for full text). `kind` filters by
    artifact kind (code/docs/pdf/spec)."""
    return _query.chunks(workspace, kind, limit, offset)


# --- knowledge artifacts (persistent HTML output) -----------------------------

@mcp.tool()
def export_graph(workspace: str = "default", cross_repo_only: bool = True) -> str:
    """Return a **mermaid** flowchart of the workspace's structural connections
    (artifacts grouped by repo, bindings as labeled edges) — engine-drawn, always
    faithful to the bindings. Embed it in a knowledge artifact inside a ```mermaid
    code fence. Set cross_repo_only=false to include intra-repo wiring too."""
    from . import artifact
    return artifact.mermaid_bindings(workspace, cross_repo_only)


@mcp.tool()
def render_artifact(workspace: str, title: str, markdown: str, subtitle: str = "") -> dict:
    """Render an investigation into a standalone, good-looking **HTML** knowledge
    artifact (ADR-028) and write it to disk; returns its file path. `markdown` is
    YOUR composed write-up — narrative, citation tables, and ```mermaid diagrams
    (use export_graph for the connections diagram). The file is self-contained
    (mermaid.js via CDN); open it in a browser or print to PDF."""
    from . import artifact
    path = artifact.write_artifact(workspace, title, markdown, subtitle)
    return {"path": path, "open_with": f"open {path}"}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
