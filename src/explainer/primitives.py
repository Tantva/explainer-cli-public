"""Extraction primitive registry (ADR-036).

A lens declares a composition of **primitives** in its `extractors` field; the ingest
driver runs exactly those — there are **no name-based `if lens == …` branches** in the
driver. Each primitive is a small, reusable extraction brick that writes into the generic
property-graph store and returns a counts dict.

An `extractors` entry is either a primitive name (`"defined-term-pattern"`) or a dict that
carries config (`{"use": "structural-markers", "etype": "scene", "preset": "slugline"}`).

Three families (ADR-036 §B2): deterministic surfacers/relation-builders (run inline),
fusion / entity-resolution, and LLM primitives (skill-orchestrated — the engine never calls
a model itself in v1). A declared-but-unimplemented primitive surfaces as `pending_extractors`,
never a silent no-op.
"""
from __future__ import annotations

import json
import re
from typing import Callable

# name -> fn(conn, workspace, root, config) -> dict(counts)
_REGISTRY: dict[str, Callable] = {}

# Bricks named in ADR-036 not yet implemented (later P-phases). Declared so a lens can
# compose them now; surfaced as pending until live.
# Deterministic bricks named in ADR-036 not yet implemented (engine code, later).
PLANNED: set[str] = {"sequence"}

# The LLM extraction phase is the GENERAL, universal mechanism (ADR-036 §B2, the correction):
# schema-guided extraction that works on ANY induced lens / ANY artifact. In v1 the engine has
# no model — these are orchestrated by the INGEST SKILL (subagent fan-out over chunks() →
# add_entity/add_relation per the lens schema), not run here. A lens may declare them; the
# driver records them as skill-orchestrated (not "pending"/broken).
SKILL_ORCHESTRATED: set[str] = {"llm-type", "llm-relations", "llm-extract"}


def primitive(name: str):
    def deco(fn: Callable) -> Callable:
        _REGISTRY[name] = fn
        return fn
    return deco


def get(name: str) -> Callable | None:
    return _REGISTRY.get(name)


def registered() -> list[str]:
    return sorted(_REGISTRY)


# --------------------------------------------------------------------- shared store helpers

def _text_chunks(conn, workspace, kinds=("docs", "pdf", "spec")):
    """Primary text chunks in the workspace (the substrate surfacers scan)."""
    marks = ",".join("?" * len(kinds))
    return conn.execute(
        f"SELECT c.id, c.name, c.text, c.artifact_id FROM chunks c "
        f"JOIN artifacts a ON a.id = c.artifact_id "
        f"WHERE c.workspace=? AND a.kind IN ({marks})",
        (workspace, *kinds),
    ).fetchall()


def _clear_origin(conn, workspace, origin):
    """Idempotent rebuild: drop this primitive's prior output (by origin), incl. mentions/edges,
    so re-ingest doesn't duplicate. Never touches origin='extracted' (write-door) entities."""
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM entities WHERE workspace=? AND json_extract(props,'$.origin')=?",
        (workspace, origin)).fetchall()]
    if ids:
        marks = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM mentions WHERE entity_id IN ({marks})", ids)
        conn.execute(f"DELETE FROM edges WHERE src_id IN ({marks}) OR dst_id IN ({marks})", [*ids, *ids])
        conn.execute(f"DELETE FROM entities WHERE id IN ({marks})", ids)


def _upsert_entity(conn, workspace, name, etype, props):
    conn.execute(
        "INSERT INTO entities(workspace, name, etype, props) VALUES (?,?,?,?) "
        "ON CONFLICT(workspace, name, etype) DO UPDATE SET props=excluded.props",
        (workspace, name, etype, json.dumps(props)))
    return conn.execute("SELECT id FROM entities WHERE workspace=? AND name=? AND etype=?",
                        (workspace, name, etype)).fetchone()["id"]


def _mention(conn, workspace, eid, chunk_id, surface):
    conn.execute("INSERT INTO mentions(workspace, entity_id, chunk_id, surface) VALUES (?,?,?,?)",
                 (workspace, eid, chunk_id, surface))


# --------------------------------------------------------------------- deterministic primitives

