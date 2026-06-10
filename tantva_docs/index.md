
# Tantva

**Smart RAG: induce a schema from the user's intent, index any corpus into a typed, cited
knowledge graph, then answer from the graph instead of re-reading.**

## The central idea

Plain RAG chunks everything and hopes embeddings surface the answer. A general agent re-reads the
corpus on every question. Tantva takes a third path: first understand what the user wants to ask,
and then design the index for it.

The unit of that design is a **lens**: a per-corpus schema (entity types, relation types,
properties) induced by the LLM from the user's stated intent and the artifact's actual content.

For example:

- a credit analyst's contract gets `defined_term` / `covenant` / `event_of_default` nodes and
  `uses_term` blast-radius edges;
- a screenwriter's novel gets characters, scenes, and `shares_scene`;
- a multi-repo codebase gets call graphs and cross-repo topic bindings.

Same engine, same store, same query surface. The lens is the only thing that changes. The lens is
induced from the user's role and goals, never from a known question list, and every type is
anchored to a small upper spine (agent · event · information_object · …) so graphs stay joinable
across domains.

Three design commitments follow:

1. **Grounded by construction.** Every node and edge carries provenance (chunk/section/file:line,
   confidence, method). An answer is a set of cited claims.
2. **The LLM is the engine's "soul," not its plumbing.** The engine (a generic SQLite property
   graph + deterministic extraction primitives + MCP tools) makes zero model calls. All judgment
   (inducing the lens, schema-guided extraction, query-time synthesis) runs in the user's own
   Claude Code session and its subagents. No API key; data stays local.
3. **Pay once, query forever.** The expensive understanding (a schema-guided LLM extraction pass
   over every chunk, then entity resolution) happens once at ingest; query cost is then small and
   independent of corpus size.

## Scope

- **In scope:** any text-bearing corpus (multi-repo codebases, legal contracts, novels,
  screenplays, textbooks, cookbooks, multi-volume canons); lens induction from intent;
  deterministic + LLM extraction; entity resolution; persona-aware cited investigation;
  ingest-time wiki synthesis; a falsifiable eval program against a strong baseline.
- **Out of scope (v1):** non-text media; engine-internal model calls; real-time/streaming
  ingestion; multi-user serving. The engine targets a single analyst's Claude Code session.

## What's built

- **Engine** (`explainer-cli`): a local property-graph store where every node and edge carries
  its citation; deterministic extractors for structured artifacts (sections, defined terms,
  cross-references, call graphs); LLM-driven extraction for everything else; entity resolution.
  Exposed to Claude Code as ~25 MCP tools. Grounded in established knowledge-representation
  practice (schema/instance separation, provenance-bearing claims, a small upper ontology).
- **Skills**: the prompts that drive the pipeline. Induce a lens from your intent, build the
  graph, investigate with citations, and optionally synthesize a wiki from the graph. None of
  them are domain-specific; the lens carries all domain knowledge.
- **Evaluation**: 8 corpora (code, legal, novels, a screenplay, a textbook, a cookbook, a
  multi-volume canon), 160 verified questions, judged against a strong same-model baseline that
  reads the corpus directly. Tantva matches the baseline on accuracy overall and wins where the
  corpus has dense internal structure. Full results in
  [Problem, Data & Evaluation](evaluation.md).

## The documents here

- **[Personas](personas.md)**: who uses this, the difficulty they face, and how Tantva helps.
- **[System Design](system-design.md)**: architecture, tradeoffs, chunking strategy, and tools.
- **[Problem, Data & Evaluation](evaluation.md)**: methodology, results across all corpora,
  learnings, and further research.
