
# System Design

Covers the architecture, the RAG-vs-agents choice, the chunking strategy, the tools, and the
tradeoffs accepted.

## Architecture

```
┌─────────────────────────  user's Claude Code session  ─────────────────────────┐
│                                                                                 │
│   skills: induce-lens · setup (ingest pipeline) · investigate · extract · wiki  │
│   (lens induction, LLM extraction, and answering run here, via subagents)       │
│                                                                                 │
└───────────────▲─────────────────────────────────────────────▲──────────────────┘
                │            ~25 MCP tools (read + write)      │
┌───────────────┴─────────────────────────────────────────────┴──────────────────┐
│                         engine (Python, zero LLM calls)                         │
│                                                                                 │
│  lens registry        primitive registry         retrieval                      │
│  (schemas, frozen,    (deterministic extractors, (static embeddings + BM25,     │
│   spine-anchored)      dispatched per lens)       keyword fallback)             │
│                                                                                 │
│            SQLite property graph (one file, one workspace per corpus)           │
│   workspaces · artifacts · chunks · entities · edges · mentions · lenses        │
└─────────────────────────────────────────────────────────────────────────────────┘
```

The system is split into two layers. The engine is a Python package that handles storage,
deterministic extraction, and retrieval; it makes no model calls. Everything that requires
judgment — inducing the schema, schema-guided extraction, answering — runs in the user's Claude
Code session through the MCP tools. As a result there is no API key, data stays on the user's
machine, and the user's existing Claude Code subscription is the only compute cost.

### The store

One SQLite database, one isolated workspace per corpus. Five core tables: **artifacts** (source
files, PDFs, repos), **chunks** (the retrieval substrate, each with a locator), **entities**
(typed nodes), **edges** (typed relations), and **mentions** (entity↔chunk occurrences). Every
table has a free-form `props` JSON column, so a new domain adds entity and relation *types*
through its lens rather than requiring schema migrations.

Each edge records `source` (provenance), `confidence`, `method` (which extractor produced it),
and an `asserted` flag. This lets the graph represent statements that are attributed but not
endorsed — for example, a doc that describes code incorrectly is stored as a non-asserted edge:
citable, but not treated as true.

### The lens

A lens is a registered, frozen schema: `entity_types`, `relation_types`, and `properties`, plus
two fields that keep graphs comparable across domains:

- **`parents`** — every type maps to one of nine general categories
  (`agent · object · place · information_object · event · role · quality · time · relationship`).
  One lens may call a type `character` and another `party`; both anchor to `agent`, so queries
  can span corpora.
- **`aligns`** — optional references to standard vocabularies (schema.org, SKOS, PROV), stored
  as strings.

This follows the standard schema/instance separation from knowledge representation (TBox/ABox):
the lens is induced once per corpus and then frozen, and the graph holds the instances. Lenses
are frozen because changing a schema mid-corpus would invalidate earlier extractions.

### Extraction

A lens declares which extractors to run; the engine dispatches them from a registry. Extraction
happens in three stages:

1. **Deterministic primitives.** Pattern-based extractors for artifacts with explicit structure:
   section/slugline/chapter markers, defined-term patterns, section-to-section cross-references,
   recurring-proper-noun and salient-term detection, co-occurrence, tree-sitter call graphs,
   doc↔code links, and route/topic bindings. These are cheap and precise, and a lens includes
   them only when the artifact's structure matches.
2. **Schema-guided LLM extraction.** The ingest skill pages through the chunks, fans out
   subagents, and each subagent writes the schema's typed entities and relations back through
   the MCP write tools, citing the source chunk for every claim. Subagents are model-tiered:
   bulk entity typing runs on a cheaper model, relation extraction on a stronger one. This stage
   does the bulk of the work on most corpora — in the contract evaluation it produced 345
   defined-term nodes where the pattern extractors produced 70 — and it is what lets the engine
   handle artifact types that have no matching deterministic primitive.