@primitive("recurring-proper-nouns")
def _recurring_proper_nouns(conn, workspace, root, config=None) -> dict:
    """Surface recurring proper nouns (a name gazetteer) as provisional entities — the
    prose/narrative surfacer. `config`: {etype (default 'character'), min_count, top_k}.
    Idempotent by origin (so a re-typed entity is cleared and re-surfaced without collision)."""
    from collections import Counter, defaultdict
    from . import prose
    config = config or {}
    etype = config.get("etype", "character")
    min_count = int(config.get("min_count", 4))
    top_k = int(config.get("top_k", 60))
    origin = prose.ORIGIN

    chunks = conn.execute(
        "SELECT c.id, c.name, c.text FROM chunks c JOIN artifacts a ON a.id=c.artifact_id "
        "WHERE c.workspace=? AND a.kind IN ('pdf','docs')", (workspace,)).fetchall()
    counts: Counter = Counter()
    chunks_of: dict[str, set] = defaultdict(set)
    first_page: dict[str, int | None] = {}
    for ch in chunks:
        page = prose._page_of(ch["name"])
        for m in prose._CAND.finditer(ch["text"] or ""):
            tok = m.group(1).strip()
            if tok in prose._STOP or tok.split()[0] in prose._STOP:
                continue
            counts[tok] += 1
            chunks_of[tok].add(ch["id"])
            if tok not in first_page and page is not None:
                first_page[tok] = page

    _clear_origin(conn, workspace, origin)
    gaz = [w for w, c in counts.most_common() if c >= min_count][:top_k]
    for name in gaz:
        eid = _upsert_entity(conn, workspace, name, etype,
                             {"first_page": first_page.get(name), "count": counts[name],
                              "provisional": True, "origin": origin})
        for cid in chunks_of[name]:
            _mention(conn, workspace, eid, cid, name)
    return {"surfaced": len(gaz)}


@primitive("co-occurrence")
def _co_occurrence(conn, workspace, root, config=None) -> dict:
    """Generic co-occurrence: entities sharing a chunk (the analysis unit) → weighted `co_occurs`
    edges. Works for any surfacer's entities (characters in scenes, ingredients in recipes).
    `config`: {min_cooccur (default 2)}. Idempotent (rebuilds all co_occurs for the workspace)."""
    from collections import Counter, defaultdict
    from . import prose
    config = config or {}
    min_cooccur = int(config.get("min_cooccur", 2))

    conn.execute("DELETE FROM edges WHERE workspace=? AND edge_type='co_occurs'", (workspace,))
    rows = conn.execute(
        "SELECT m.entity_id eid, m.chunk_id cid, c.name cname FROM mentions m "
        "JOIN chunks c ON c.id=m.chunk_id WHERE m.workspace=?", (workspace,)).fetchall()
    chunk_ents: dict[int, set] = defaultdict(set)
    page_by_chunk: dict[int, int | None] = {}
    for r in rows:
        chunk_ents[r["cid"]].add(r["eid"])
        page_by_chunk[r["cid"]] = prose._page_of(r["cname"])

    pair: Counter = Counter()
    pair_page: dict[tuple, int | None] = {}
    for cid, ents in chunk_ents.items():
        es = sorted(ents)
        for i in range(len(es)):
            for j in range(i + 1, len(es)):
                k = (es[i], es[j])
                pair[k] += 1
                pair_page.setdefault(k, page_by_chunk.get(cid))

    created = 0
    for (a, b), n in pair.items():
        if n < min_cooccur:
            continue
        conf = min(1.0, 0.4 + 0.1 * n)
        conn.execute(
            "INSERT INTO edges(workspace, src_id, dst_id, edge_type, confidence, method, props) "
            "VALUES (?,?,?, 'co_occurs', ?, 'co-occurrence', ?)",
            (workspace, a, b, conf, json.dumps({"shared": n, "first_page": pair_page[(a, b)]})))
        created += 1
    return {"co_occurs": created}


@primitive("doc-cross-source")
def _doc_cross_source(conn, workspace, root, config=None) -> dict:
    """The wedge: resolve doc/pdf mentions to code symbols (exact + fuzzy) → cross-source
    `doc_describes_code` edges."""
    from .synthesis import resolve_workspace
    return {"cross_source_edges": resolve_workspace(conn, workspace)}


