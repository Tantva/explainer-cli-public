---
title: Problem, Data & Evaluation
nav_order: 4
---

# Problem, Data & Evaluation

## Problem definition

The questions that matter most about a body of knowledge cut across its parts: "if this defined
term is amended, which clauses break," "trace this event from SDK to storage across three repos,"
"who shares scenes with whom across three generations." A general agent answers these only by
reading everything from scratch on every question — slow, expensive, and recurring. Tantva ingests
a corpus once into a typed, cited knowledge graph shaped by the user's intent (an induced lens),
then answers from the graph.

The thesis under test:

1. **Accuracy parity.** Graph-backed answers match a strong read-everything agent on quality.
2. **Structural advantage.** On corpora with dense internal structure (definition webs,
   alias-heavy casts, cross-repo contracts), the graph wins outright.
3. **Cost asymmetry.** The reader's cost recurs per question set and grows with corpus size; the
   graph's ingest is one-time and its query-time cost is flat.

## Method

**Corpora.** Seven, spanning very different artifact types: six Sentry-pipeline repositories
(code), a $950M credit agreement, two novels (*Dune*, *Pachinko*), a screenplay (*Andor*), a
566-page cookbook, and a 1,099-page economics textbook. Each carries a 20-question set with a
hand-verified, citation-grounded answer key.

**Contestants.** Two per corpus, run in fresh, isolated sessions with the answer keys removed:

- **grep baseline** — the same Claude model with `grep`/`Read` over the raw text. Deliberately
  strong: a competent agent free to read everything, not a strawman.
- **Tantva** — the same model restricted to Tantva's MCP tools over a graph built by the full
  pipeline (intent → induced lens → deterministic primitives → schema-guided LLM extraction →
  entity resolution).

**Scoring.** An independent judge per corpus scores both contestants against per-question
"judge on" pass conditions (1 / 0.5 / 0), identical strictness on both sides.

**Three rules keep the comparison honest.** Each was added after an earlier draft of the method
failed without it:

1. **Discriminability gate.** A question counts as discriminating only if its answer is not
   co-located in one passage (relational, aggregate, blast-radius, cross-document shapes).
   Single-passage questions measure nothing — grep aces them trivially. A small parity floor of
   such questions is kept deliberately so the comparison isn't staged in Tantva's favor.
2. **Contamination control.** Several corpora are famous and memorized by the model. Every set
   includes an out-of-corpus bucket: plausible questions whose answers are not in this text (a
   TV-only character, a later-canon fate, a post-publication policy). Pass = grounded abstention;
   fail = answering from parametric memory. All credited answers must carry a real citation
   (page / §section / `repo/file:line`).
3. **Blind lens induction.** Each corpus carries a `user-context.md` — a realistic role brief
   ("I'm a credit analyst reviewing covenant risk…"). The lens is induced from that intent alone,
   blind to the questions, which the contestant opens only at answer time. A lens shaped to a
   known question list would be teaching-to-the-test; the lens must generalize from a vague human
   intent to unseen questions, as in real use. The induction step is itself tested: blind
   inductions are scored against a hand-authored domain rubric (on the contract, 3 of 3
   independent inductions covered all must-have types, relations, and domain areas).

## Results — text corpora

Six corpora judged head-to-head, 20 points each.

| corpus | artifact type | size | grep | Tantva | verdict |
|---|---|---|---|---|---|
| **Credit agreement** | legal | 93k words | 18.5 | **19.0** | **Tantva** — relational bucket 7.0 vs 5.5 |
| **Pachinko** | novel (alias-heavy, 3 generations) | 481 pp | 18.0 | **19.5** | **Tantva** — discriminating 13.5 vs 12.0 |
| **Classic Indian Cooking** | reference / recipes | 566 pp | 18.5 | 18.5 | tie |
| **Dune** (Book 1) | novel | 345 pp | **20.0** | 19.5 | grep |
| **Andor** screenplay | screenplay | 55 pp | **20.0** | 19.5 | grep |
| **Indian Economy** | textbook | 1,099 pp | **18.0** | 17.0 | grep |
| **Total** | | | **113.0 / 120** | **113.0 / 120** | **tie (94.2%)** |

**Thesis 1 (parity): confirmed.** A tie across 120 judged questions. Both contestants also passed
all 16 out-of-corpus traps on every corpus — zero fabrication from memory on either side.
Grounding discipline drives abstention; the index neither helps nor hurts it.

**Thesis 2 (structural advantage): confirmed where structure is dense — and only there.**

- **The contract is the clear win.** Tantva took the blast-radius/cross-reference bucket 7.0 vs
  5.5. Most telling: grep confidently inverted the contract's default-cure logic (§10(c) vs
  §10(d)) — a wrong answer, not a gap — while Tantva's covenant→default edges produced the correct
  immediate-vs-30-day-cure split. Tantva's `uses_term` edges found all six consumers of a changed
  defined term where grep found three.
