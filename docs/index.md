---
title: Home
nav_order: 1
---

# Tantva

**Tell it what you want to ask. It designs the index.**

Tantva turns any corpus — code, contracts, novels, textbooks — into a typed, cited knowledge
graph shaped by your intent, then answers from the graph instead of re-reading.

[Get started](https://github.com/Tantva/explainer-cli-public#setup--step-by-step){: .btn .btn-primary }
[See the evaluation](evaluation){: .btn }
[System design](system-design){: .btn }

---

## The central idea

Plain RAG chunks everything and hopes embeddings surface the answer. A general agent re-reads
the corpus on every question. Tantva takes a third path: first understand what the user wants to
ask, then design the index for it.

```mermaid
flowchart LR
  intent(["your intent<br/><i>role + goals, in your words</i>"]) --> lens["induced <b>lens</b><br/>entity types · relations · properties"]
  lens --> graph[("typed, cited<br/>knowledge graph")]
  graph --> ans(["cited answers<br/><i>graph traversal, not re-reading</i>"])
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

### Priya — staff engineer onboarding to a multi-repo system

**The cross-repo picture doesn't exist anywhere.** `grep` drowns her in matches and misses
dynamic wiring (a URL built at runtime, a Kafka topic resolved through config). Tantva ingests
the repos once; route/topic bindings, the call graph, and doc↔code links make a single question
return a cited, cross-repo trace.

> "How does an event get from the SDK to ClickHouse?" — a five-hop trace across
> `sentry-python → relay → snuba`, each hop cited `repo/file:line`. One agent and ~63 tool
> calls, where the same model reading from scratch used 39 agents and 818.
{: .result }

### Alex — credit analyst working a contract

**A credit agreement is a web of definitions.** Amending one definition silently moves ratios
and baskets elsewhere in the document. Tantva's legal lens extracts every defined term, wires
term-dependency (`uses_term`) edges, and resolves aliases — blast radius becomes one graph call.

> Tantva found all six consumers of a changed defined term where the read-everything baseline
> found three — and the baseline confidently inverted the contract's default-cure logic, while
> the graph's covenant→default edges got it right.
{: .result }

### Sam — screenwriter adapting a novel

**Text search counts strings, not people.** A 500-page cast goes by maiden names, married
names, and honorifics, so every census and ranking is silently wrong. Tantva's prose lens
builds the character/scene graph and entity resolution collapses each character into one node.

> On *Pachinko*, the baseline string-counted a family census (9 vs the true 10–12) and ranked
> first appearances by first mention; the alias-resolved graph got both right.
{: .result }

### Dr. Rao — researcher over an unfamiliar domain corpus

**The right way to index isn't known up front.** Off-the-shelf RAG returns passages, not typed
relationships; a bespoke extraction pipeline per domain is weeks of engineering. State your role
and goals; Tantva induces a schema for that domain, validates it, and extracts into it — and the
schema must generalize to questions you haven't asked yet.

### Maya — docs / knowledge-management owner

**Docs go stale silently.** Nothing links what a doc claims to what the code does. Tantva emits
doc↔code edges with confidence and provenance, so drift becomes a first-class, cited finding.

> On the Sentry corpus, Tantva flagged that an authoritative ingest doc had been mis-linked to a
> test fixture by its own synthesizer — it surfaced its own weak spot, with evidence.
{: .result }

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