3. **Entity resolution.** Name normalization plus an embedding pass collapse alias surface forms
   ("the Borrower" / "Borrower"; a character's maiden name, married name, and honorific) into
   one canonical node, re-pointing mentions and edges. This stage is required: unresolved
   aliases distort every count and ranking built on the graph.

## RAG or agents?

Both, in different places.

- **Ingest is agentic.** Building the graph requires judgment about what types matter and which
  relations hold, so it is an agent workflow (induce → critique → deterministic primitives →
  LLM extraction → resolution). It runs once per corpus.
- **Query is retrieval over a structured index.** Answers come from graph traversal
  (`entities`, `neighbors`, `cross_edges`) and hybrid search (`search`), with `get_chunk` for
  exact cited text. For connective questions, the investigate skill fans out subagents along
  angles derived from the lens's relation types: a contract gets a definition-dependency angle,
  a novel a co-occurrence angle, a codebase call-graph and cross-repo angles.

The reasoning: plain RAG returns passages, which cannot answer relational questions ("what
depends on X") without the relations having been extracted; a pure agent answers them by
re-reading the corpus on every question. Splitting the work — agentic understanding once at
ingest, cheap structured retrieval at query time — addresses both.

## Chunking strategy

Chunking is per artifact kind and structure-aware. The chunk is the citation unit, so chunk
boundaries follow the artifact's own structure:

| artifact | strategy |
|---|---|
| **code** | tree-sitter parse → one chunk per function/class, with file/line locators; the call graph comes from the same parse |
| **docs / markdown** | heading-aware splits; legal `SECTION/ARTICLE` headings and screenplay sluglines are also recognized, so a section or scene is not split mid-unit |
| **PDF** | per-page text extraction; pages become citable `p<N>` units, indexed like any text |
| **prose / books** | page or chapter units, following the source's native structure |
| **specs (OpenAPI)** | one chunk per route; these also feed the route-binding extractor |

The cross-reference extractor and the LLM extraction stage both assume a chunk corresponds to a
coherent unit (a section, a scene, a function), which is why boundary detection is done per
artifact kind rather than by fixed-size windows.

## Tools

| layer | choice | why |
|---|---|---|
| storage | SQLite (single file) | local, zero-ops, transactional; sufficient for single-analyst corpora |
| code parsing | tree-sitter | language-accurate functions, classes, and call edges |
| retrieval | static embeddings (Model2Vec) + BM25, keyword fallback | CPU-only, no API; degrades gracefully if the model is unavailable |
| interface | MCP server (~25 tools) | works with any MCP host; Claude Code is the primary one |
| orchestration | Claude Code skills + subagents | the pipeline's judgment steps are prompts, versioned in the repo like code |
| packaging | `uv` + a Claude Code plugin marketplace | one-command install; dependencies resolve on first launch |

## Tradeoffs accepted

1. **No model calls in the engine.** Benefit: no API key, local data, a simple engine. Cost:
   extraction quality depends on the host session following the skills; it is orchestrated, not
   guaranteed. Mitigated with explicit skill contracts and a test that scores lens induction
   against a domain rubric.
2. **Ingest cost is front-loaded.** Schema-guided extraction over a large corpus takes minutes
   and a significant token budget. It pays for itself only when the corpus is queried
   repeatedly; the evaluation reports this cost separately rather than folding it into
   query-time numbers.
3. **Frozen lenses.** Re-shaping a schema means re-registering and re-extracting. Flexibility is
   traded for graph consistency.
4. **SQLite rather than a graph database.** The traversals needed (`neighbors`, typed lookups)
   are simple SQL, and a single local file is easier to operate than a graph server. Complex
   multi-hop query languages are given up.
5. **Deterministic extractors are optional.** They could carry more of the load on structured
   artifacts, but treating them as the primary mechanism ties the engine to the artifact types
   already seen. The LLM extraction stage is the primary mechanism; patterns reduce its cost
   where structure allows.
6. **Single analyst, not a service.** No multi-user serving, auth, or streaming ingestion in
   v1. The deployment target is one person's Claude Code session.