@primitive("structural-binding")
def _structural_binding(conn, workspace, root, config=None) -> dict:
    """Bind client↔server connectors (HTTP routes / queue topics) across artifacts →
    `binding` edges (preserves agent-asserted `llm` bindings)."""
    from .structural import resolve_structural
    return {"structural_bindings": resolve_structural(conn, workspace)}


@primitive("ast-callgraph")
def _ast_callgraph(conn, workspace, root, config=None) -> dict:
    """Tree-sitter call graph: `calls` edges between code symbols, re-derived from the
    workspace's code artifacts (idempotent, workspace-wide). Replaces the inline call-graph
    that used to live in the code chunker (ADR-036 — code is just a lens)."""
    from pathlib import Path
    from .ingestors import iter_calls

    conn.execute("DELETE FROM edges WHERE workspace=? AND edge_type='calls' AND method='structural'",
                 (workspace,))
    arts = conn.execute(
        "SELECT id, path, lang FROM artifacts WHERE workspace=? AND kind='code'", (workspace,)
    ).fetchall()
    created = 0
    for a in arts:
        try:
            src = Path(a["path"]).read_text("utf-8", "ignore")
        except OSError:
            continue
        for enc_name, callee in iter_calls(src, a["lang"] or ""):
            enc = conn.execute(
                "SELECT id FROM entities WHERE workspace=? AND name=? AND etype='symbol'",
                (workspace, enc_name)).fetchone()
            if not enc:
                continue
            conn.execute("INSERT OR IGNORE INTO entities(workspace, name, etype) VALUES (?,?, 'symbol')",
                         (workspace, callee))
            callee_eid = conn.execute(
                "SELECT id FROM entities WHERE workspace=? AND name=? AND etype='symbol'",
                (workspace, callee)).fetchone()["id"]
            cc = conn.execute(
                "SELECT id FROM chunks WHERE workspace=? AND artifact_id=? AND name=? ORDER BY id LIMIT 1",
                (workspace, a["id"], enc_name)).fetchone()
            if cc:
                _mention(conn, workspace, callee_eid, cc["id"], callee)
            conn.execute(
                "INSERT INTO edges(workspace, src_id, dst_id, edge_type, cross_source, confidence, method) "
                "VALUES (?,?,?, 'calls', 0, 1.0, 'structural')",
                (workspace, enc["id"], callee_eid))
            created += 1
    return {"calls": created}


# defined-term surfacing: explicit definition forms common to legal/contract + textbook/glossary.
_DEFINED_TERM_RES = [
    re.compile(r'^[ \t]*[“"‘\']([A-Z][A-Za-z0-9 ,\-/&()]{1,70}?)[”"’\']\s*:', re.MULTILINE),  # "Term": …  (colon definitional-list form — the dominant real-contract style)
    re.compile(r'[“"‘\']([A-Z][A-Za-z0-9 ,\-/&]{1,70}?)[”"’\']\s+(?:means|shall mean|shall have the meaning)\b'),
    re.compile(r'\(\s*(?:the|each(?: a)?|a|an|collectively,?|individually,?|together,?)?\s*'
               r'[“"‘\']([A-Z][A-Za-z0-9 ,\-/&]{1,70}?)[”"’\']\s*\)'),   # (the "Borrower"), ("Lenders") — inline
    re.compile(r'\b([A-Z][A-Za-z0-9 ,\-/&]{1,70}?)\s+is defined as\b'),
    re.compile(r'\b([A-Z][A-Za-z0-9 ,\-/&]{1,70}?)\s+means\s+[A-Za-z]'),                 # Term means …
]


@primitive("defined-term-pattern")
def _defined_term_pattern(conn, workspace, root, config=None) -> dict:
    """Surface explicitly *defined* terms (legal `"X" means …`, textbook/glossary definitions)
    as typed entities. The non-proper-noun things a name gazetteer can't find. Idempotent."""
    config = config or {}
    etype = config.get("etype", "defined_term")
    origin = "defined-term-pattern"
    _clear_origin(conn, workspace, origin)
    seen: dict[str, int] = {}
    for ch in _text_chunks(conn, workspace):
        text = ch["text"] or ""
        for rx in _DEFINED_TERM_RES:
            for m in rx.finditer(text):
                term = re.sub(r"\s+", " ", m.group(1)).strip(" ,")
                if len(term) < 2:
                    continue
                if term not in seen:
                    snippet = text[m.start(): m.start() + 160].replace("\n", " ")
                    seen[term] = _upsert_entity(conn, workspace, term, etype,
                                                {"origin": origin, "provisional": True, "definition": snippet})
                _mention(conn, workspace, seen[term], ch["id"], term)
    return {"defined_terms": len(seen)}


