---
title: Home
nav_order: 1
---

# Tantva

**Tell it what you want to ask. It designs the index.**

Tantva turns any corpus — code, contracts, novels, textbooks — into a typed, cited knowledge
graph shaped by your intent, then answers from the graph instead of re-reading.

---

## The central idea

Plain RAG chunks everything and hopes embeddings surface the answer. A general agent re-reads
the corpus on every question. Tantva takes a third path: first understand what the user wants to
ask, then design the index for it.

```mermaid
flowchart LR
  intent(["your intent<br/><i>role + goals, in your words</i>"]) --> lens["induced <b>lens</b><br/>entity types · relations · properties"]
  lens --> kg[("typed, cited<br/>knowledge graph")]
  kg --> ans(["cited answers<br/><i>graph traversal, not re-reading</i>"])
```

The **lens** is a per-corpus schema induced by the LLM from your stated intent and the
artifact's actual content — never from a question list. Same engine, same store, same query
surface; the lens is the only thing that changes:

| who | corpus | the lens builds | one call answers |
|---|---|---|---|
| credit analyst | a credit agreement | `defined_term` / `covenant` / `event_of_default` nodes, `uses_term` edges | "if this definition changes, what breaks?" |
| screenwriter | a novel | characters, scenes, `shares_scene`, aliases resolved | "who shares scenes with whom?" |
| platform engineer | a multi-repo codebase | call graphs, cross-repo route/topic bindings | "trace this event across the repos" |

Everything runs locally inside your Claude Code session — the engine makes zero model calls, so
there is no API key and your data stays on your machine. Every node and edge carries its
citation.

---

## Who it's for

**Broad on purpose.** Tantva isn't tuned to one domain — you tell Claude your niche, and it
custom-designs the index for exactly that use case. The same engine serves whoever shows up
next.

| who | the problem | with Tantva | from the eval |
|---|---|---|---|
| **Priya** — staff engineer onboarding to a multi-repo system | the cross-repo picture doesn't exist anywhere; `grep` misses dynamic wiring (runtime URLs, Kafka topics from config) | route/topic bindings, the call graph, and doc↔code links make one question return a cited, cross-repo trace | a five-hop SDK→ClickHouse trace, each hop cited `repo/file:line` — 1 agent and ~63 tool calls vs 39 agents and 818 reading from scratch |
| **Alex** — credit analyst working a contract | a credit agreement is a web of definitions; amending one silently moves ratios and baskets elsewhere | every defined term extracted, `uses_term` dependency edges wired, aliases resolved — blast radius is one graph call | found all **6** consumers of a changed term (baseline: 3); the baseline inverted the default-cure logic, the graph got it right |
| **Sam** — screenwriter adapting a novel | text search counts strings, not people — censuses and rankings are silently wrong across maiden names and honorifics | the character/scene graph plus entity resolution collapses each character into one node | on *Pachinko*: baseline census 9 vs the true 10–12, ranked by first mention; the alias-resolved graph got both right |
| **Dr. Rao** — researcher over an unfamiliar domain corpus | the right way to index isn't known up front; a bespoke pipeline per domain is weeks of engineering | state your role and goals; a schema is induced, validated, and extracted into — and must generalize to unseen questions | 3 of 3 blind lens inductions covered every must-have type, relation, and domain area in the rubric |
| **Maya** — docs / knowledge-management owner | docs go stale silently; nothing links what a doc claims to what the code does | doc↔code edges carry confidence and provenance, so drift becomes a first-class, cited finding | flagged that an authoritative doc had been mis-linked to a test fixture — surfaced its own weak spot, with evidence |

---

## Scope

- **In scope:** any text-bearing corpus; lens induction from intent; deterministic + LLM
  extraction; entity resolution; persona-aware cited investigation; ingest-time wiki synthesis;
  a falsifiable eval program against a strong baseline.
- **Out of scope (v1):** non-text media; engine-internal model calls; real-time/streaming
  ingestion; multi-user serving. The engine targets a single analyst's Claude Code session.

## What's built

- **Engine** (`explainer-cli`): a local property-graph store where every node and edge carries
  its citation; deterministic extractors for structured artifacts; LLM-driven extraction for
  everything else; entity resolution. Exposed to Claude Code as ~25 MCP tools.
- **Skills**: the prompts that drive the pipeline — induce a lens from your intent, build the
  graph, investigate with citations, optionally synthesize a wiki. None are domain-specific;
  the lens carries all domain knowledge.
- **Evaluation**: 7 corpora, 140 verified questions, judged against a strong same-model
  baseline that reads the corpus directly. Tantva matches the baseline on accuracy overall and
  wins where the corpus has dense internal structure. Full results in
  [Problem, Data & Evaluation](evaluation).
