---
description: Generate a navigable, grounded knowledge wiki for a workspace at ingest time and index it back — so it's both browsable documentation AND retrieval substrate that makes every future answer better. Per-lens (code → architecture wiki, prose → literary companion, …).
---

# Wiki — synthesize documentation at ingest, then index it

This is the "generous at ingest" payoff (ADR-028): once the corpus is ingested and typed, **you** (the session) synthesize a structured wiki, grounded in the graph, and **index it back** so it improves Q&A. Run it after `setup`/ingest. It is real, substantial work, done once.

The shape mirrors the best auto-doc tools, but with three things they lack: **per-claim `file:line` citations**, **cross-artifact reach** (repos + docs + PDFs, via the wedge), and **the flywheel** — the wiki becomes indexed content.

## What to generate — derive the plan from the lens + the graph (don't expect it baked)

The synthesis plan (`doc_types`, how to `decompose_by`, what to `ground_on`) is **derived per corpus, not
read from a hardcoded engine constant** (ADR-036 — domain content isn't baked into seed lenses):

1. `get_lens(<workspace's lens>)` and `overview(workspace)` (the recorded **intent**). If the lens carries
   an induced `synthesis` block, use it.
2. Otherwise **derive the plan from the lens's `entity_types` + the intent + what's actually in the graph**
   (`entities` by type, the dominant types): make one doc-type per major entity type, decompose by it,
   ground on the primary chunks for that type. Examples it should *produce* (not be handed):
   - code → architecture-overview, subsystem-guide (per package / call-graph community), flow-narrative.
   - a novel → character profiles, place/setting pages, relationship map (per `character`/`place`).
   - a contract → a defined-terms glossary, a per-section guide, a cross-reference map.
   - a textbook → concept pages + a dependency map (per `concept`, via `depends_on`).
   The shape follows the corpus's real types — never a fixed list tuned to the first thing we indexed.

## Passes

1. **Decompose into topics — from the graph, not guesses.** Use `entities`/`neighbors`/`list_artifacts` to find the real subsystems (code: cluster by directory + call-graph; prose: the typed `entities` by etype). Produce the wiki's table of contents.
2. **Per-topic synthesis (grounded, PRIMARY only).** For each topic: `search` + `get_chunk` + `neighbors` over the **primary** corpus, then write a section — responsibility/summary, the key entities **cited `repo/file:line` (or page)**, the internal flow, and links to related topics. Name real symbols; explain how it *works*, not just what exists.
3. **Flow & overview.** Trace the cross-topic flow (code: the lifecycle via the call graph + cross-repo bindings; prose: arcs/timeline) and write the top-level overview that ties the sections together.
4. **Cross-link** sections to each other and to **cross-artifact edges** (`connections`, `cross_edges`) — the connective tissue single-repo tools can't show.
5. **Index it back (the flywheel).** Write the sections as markdown files, then **`ingest(<wiki_dir>, workspace, provenance="synthesized")`**. Now the wiki is searchable, and `doc↔code` synthesis links each section to the code it describes. Future answers draw on the synthesized subsystem docs **and** the primary code.
6. **Render (optional)** a browsable HTML wiki via the `artifact` skill (`render_artifact`) with mermaid, for humans / the docs site.

## Discipline (non-negotiable)
- **Ground on primary only.** Never synthesize *from* generated docs — that drifts model-on-model. (On regeneration: `clear_synthesized(workspace)` first, then generate from primary, then re-ingest.)
- **Citations resolve to primary.** The wiki is the navigation layer; every claim's citation points at the authoritative `file:line`/page, traced via the `doc↔code` edge. (Strictly better than a blanket "this may be wrong" disclaimer.)
- **Mark it synthesized.** Always ingest the wiki with `provenance="synthesized"` so trust, staleness, and regeneration stay honest.
- **Bounded.** Decompose first; synthesize per topic. Cost scales with topic count, not file count.

## Why it matters
The wiki is not a dead-end artifact — it's **retrieval substrate**. After it's indexed, Q&A answers with the *structure and completeness* of a generated wiki **plus** per-claim citations and cross-artifact reach. Synthesis → indexed docs → better answers.