# structural-marker surfacing: headings / numbered sections / sluglines / chapters.
# Presets keyed by a hint; default scans the common union. Each emits a structural entity
# (a `section`/`scene` node) so structure becomes queryable and cross-references can link it.
_MARKER_PRESETS = {
    "section": [re.compile(r'(?m)^\s*((?:SECTION|Section)\s+\d+[A-Za-z0-9.]*)'),
                re.compile(r'(?m)^\s*((?:ARTICLE|Article)\s+[IVXLC0-9]+)')],
    "heading": [re.compile(r'(?m)^#{1,6}\s+(.+?)\s*$')],
    "slugline": [re.compile(r'(?m)^\s*((?:INT\.|EXT\.|INT/EXT\.?)[^\n]{0,70})')],
    "chapter": [re.compile(r'(?m)^\s*((?:CHAPTER|Chapter)\s+[A-Za-z0-9]+)')],
}


@primitive("structural-markers")
def _structural_markers(conn, workspace, root, config=None) -> dict:
    """Surface structural divisions (contract sections, screenplay scenes, chapters, headings)
    as typed entities + chunk locators — the nodes `cross-reference` (P2) links and the
    analysis unit co-occurrence uses. `config`: {etype, preset}; default scans the common union."""
    config = config or {}
    preset = config.get("preset")
    etype = config.get("etype", "section")
    rxs = _MARKER_PRESETS.get(preset, [r for group in _MARKER_PRESETS.values() for r in group])
    origin = f"structural-markers:{etype}"   # etype-scoped so a section run and a scene run don't clear each other
    _clear_origin(conn, workspace, origin)
    seen: dict[str, int] = {}
    for ch in _text_chunks(conn, workspace):
        text = ch["text"] or ""
        for rx in rxs:
            for m in rx.finditer(text):
                label = re.sub(r"\s+", " ", m.group(1)).strip()
                if not label or len(label) > 90:
                    continue
                line = text.count("\n", 0, m.start()) + 1
                if label not in seen:
                    seen[label] = _upsert_entity(conn, workspace, label, etype,
                                                 {"origin": origin, "label": label})
                _mention(conn, workspace, seen[label], ch["id"], label)
                # record first-seen locator
                conn.execute(
                    "UPDATE entities SET props=json_set(props,'$.line', ?) "
                    "WHERE id=? AND json_extract(props,'$.line') IS NULL",
                    (line, seen[label]))
    return {"structural_markers": len(seen)}


# salient-term surfacing: frequent multi-word noun phrases REGARDLESS OF CASE — the
# lowercase domain terms a proper-noun gazetteer can't see (recipe ingredients, textbook
# concepts). RAKE-style: candidate phrases are runs of non-stopword tokens; rank by frequency.
_STOPWORDS = set(
    "a an the and or but if then else of to in on at by for with from into over under as is are "
    "was were be been being this that these those it its he she they we you i his her their our your "
    "my not no nor so than too very can will would should could may might must do does did have has "
    "had which who whom whose what when where why how all any both each few more most other some such "
    "only own same s t just don now also per via use used using add".split()
)


def _phrases(text: str, max_n: int = 3) -> list[str]:
    """Candidate terms = all 1..max_n-grams within each run of non-stopword tokens. Emitting
    sub-grams (not just whole runs) means a frequent phrase isn't hidden inside longer runs —
    e.g. 'garam masala' surfaces even when it appears as 'garam masala generously'. Noisy by
    design; the typing pass refines."""
    runs: list[list[str]] = []
    cur: list[str] = []
    for tok in re.findall(r"[A-Za-z][A-Za-z'\-]*|[^A-Za-z\s]", text):
        if tok.isalpha() and len(tok) > 2 and tok.lower() not in _STOPWORDS:
            cur.append(tok)
        else:
            if cur:
                runs.append(cur); cur = []
    if cur:
        runs.append(cur)
    out: list[str] = []
    for run in runs:
        for n in range(1, max_n + 1):
            for i in range(len(run) - n + 1):
                out.append(" ".join(run[i:i + n]))
    return out


