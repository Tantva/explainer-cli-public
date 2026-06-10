"""Lenses: named, reusable indexing strategies (ADR-035, ADR-036).

A **lens** is the type-specific contract for turning an artifact into graph: which
entity types and relations matter, which properties to capture, and — per ADR-036 —
which **upper-spine category** each type specializes (`parents`), which external
vocabulary it soft-references (`aligns`), and which extraction **primitives** the
engine should run (`extractors`). Code is just the first hand-built lens; the ingest
runtime picks a registered lens for a known artifact type or **induces** one for an
unknown type and registers it.

Lenses are global (reused across workspaces) and **frozen on register** — the wedge
needs a shared, joinable schema, so an induced lens's shape can't drift per ingest.
The data all lands in the generic property-graph store; a lens only decides *what*
to put there, never *where*.

ADR-036 grounding: the lens is a TBox (entity types = concepts, relation types =
roles); the extracted graph is the ABox. Each type anchors to a tiny shared upper
spine so "all agents / all events across corpora" is a join. Soft reuse only — a
`parent`/`aligns` reference, never an ontology import.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from . import store


# --------------------------------------------------------------------- the upper spine (ADR-036)
# A tiny shared top layer (~9 categories) anchored on endurant/object vs perdurant/event
# (gUFO/BFO/DOLCE lineage). Every induced or seed type declares a `parent` among these so
# the graph stays joinable across corpora. Seed, don't import; keep it small.
SPINE: list[str] = [
    "agent",               # a thing that acts: person, organization, faction
    "object",              # a concrete endurant thing
    "place",               # a location
    "information_object",  # an abstract artifact: concept, section, definition, document
    "event",               # a perdurant happening / occurrence
    "role",                # a way of participating (borrower, narrator)
    "quality",             # a measurable/attributable feature (a threshold, a trait)
    "time",                # a temporal entity
    "relationship",        # a reified n-ary relation
]

# Soft-reference vocabularies a lens MAY point a type at via `aligns` (term-level reuse,
# never an import). Documented here so induced lenses reuse a known term instead of
# inventing one. See ADR-036 §A3.
SOFT_VOCABS: dict[str, str] = {
    "schema": "https://schema.org/",          # Person, Place, Organization, CreativeWork, Event
    "skos": "http://www.w3.org/2004/02/skos/core#",  # broader/narrower/related (taxonomies)
    "dct": "http://purl.org/dc/terms/",       # Dublin Core document metadata
    "crm": "http://www.cidoc-crm.org/cidoc-crm/",    # event-centric (narrative/historical)
    "prov": "http://www.w3.org/ns/prov#",     # provenance (binds to the claim model)
    "time": "http://www.w3.org/2006/time#",   # temporal entities
}


@dataclass
class Lens:
    name: str
    description: str
    discriminators: str                      # how the ingest runtime recognizes this artifact type
    entity_types: list[str] = field(default_factory=list)
    relation_types: list[str] = field(default_factory=list)
    properties: dict[str, list[str]] = field(default_factory=dict)  # entity_type -> [field, ...]
    signals: list[str] = field(default_factory=list)
    method: str = ""
    # ADR-036: anchor each type to the shared upper spine, optionally soft-reference an
    # external vocabulary term, and declare the primitive composition the engine runs.
    parents: dict[str, str] = field(default_factory=dict)    # entity_type -> SPINE category
    aligns: dict[str, str] = field(default_factory=dict)     # entity_type -> "vocab:Term" (soft ref)
    extractors: list[str] = field(default_factory=list)      # primitive names (see primitives.py)
    # How to SYNTHESIZE documentation for this artifact type (ADR-028): which docs to
    # generate, how to decompose, what to ground on. The wiki skill reads this.
    synthesis: dict = field(default_factory=dict)
    kind: str = "coded"                      # coded | induced
    version: int = 1

    def schema(self) -> dict:
        d = asdict(self)
        d.pop("name"); d.pop("description"); d.pop("kind"); d.pop("version")
        return d


# --------------------------------------------------------------------- seed lenses

SEED_LENSES: list[Lens] = [
    Lens(
        name="code",
        description="Source repositories — functions, classes, call graphs, and the routes/topics that wire services together.",
        discriminators="A directory of source files (.py/.rs/.ts/.go/.java/...), or a single code file; an API spec (OpenAPI) counts as code-adjacent.",
        entity_types=["function", "class", "struct", "method", "interface", "endpoint", "symbol"],
        relation_types=["calls", "imports", "binding", "connector", "doc_describes_code"],
        properties={"function": ["lang"], "endpoint": ["methods"]},
        signals=["call-graph", "route/topic-binding", "doc<->code synthesis", "semantic"],
        method="tree-sitter AST (deterministic) + connector regex + LLM-assist binding for dynamic wiring",
        # ADR-036 anchoring + composition. (The call graph is emitted at chunk time by the
        # code chunker today; migrating it to an `ast-callgraph` primitive is a P0.2 follow-up.)
        parents={"function": "information_object", "class": "information_object",
                 "struct": "information_object", "method": "information_object",
                 "interface": "information_object", "endpoint": "information_object",
                 "symbol": "information_object"},
        aligns={"endpoint": "schema:EntryPoint"},
        extractors=["ast-callgraph", "structural-binding", "doc-cross-source"],
        # No baked synthesis plan (ADR-036 correction): the wiki/synthesis plan is induced
        # per corpus from intent, or supplied as an exemplar in the induction prompt — not an
        # engine constant. Seed lenses ship thin.
    ),
    Lens(
        name="prose",
        description="Books and long-form prose — characters, places, concepts, and themes, and who/what appears together.",
        discriminators="A PDF or text document of narrative or expository prose (a novel, a textbook chapter) — not code, not structured/tabular data.",
        entity_types=["character", "place", "concept", "theme"],
        relation_types=["co_occurs", "mentions"],
        properties={"character": ["first_page", "count", "aliases"], "concept": ["first_page", "count"]},
        signals=["co-occurrence graph", "semantic"],
        method="gazetteer discovery (recurring proper-noun / key-term frequency; session-refinable) + deterministic mention tagging + co-occurrence edges",
        parents={"character": "agent", "place": "place", "concept": "information_object",
                 "theme": "information_object"},
        aligns={"character": "schema:Person", "place": "schema:Place", "concept": "skos:Concept"},
        extractors=[{"use": "recurring-proper-nouns", "etype": "character"}, "co-occurrence",
                    "doc-cross-source", "structural-binding"],
        # No baked synthesis plan — see the code lens note above (ADR-036).
    ),
]


# --------------------------------------------------------------------- registry

def _ensure_seeded(conn) -> None:
    for lens in SEED_LENSES:
        conn.execute(
            "INSERT OR IGNORE INTO lenses(name, description, schema, kind, version, frozen) "
            "VALUES (?,?,?,?,?,1)",
            (lens.name, lens.description, json.dumps(lens.schema()), lens.kind, lens.version),
        )
    conn.commit()


def ensure_seeded(conn) -> None:
    """Public: seed the coded lenses into an existing connection (idempotent). The ingest
    driver calls this before reading a lens's `extractors` on its own connection."""
    _ensure_seeded(conn)


