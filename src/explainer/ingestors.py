"""Pluggable ingestion: a registry of **Ingestors**, one per medium.

Each ingestor declares what files it `handles()` and how to `ingest()` them into
the store (chunks, entities, mentions, edges, and — crucially — *connectors* that
let a medium participate in the cross-repo wedge). New media slot in by writing an
Ingestor and registering it; nothing else changes.

Built-ins: code (tree-sitter call graph), docs (heading chunks), pdf (page text →
disk for semble), openapi (spec routes → server connectors). The driver in
``ingest.py`` walks files and dispatches to the first ingestor that handles each.

Design notes:
- ``IngestContext`` owns the store handles + shared write helpers, so ingestors
  stay small and never touch SQL directly.
- ``add_connector`` is the extension point that makes a *non-code* medium feed the
  structural binder (e.g. an OpenAPI spec asserts the routes it serves).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from . import connectors as _connectors
from . import store

CODE_EXT = {
    ".py": "python", ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".rs": "rust",
    ".go": "go", ".java": "java", ".rb": "ruby",
}
DOC_EXT = {".md", ".markdown", ".rst", ".txt"}
PDF_EXT = {".pdf"}
SPEC_EXT = {".json", ".yaml", ".yml"}
IGNORE_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__"}

# Where PDF (and future binary) text is extracted to disk so semble can index it.
DERIVED_ROOT = Path.home() / ".explainer" / "derived"

# Per-language tree-sitter spec: which node types are definitions (→ chunks +
# symbol entities), what they map to, and which node type is a call (→ callgraph
# edges). Add a language by adding a row here — node names come from its grammar.
# Languages NOT listed fall back to naive regex chunking.
_LANG_SPEC: dict[str, dict] = {
    "python": {
        "defs": {"function_definition": "function", "class_definition": "class"},
        "call": "call",
    },
    "rust": {
        "defs": {"function_item": "function", "struct_item": "struct",
                 "enum_item": "enum", "trait_item": "trait"},
        "call": "call_expression",
    },
    "javascript": {
        "defs": {"function_declaration": "function", "method_definition": "method",
                 "class_declaration": "class"},
        "call": "call_expression",
    },
    "typescript": {
        "defs": {"function_declaration": "function", "method_definition": "method",
                 "class_declaration": "class", "interface_declaration": "interface"},
        "call": "call_expression",
    },
}
_TS_LANGS = set(_LANG_SPEC)
_DEF_RE = re.compile(r"^\s*(?:def|class|func|function|fn)\s+([A-Za-z_]\w+)", re.M)


# ----------------------------------------------------------------------------- context

@dataclass
class IngestContext:
    """Store handles + write helpers shared by all ingestors."""
    conn: object
    workspace: str

    @staticmethod
    def sha(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()[:16]

    def add_artifact(self, path: Path, kind: str, lang: str | None, sha: str) -> int:
        # UPSERT keeps the artifact id STABLE across re-ingest (so bindings referencing
        # it survive); then clear its old chunks/mentions/connectors so re-ingest is
        # idempotent.
        conn, ws = self.conn, self.workspace
        conn.execute(
            "INSERT INTO artifacts(workspace, path, kind, lang, sha) VALUES (?,?,?,?,?) "
            "ON CONFLICT(workspace, path) DO UPDATE SET kind=excluded.kind, lang=excluded.lang, "
            "sha=excluded.sha, ingested_at=datetime('now')",
            (ws, str(path), kind, lang, sha),
        )
        aid = conn.execute(
            "SELECT id FROM artifacts WHERE workspace=? AND path=?", (ws, str(path))
        ).fetchone()["id"]
        old = [r["id"] for r in conn.execute("SELECT id FROM chunks WHERE artifact_id=?", (aid,)).fetchall()]
        if old:
            marks = ",".join("?" * len(old))
            conn.execute(f"DELETE FROM mentions WHERE chunk_id IN ({marks})", old)
            conn.execute("DELETE FROM chunks WHERE artifact_id=?", (aid,))
        store.clear_connectors(conn, aid)
        return aid

    def add_chunk(self, aid, kind, name, start, end, text) -> int:
        cur = self.conn.execute(
            "INSERT INTO chunks(workspace, artifact_id, kind, name, start_line, end_line, text) "
            "VALUES (?,?,?,?,?,?,?)",
            (self.workspace, aid, kind, name, start, end, text),
        )
        return cur.lastrowid

    def ensure_entity(self, name, etype) -> int:
        conn, ws = self.conn, self.workspace
        conn.execute("INSERT OR IGNORE INTO entities(workspace, name, etype) VALUES (?,?,?)",
                     (ws, name, etype))
        return conn.execute("SELECT id FROM entities WHERE workspace=? AND name=? AND etype=?",
                            (ws, name, etype)).fetchone()["id"]

    def add_mention(self, eid, cid, surface) -> None:
        self.conn.execute(
            "INSERT INTO mentions(workspace, entity_id, chunk_id, surface) VALUES (?,?,?,?)",
            (self.workspace, eid, cid, surface),
        )

    def add_edge(self, src, dst, etype, cross, conf, method, prov=None) -> None:
        self.conn.execute(
            "INSERT INTO edges(workspace, src_id, dst_id, edge_type, cross_source, confidence, method, provenance) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (self.workspace, src, dst, etype, cross, conf, method, prov),
        )

    def add_connector(self, aid, kind, role, key_norm, key_raw=None, line=None) -> None:
        store.add_connector(self.conn, self.workspace, aid, kind, role, key_norm, key_raw, line)

    def doc_chunk(self, aid, name, body) -> None:
        cid = self.add_chunk(aid, "section", name, None, None, body)
        self.extract_doc_mentions(cid, body)

    def extract_doc_mentions(self, chunk_id, body) -> None:
        """Capture candidate entity surfaces from prose: inline code-spans are strong
        signals of a symbol/service the doc is talking about."""
        seen = set()
        for span in re.findall(r"`([^`]+)`", body):
            tok = span.strip().split("(")[0].split(".")[-1]
            if re.fullmatch(r"[A-Za-z_]\w{2,}", tok) and tok not in seen:
                seen.add(tok)
                eid = self.ensure_entity(tok, "mention")
                self.add_mention(eid, chunk_id, span)


# ----------------------------------------------------------------------------- protocol

@runtime_checkable
class Ingestor(Protocol):
    name: str
    def handles(self, path: Path) -> bool: ...
    def ingest(self, ctx: IngestContext, path: Path) -> None: ...


# ----------------------------------------------------------------------------- helpers (code)

def _txt(node) -> str:
    return node.text.decode("utf-8", "ignore")


def _callee_name(fn) -> str | None:
    """The called symbol from a call's `function` node, across grammars:
    plain identifier; attribute (py) / member_expression (js,ts) / field_expression
    (rust) → the trailing name; scoped_identifier (rust ``a::b::c``) → last segment."""
    if fn is None:
        return None
    if fn.type in ("identifier", "field_identifier", "property_identifier"):
        return _txt(fn)
    for field in ("attribute", "property", "field", "name"):
        c = fn.child_by_field_name(field)
        if c is not None:
            return _txt(c)
    ids = [ch for ch in fn.children if ch.type in ("identifier", "field_identifier")]
    return _txt(ids[-1]) if ids else None


def _walk_nodes(node):
    yield node
    for child in node.children:
        yield from _walk_nodes(child)


def _enclosing_name(defs: list, byte: int):
    """Name of the smallest def span containing `byte` (defs = [(name, start, end)])."""
    best = None
    best_span = None
    for name, sb, eb in defs:
        if sb <= byte <= eb:
            span = eb - sb
            if best_span is None or span < best_span:
                best, best_span = name, span
    return best


def iter_calls(src: str, lang: str) -> list[tuple[str, str]]:
    """(enclosing_def_name, callee_name) pairs from code text via tree-sitter — pure, no
    store writes. Empty for languages without a tree-sitter spec (their symbols are still
    chunked; they just have no call graph). Used by the `ast-callgraph` primitive (ADR-036)."""
    if lang not in _TS_LANGS:
        return []
    from tree_sitter import Parser
    from tree_sitter_language_pack import get_language

    language = get_language(lang)
    try:
        parser = Parser(language)
    except TypeError:  # older binding
        parser = Parser()
        parser.language = language
    tree = parser.parse(bytes(src, "utf-8"))
    nodes = list(_walk_nodes(tree.root_node))
    spec = _LANG_SPEC[lang]
    def_types, call_type = spec["defs"], spec["call"]

    defs: list[tuple] = []
    for node in nodes:
        if node.type in def_types:
            nn = node.child_by_field_name("name")
            if nn is not None:
                defs.append((_txt(nn), node.start_byte, node.end_byte))

    out: list[tuple[str, str]] = []
    for node in nodes:
        if node.type != call_type:
            continue
        callee = _callee_name(node.child_by_field_name("function"))
        if not callee:
            continue
        enc = _enclosing_name(defs, node.start_byte)
        if enc is None or callee == enc:
            continue
        out.append((enc, callee))
    return out


# ----------------------------------------------------------------------------- ingestors

class CodeIngestor:
    name = "code"

    def handles(self, path: Path) -> bool:
        return path.suffix.lower() in CODE_EXT

    def ingest(self, ctx: IngestContext, path: Path) -> None:
        lang = CODE_EXT[path.suffix.lower()]
        src = path.read_text("utf-8", "ignore")
        aid = ctx.add_artifact(path, "code", lang, ctx.sha(src))

        if lang not in _TS_LANGS:
            cid = ctx.add_chunk(aid, "file", path.name, 1, src.count("\n") + 1, src)
            for m in _DEF_RE.finditer(src):
                eid = ctx.ensure_entity(m.group(1), "symbol")
                ctx.add_mention(eid, cid, m.group(1))
            return

        from tree_sitter import Parser
        from tree_sitter_language_pack import get_language

        language = get_language(lang)
        try:
            parser = Parser(language)
        except TypeError:  # older binding
            parser = Parser()
            parser.language = language
        tree = parser.parse(bytes(src, "utf-8"))
        nodes = list(_walk_nodes(tree.root_node))
        spec = _LANG_SPEC[lang]
        def_types = spec["defs"]

        # Definitions → chunks + symbol entities. This is *chunking* (per-medium, fine).
        # The call graph is NOT built here — it's the `ast-callgraph` extraction primitive
        # (ADR-036), so code is no longer a privileged inline-extraction path.
        for node in nodes:
            if node.type not in def_types:
                continue
            namenode = node.child_by_field_name("name")
            if namenode is None:
                continue
            name = _txt(namenode)
            cid = ctx.add_chunk(aid, def_types[node.type], name,
                                node.start_point[0] + 1, node.end_point[0] + 1, _txt(node))
            eid = ctx.ensure_entity(name, "symbol")
            ctx.add_mention(eid, cid, name)


# A structural boundary in a text document — generalizes markdown headings to the universal
# division cues (numbered sections/articles/chapters, screenplay sluglines) so a non-markdown
# structured doc (a contract, a script) chunks by its real divisions instead of one giant blob.
_DOC_BOUNDARY = re.compile(
    r'(?m)^[ \t]*(?:'
    r'#{1,6}[ \t]+\S.*'                                              # markdown heading
    r'|(?:SECTION|Section|ARTICLE|Article|CHAPTER|Chapter)[ \t]+[\w.\-]+.*'  # numbered division
    r'|(?:INT\.|EXT\.|INT/EXT\.?)[ \t].*'                           # screenplay slugline
    r')[ \t]*$')


class DocsIngestor:
    name = "docs"

    def handles(self, path: Path) -> bool:
        return path.suffix.lower() in DOC_EXT

    def ingest(self, ctx: IngestContext, path: Path) -> None:
        text = path.read_text("utf-8", "ignore")
        aid = ctx.add_artifact(path, "docs", None, ctx.sha(text))
        lines = text.splitlines(keepends=True)
        bounds = [i for i, ln in enumerate(lines) if _DOC_BOUNDARY.match(ln)]
        if not bounds:
            ctx.doc_chunk(aid, path.name, text)
            return
        # preamble before the first division (title block, recitals)
        if bounds[0] > 0:
            pre = "".join(lines[:bounds[0]])
            if pre.strip():
                ctx.doc_chunk(aid, path.name, pre)
        # one chunk per division, named by its heading line
        for j, b in enumerate(bounds):
            end = bounds[j + 1] if j + 1 < len(bounds) else len(lines)
            heading = lines[b].strip().lstrip("#").strip()
            ctx.doc_chunk(aid, heading, "".join(lines[b:end]))


class PdfIngestor:
    name = "pdf"

    def handles(self, path: Path) -> bool:
        return path.suffix.lower() in PDF_EXT

    def ingest(self, ctx: IngestContext, path: Path) -> None:
        try:
            import fitz  # PyMuPDF
        except ImportError:
            return
        doc = fitz.open(path)
        aid = ctx.add_artifact(path, "pdf", None, ctx.sha(str(path) + str(doc.page_count)))
        ddir = DERIVED_ROOT / ctx.workspace / re.sub(r"[^\w.-]", "_", path.name)
        ddir.mkdir(parents=True, exist_ok=True)
        for pno in range(doc.page_count):
            body = doc.load_page(pno).get_text("text")
            cid = ctx.add_chunk(aid, "page", f"p{pno + 1}", None, None, body)
            ctx.extract_doc_mentions(cid, body)
            # Extract page text to disk (as .md, which semble indexes as DOCS).
            dfile = ddir / f"p{pno + 1:04d}.md"
            dfile.write_text(body, "utf-8")
            store.add_derived(ctx.conn, ctx.workspace, str(dfile.resolve()), str(path), pno + 1)
        store.add_source(ctx.conn, ctx.workspace, str((DERIVED_ROOT / ctx.workspace).resolve()))


class OpenApiIngestor:
    """OpenAPI / Swagger specs (.json/.yaml/.yml). A spec is a first-class medium in
    the wedge: each declared path becomes an endpoint chunk AND a *server* http
    connector, so the routes a service documents bind to the client calls that hit
    them — connecting a third kind of artifact (the contract) to the code."""
    name = "spec"
    _METHODS = ("get", "post", "put", "delete", "patch", "head", "options", "trace")

    def handles(self, path: Path) -> bool:
        if path.suffix.lower() not in SPEC_EXT:
            return False
        try:
            head = path.read_text("utf-8", "ignore")[:4096]
        except OSError:
            return False
        # Cheap sniff before a full parse: must look like an OpenAPI/Swagger doc.
        return bool(re.search(r'["\']?(openapi|swagger)["\']?\s*:', head))

    def _load(self, path: Path):
        text = path.read_text("utf-8", "ignore")
        if path.suffix.lower() == ".json":
            import json
            return json.loads(text)
        import yaml
        return yaml.safe_load(text)

    def ingest(self, ctx: IngestContext, path: Path) -> None:
        try:
            spec = self._load(path)
        except Exception:
            return
        if not isinstance(spec, dict):
            return
        text = path.read_text("utf-8", "ignore")
        aid = ctx.add_artifact(path, "spec", "openapi", ctx.sha(text))
        title = (((spec.get("info") or {}).get("title")) or path.name)
        paths = spec.get("paths") or {}
        # locate the line of a route in the raw text for citation (best-effort).
        lines = text.splitlines()

        def _line_of(route: str) -> int | None:
            for i, ln in enumerate(lines, 1):
                if route in ln:
                    return i
            return None

        for route, item in paths.items():
            if not isinstance(route, str) or not route.startswith("/"):
                continue
            methods = [m.upper() for m in (item or {}) if m.lower() in self._METHODS] if isinstance(item, dict) else []
            label = f"{title} {' '.join(methods)} {route}".strip()
            body = f"{label}\n" + _summarize_path(item)
            cid = ctx.add_chunk(aid, "endpoint", f"{' '.join(methods) or 'ANY'} {route}", _line_of(route), None, body)
            # endpoint as an entity surface (so synthesis can relate it to code/docs).
            eid = ctx.ensure_entity(route, "endpoint")
            ctx.add_mention(eid, cid, route)
            # the spec SERVES this route → a server connector that binds to client calls.
            norm = _connectors._normalize("http", route)
            if norm:
                ctx.add_connector(aid, "http", "server", norm, route, _line_of(route))


def _summarize_path(item) -> str:
    if not isinstance(item, dict):
        return ""
    bits = []
    for method, op in item.items():
        if not isinstance(op, dict):
            continue
        summ = op.get("summary") or op.get("operationId") or ""
        bits.append(f"{method.upper()}: {summ}".rstrip(": "))
    return "\n".join(bits)


# ----------------------------------------------------------------------------- registry

# Order matters only when extensions overlap; built-ins are disjoint by extension
# except specs (which content-sniff). Extend by appending an Ingestor here.
REGISTRY: list[Ingestor] = [
    CodeIngestor(),
    OpenApiIngestor(),
    DocsIngestor(),
    PdfIngestor(),
]


def register(ingestor: Ingestor) -> None:
    REGISTRY.append(ingestor)


def resolve(path: Path) -> Ingestor | None:
    """First ingestor that handles ``path`` (None → skip)."""
    for ing in REGISTRY:
        if ing.handles(path):
            return ing
    return None