@primitive("salient-terms")
def _salient_terms(conn, workspace, root, config=None) -> dict:
    """Surface frequent multi-word/lowercase noun phrases as candidate entities — the domain
    terms (ingredients, concepts) a proper-noun gazetteer misses. Provisional; the typing pass
    refines. Idempotent. `config`: {etype, min_count, top_k}."""
    from collections import Counter, defaultdict
    config = config or {}
    etype = config.get("etype", "term")
    min_count = int(config.get("min_count", 4))
    top_k = int(config.get("top_k", 80))
    origin = "salient-terms"
    _clear_origin(conn, workspace, origin)

    counts: Counter = Counter()
    chunks_of: dict[str, set] = defaultdict(set)
    surface_of: dict[str, str] = {}
    for ch in _text_chunks(conn, workspace):
        for ph in _phrases(ch["text"] or ""):
            key = ph.lower()
            counts[key] += 1
            chunks_of[key].add(ch["id"])
            surface_of.setdefault(key, ph)

    keep = [k for k, c in counts.most_common() if c >= min_count][:top_k]
    for key in keep:
        name = surface_of[key]
        eid = _upsert_entity(conn, workspace, name, etype,
                             {"origin": origin, "provisional": True, "count": counts[key]})
        for cid in chunks_of[key]:
            _mention(conn, workspace, eid, cid, name)
    return {"salient_terms": len(keep)}


# cross-reference: explicit pointers between structural divisions ("Section 9.1", "Article IV",
# "see Chapter 3") → typed edges between the section entities `structural-markers` created.
# Keyed on the section number so a reference matches the right node. Powers blast-radius queries.
# anchored on the division keyword so we capture the *number*, not the "I" inside "SECTION".
_XREF = re.compile(r'(?:Section|Article|Clause|Chapter|§)\s*([0-9]+(?:\.[0-9]+)*|[IVXLC]+)\b', re.I)


@primitive("cross-reference")
def _cross_reference(conn, workspace, root, config=None) -> dict:
    """Link structural divisions by their explicit cross-references. Source = the section entity
    whose label matches a chunk's heading; target = the referenced section number. `config`:
    {etype, relation}. Idempotent (clears its own method-tagged edges)."""
    config = config or {}
    etype = config.get("etype", "section")
    relation = config.get("relation", "references")
    conn.execute("DELETE FROM edges WHERE workspace=? AND edge_type=? AND method='cross-reference'",
                 (workspace, relation))
    secs = conn.execute("SELECT id, name FROM entities WHERE workspace=? AND etype=?",
                        (workspace, etype)).fetchall()
    by_num: dict[str, int] = {}
    by_name: list[tuple[str, int]] = []
    for s in secs:
        m = _XREF.search(s["name"])
        if m:
            by_num.setdefault(m.group(1), s["id"])
        by_name.append((s["name"], s["id"]))

    created = 0
    seen: set = set()
    for ch in _text_chunks(conn, workspace):
        cname = ch["name"] or ""
        src_id = None
        for nm, sid in by_name:
            if cname and (cname == nm or cname.startswith(nm) or nm.startswith(cname)):
                src_id = sid
                break
        if src_id is None:
            continue
        for m in _XREF.finditer(ch["text"] or ""):
            dst = by_num.get(m.group(1))
            if dst and dst != src_id and (src_id, dst) not in seen:
                seen.add((src_id, dst))
                conn.execute(
                    "INSERT INTO edges(workspace, src_id, dst_id, edge_type, cross_source, confidence, method) "
                    "VALUES (?,?,?,?,0,0.7,'cross-reference')",
                    (workspace, src_id, dst, relation))
                created += 1
    return {"cross_references": created}


# entity resolution / canonicalization (ADR-036 §B3, the knowledge-fusion stage): collapse
# surface forms + aliases of the same entity into one node. Deterministic normalized-name
# clustering always runs (handles articles + case: "the Borrower" == "Borrower"); an optional
# embedding pass (Model2Vec, guarded) catches near-dups string-normalization can't.
_ARTICLE = re.compile(r'^(?:the|a|an)\s+', re.I)


def _norm_name(s: str) -> str:
    s = _ARTICLE.sub("", (s or "").strip())
    s = re.sub(r"[^\w\s]", "", s).lower()
    return re.sub(r"\s+", " ", s).strip()