- **Pachinko is the alias win.** Entity resolution decided the questions grep structurally
  fumbles: grep counted a family census by string-matching (9 vs the true 10–12) and ranked
  "first appearances" by first mention rather than presence.
- **Grep wins read-once-able single documents.** On a 55-page screenplay or one novel, an
  attentive reader holds the whole artifact; pre-built structure adds little accuracy.
- **The textbook loss is an extraction-coverage loss, not a method loss**: a committee the
  extraction pass missed, two monetary-aggregate systems conflated. The graph is only as good as
  its extraction pass; this bounds the architecture honestly.

## Results — code corpus (Sentry, six repos)

The code eval used the same protocol, with the verified key as baseline (native Claude reading
the repos from scratch is the key).

| | quality (/20) | agents | tool calls | query tokens |
|---|:--:|:--:|:--:|:--:|
| Native Claude (read everything) | 20.0 | 39 | 818 | ~1.17M |
| **Tantva (single pass over index)** | **17.5** | **1** | **~63** | small (one agent) |

A single pass over the index reached 87.5% of from-scratch quality at roughly 1/13 the tool calls
and 1/39 the agents, including both abstentions. The two misses were retrieval-depth failures,
not coverage gaps. Ingest was deterministic (tree-sitter + connectors, zero LLM tokens, ~104s for
all six repos → 3,040 artifacts, 711 cross-source edges). A planned third baseline (Google Code
Wiki) was excluded, not scored: it had indexed only 1 of the 6 repos, so no like-for-like
comparison was possible.

## Results — cost

Ingest (one-time) is reported separately from query time (recurring):

| corpus | grep per question set | Tantva ingest (once) | Tantva query |
|---|---|---|---|
| contract (93k words) | ~60k tok · 15 min | ~275k tok · 15 min | ~11 graph calls + cited retrieval |
| cookbook (566 pp) | ~310k tok (whole-book fan-out) | ~1.9M tok · 65 min | ~92 graph calls |
| textbook (1,099 pp) | ~80k tok · 22 min (selective) | ~1.4M tok · 22 min | ~57 calls |
| Pachinko (481 pp) | ~29 calls · 20 min (recurs every session) | ~648k tok · 12 min | ~40 calls, zero page reads |

Two observations. First, at these sizes a single question set does not amortize the ingest; grep
is often cheaper in total for one pass. Second, the structure of the asymmetry is exactly as
claimed: Tantva's query pass is small and corpus-size-independent (~40–90 graph calls whether the
corpus is 93k or 1M words, zero raw-page reads), while the baseline's cost recurs per question
set and tracks corpus size. The relevant metric is flat query cost vs. linear, recurring read
cost — which dominates when corpora are large and queried repeatedly, not "fewer tokens on a
small document queried once."

## What we learned

1. **A strong baseline keeps you honest.** Claude+grep is a very good reader — it beat us on
   corpora we assumed we'd win. The result (win where structured, parity overall) is worth more
   than the flattering result a weak baseline would have produced.
2. **The schema-guided LLM extraction pass is the backbone; deterministic patterns are
   accelerators.** On the real contract, regexes surfaced 70 defined terms; the extraction pass
   found 345.
3. **Entity resolution is not optional.** It single-handedly decided Pachinko's census and
   ranking questions; unresolved aliases silently corrupt every count.
4. **Lens induction generalizes from intent alone — and is testable.** Blind inductions hit the
   domain rubric 3 of 3; the induction test also caught a real extraction gap (the contract's
   dominant colon-style definition form) before any eval run did.
5. **Where the graph loses, it loses to extraction coverage, not method** — a missed committee, a
   missed final scene. The fix is a completeness pass at ingest, not a different architecture.
6. **Index advantage is a function of corpus structure.** Dense cross-references and aliases →
   the graph wins; linear read-once narrative → parity at best.

## Further research

- **A scale sweep**: run the same question set at increasing corpus sizes and publish both cost
  curves (reader linear, graph flat) with the break-even question-set count.
- **Extraction-coverage QA**: an adversarial "what did we miss?" pass at ingest (sampled re-reads
  diffed against the graph), targeting the gap behind every point Tantva lost.
- **Repeat-query amortization**: measure real multi-session usage where one graph serves many
  question sets — the regime the architecture is built for.
- **Mixed knowledge bases**: code + docs + contracts in one workspace, where shared type
  anchoring should let a single graph join domains.
- **The wiki flywheel**: measure whether ingest-time synthesized documentation, indexed back into
  the graph, raises answer quality on the same question sets.
- **Tiered-extraction economics**: how far bulk extraction can be pushed to cheaper models before
  accuracy drops.
- **Code-eval fixes**: first-class JSON-schema ingestion and the producer↔consumer topic binder,
  the two limiters surfaced by the Sentry run.