def extractors_for(conn, name: str) -> list[str] | None:
    """The primitive composition a lens declares (ADR-036), read on an existing connection.
    Returns None if the lens is unknown or declares no extractors (caller falls back to the
    default composition)."""
    r = conn.execute("SELECT schema FROM lenses WHERE name=?", (name,)).fetchone()
    if not r:
        return None
    return json.loads(r["schema"]).get("extractors") or None


def _row_to_dict(r) -> dict:
    d = {"name": r["name"], "description": r["description"], "kind": r["kind"],
         "version": r["version"], "frozen": bool(r["frozen"])}
    d.update(json.loads(r["schema"]))
    return d


def list_lenses(db=store.DEFAULT_DB) -> list[dict]:
    """All registered lenses (seed + induced), with their discriminators — the ingest
    runtime reads this to choose which lens an artifact matches."""
    conn = store.connect(db)
    _ensure_seeded(conn)
    rows = conn.execute(
        "SELECT name, description, schema, kind, version, frozen FROM lenses ORDER BY kind, name"
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def get_lens(name: str, db=store.DEFAULT_DB) -> dict | None:
    conn = store.connect(db)
    _ensure_seeded(conn)
    r = conn.execute(
        "SELECT name, description, schema, kind, version, frozen FROM lenses WHERE name=?",
        (name,),
    ).fetchone()
    conn.close()
    return _row_to_dict(r) if r else None


def register_lens(name: str, description: str, schema: dict, db=store.DEFAULT_DB) -> dict:
    """Register an INDUCED lens (frozen). The ingest runtime calls this once for a new
    artifact type. Frozen means: if a lens by this name already exists it is NOT
    overwritten — reuse keeps the graph joinable. Returns the lens (existing or new)."""
    conn = store.connect(db)
    _ensure_seeded(conn)
    existing = conn.execute("SELECT frozen FROM lenses WHERE name=?", (name,)).fetchone()
    if existing:
        conn.close()
        return {"ok": False, "reason": "lens already exists and is frozen — reuse it or pick a new name",
                "lens": get_lens(name, db)}
    conn.execute(
        "INSERT INTO lenses(name, description, schema, kind, version, frozen) VALUES (?,?,?,'induced',1,1)",
        (name, description, json.dumps(schema)),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "lens": get_lens(name, db)}