def _mention_count(conn, eid: int) -> int:
    return conn.execute("SELECT COUNT(*) n FROM mentions WHERE entity_id=?", (eid,)).fetchone()["n"]


def _merge_bucket(conn, workspace, members) -> int:
    """Pick canonical (most mentions, tiebreak longest name) and fuse the rest into it."""
    from . import store
    ordered = sorted(members, key=lambda e: (_mention_count(conn, e["id"]), len(e["name"] or "")), reverse=True)
    keep, drops = ordered[0]["id"], [m["id"] for m in ordered[1:]]
    return store.merge_entities(conn, workspace, keep, drops)


@primitive("alias-merge")
def _alias_merge(conn, workspace, root, config=None) -> dict:
    """Resolve duplicate entities into canonical nodes — the stage that stops "Sunja" /
    "Madam Baek" / "the Borrower" / "Borrower" inflating counts. Resolves WITHIN each entity
    type. `config`: {etype (limit to one type), embeddings (bool, default True), threshold}."""
    from collections import defaultdict
    config = config or {}
    only_etype = config.get("etype")
    use_embed = config.get("embeddings", True)
    threshold = float(config.get("threshold", 0.9))

    q = "SELECT id, name, etype FROM entities WHERE workspace=?"
    args: list = [workspace]
    if only_etype:
        q += " AND etype=?"
        args.append(only_etype)
    rows = conn.execute(q, args).fetchall()
    by_type: dict[str, list] = defaultdict(list)
    for r in rows:
        by_type[r["etype"]].append(r)

    merged = 0
    for etype, ents in by_type.items():
        # 1) deterministic: bucket by normalized name (case, punctuation, leading article)
        buckets: dict[str, list] = defaultdict(list)
        for e in ents:
            buckets[_norm_name(e["name"])].append(e)
        survivors = []
        for key, members in buckets.items():
            if len(members) > 1:
                merged += _merge_bucket(conn, workspace, members)
            survivors.append(members[0])   # one representative per normalized key remains
        # 2) optional embedding pass: cluster the survivors by cosine similarity of their names
        if use_embed and len(survivors) > 1:
            merged += _embed_merge(conn, workspace, survivors, threshold)
    return {"merged_entities": merged}


def _embed_merge(conn, workspace, ents, threshold) -> int:
    """Best-effort embedding canonicalization (Model2Vec). No-ops if the model/numpy aren't
    available — the deterministic pass already ran, so this only augments."""
    try:
        import numpy as np
        from model2vec import StaticModel
        from .retriever import _model_path
        model = StaticModel.from_pretrained(_model_path())
        vecs = np.asarray(model.encode([e["name"] for e in ents]), dtype="float32")
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        vecs = vecs / np.clip(norms, 1e-9, None)
    except Exception:
        return 0
    n = len(ents)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    sims = vecs @ vecs.T
    for i in range(n):
        for j in range(i + 1, n):
            if sims[i, j] >= threshold:
                parent[find(i)] = find(j)
    clusters: dict[int, list] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(ents[i])
    merged = 0
    for members in clusters.values():
        if len(members) > 1:
            merged += _merge_bucket(conn, workspace, members)
    return merged


# --------------------------------------------------------------------- driver

def _parse_item(item):
    if isinstance(item, str):
        return item, {}
    name = item.get("use") or item.get("name")
    return name, {k: v for k, v in item.items() if k not in ("use", "name")}


def run_extractors(conn, workspace: str, root: str, extractors: list) -> dict:
    """Run the lens's declared primitive composition, in order, merging their counts. The
    single dispatch point — the driver never branches on lens name. Declared-but-unimplemented
    primitives are recorded under `pending_extractors` (visible, not silent)."""
    counts: dict = {}
    pending: list[str] = []
    skill: list[str] = []
    for item in extractors:
        name, config = _parse_item(item)
        fn = get(name)
        if fn is not None:
            counts.update(fn(conn, workspace, root, config) or {})
        elif name in SKILL_ORCHESTRATED:
            skill.append(name)          # the ingest skill fulfills these (LLM extraction phase)
        else:
            pending.append(name)        # declared but unimplemented deterministic brick
    if skill:
        counts["skill_extractors"] = skill
    if pending:
        counts["pending_extractors"] = pending
    return counts
