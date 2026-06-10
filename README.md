# Tantva (`explainer-cli`)

**Smart RAG for Claude Code: tell it what you want to ask, and it designs the index.**

Tantva ingests any text-bearing corpus — a multi-repo codebase, a legal contract, a novel, a
textbook, a stack of specs — into a **typed, cited knowledge graph**, shaped by a **lens**: a
per-corpus schema (entity types, relation types, properties) that the LLM **induces from your
stated intent**. You then ask questions and get grounded, citation-backed answers from the graph
instead of re-reading the corpus every time.

It runs **entirely locally** inside your installed Claude Code: the engine (this Python package)
makes **zero LLM calls** — Claude Code is the brain (lens induction, schema-guided extraction,
answering), the engine is the structured memory (SQLite property graph + deterministic extraction
primitives + MCP tools). No API key. Your data stays on your machine.

## How it works (the pipeline)

```
your intent ("I'm a credit analyst; I care about covenant risk…")
        │
        ▼
 1. INDUCE a lens          the LLM designs the schema: entity_types, relation_types,
    (intent ∩ artifact)    properties, spine anchors, extractor composition
        │
        ▼
 2. CRITIQUE the lens      does every sub-area of your intent have a home? is each
                           type actually present in the text?
        │
        ▼
 3. INGEST (deterministic) section-aware chunking + the lens's pattern primitives:
                           structural markers, defined-term patterns, cross-references,
                           proper-noun/salient-term surfacers, tree-sitter call graphs…
        │
        ▼
 4. LLM EXTRACTION         the universal backbone: subagents walk the chunks and write
    (schema-guided)        the schema's typed entities + relations, each cited to its
                           source chunk (model-tiered for cost)
        │
        ▼
 5. ENTITY RESOLUTION      collapse aliases ("the Borrower"/"Borrower"; a character's
                           three names) into canonical nodes
        │
        ▼
 6. ASK                    answers come from graph traversal (neighbors/entities/search
                           + exact-passage citations), not from re-reading the corpus
```

Every node and edge carries provenance (source chunk, confidence, method). Answers are cited
claims or honest abstentions.

## Setup — step by step

**Prerequisites:** [Claude Code](https://claude.com/claude-code) installed; [`uv`](https://docs.astral.sh/uv/)
on your PATH (the MCP server resolves its Python deps with it on first launch).

1. **Add the marketplace and install the plugin.** In any Claude Code session:
   ```
   /plugin marketplace add Tantva/explainer-cli-public
   /plugin install explainer@explainer-cli-public
   /reload-plugins
   ```
2. **Verify.** Ask Claude: *"list the explainer tools"* — you should see `create_workspace`,
   `set_intent`, `inspect`, `register_lens`, `ingest`, `chunks`, `add_entity`, `add_relation`,
   `resolve_entities`, `search`, `entities`, `neighbors`, `overview`, … (~25 tools). The first
   call triggers a one-time `uv sync`; the first `search` downloads a small local embedding model.
3. **Ingest your first corpus.** `cd` into the project and run the setup skill:
   ```
   /explainer:setup
   ```
   It will ask one question — **"what do you want to be able to ask of this?"** — then run the
   whole pipeline above. Answer with your *role and goals*, not a question list (see personas
   below); the lens is induced from that.
4. **Ask questions.**
   ```
   /explainer:investigate If the definition of Consolidated EBITDA changes, which sections are affected?
   ```
   Or just ask in plain conversation — Claude will reach for the graph tools on its own once a
   workspace exists.
5. **(Optional) Generate a wiki.** `/explainer:wiki` synthesizes grounded, cited documentation
   from the graph (a defined-terms glossary, character profiles, an architecture overview —
   whatever fits the lens) and indexes it back, so future answers get better.

**Everything is stored locally** in `~/.explainer/explainer.db`, one isolated workspace per corpus.

## Usage by persona — worked examples

The same engine, the same five steps; only the *intent* differs — and therefore the lens, the
graph, and what one tool call can answer.

### 1. The credit analyst (a 93k-word credit agreement)

> **Intent you give at setup:** "I'm a credit analyst reviewing this agreement before a
> refinancing. I care about the financial covenants, what triggers a default, the conditions
> before drawing — and above all how the defined terms interlock: for any term, what relies on it."

Tantva induces a legal lens (`defined_term`, `section`, `party`, `covenant`, `event_of_default`;
relations `uses_term`, `references`, `obligates`), extracts ~350 defined terms with their
definitions, wires section cross-references and term-dependency edges, and resolves
"the Borrower"/"Borrower."

```
You:  If "Consolidated EBITDA" is amended, what's the blast radius?
      → neighbors("Consolidated EBITDA", relation="uses_term") — every clause that relies on
        it, each cited §X.Y, in one call. A reader has to re-scan all 93k words to assemble this.

You:  Enumerate every Event of Default with its grace period.
      → entities(etype="event_of_default") — the typed list, §10(a)–(o), already cited.
```

### 2. The screenwriter (adapting a 481-page novel)

> **Intent:** "I'm adapting this novel into a series. I need the cast and how central each
> character is, who shares scenes with whom across the three generations, the arcs, places, and
> timeline — so I can decide what to cut, merge, and dramatize."

Prose lens: characters/places/events, `shares_scene`/`appears_in` edges, and — critically —
**entity resolution**, so a character's maiden name, married name, and honorific count as one node.

```
You:  Rank the cast by presence and tell me who anchors each generation.
      → entities(etype="character") — mention-ranked, alias-resolved. (In our eval, a
        grep-based reader miscounted a family census by string-matching aliases; the graph got it.)

You:  Who shares scenes with Sunja in Book II?
      → neighbors("Sunja", relation="shares_scene") — ranked, page-cited.
```

### 3. The platform engineer (a six-repo event pipeline)

> **Intent:** "Onboarding to our ingest pipeline: SDK → relay → Kafka → snuba. I need the
> cross-repo contracts — who produces and consumes which topic, which routes bind the services,
> and where the docs have drifted from the code."

Code lens: tree-sitter call graphs per repo, route/topic connector binding across repos,
doc↔code edges.

```
You:  Trace an error event from the Python SDK to ClickHouse.
      → the graph walks SDK transport → relay endpoint → Kafka topic → snuba consumer, each hop
        a cited repo/file:line edge. (Eval: one agent + ~63 tool calls vs 39 agents + 818 calls
        reading from scratch.)

You:  What breaks if the envelope route changes?
      → cross-repo blast radius from the binding edges.
```

### 4. The home cook (a 566-page cookbook)

> **Intent:** "I cook from this book and improvise. I want: which dishes use an ingredient I have,
> what substitutes for what, which dishes share a technique, and how dishes group by region."

Recipe lens: `dish`/`ingredient`/`technique`/`region`, `uses` and `substitutes_for` edges
(~2,200 dish→ingredient edges in our build).

```
You:  I have asafoetida and a lot of yogurt — what can I make?
      → neighbors on both ingredients, intersected, page-cited recipes.
```

### 5. The student (a 1,099-page economics textbook)

> **Intent:** "Studying for an exam. I need how concepts build on each other — what to grasp
> before a topic — which policies affect which sectors, and which institution administers what."

Textbook lens: `concept`/`indicator`/`policy`/`scheme`/`institution`, `depends_on` /
`administered_by` / `affects` edges.

```
You:  What do I need to understand before tackling monetary policy transmission?
      → the depends_on subgraph, in study order, page-cited.
```

## The skills (what each does)

| skill | what it does |
|---|---|
| `/explainer:setup` | The full ingest pipeline: elicit intent → induce lens → critique → deterministic primitives → schema-guided LLM extraction → entity resolution → report |
| `/explainer:induce-lens` | Just the lens design (the schema), from intent ∩ artifact — induced from your *role/goals*, never from a question list |
| `/explainer:investigate` | Answer a question over the graph — persona-aware, answer-focused or multi-agent deep-dive, returns cited claims (or an honest abstention) |
| `/explainer:extract` | Targeted extraction for entity types the patterns can't get (quotes, costumes, events) |
| `/explainer:wiki` | Synthesize grounded wiki docs from the graph and index them back (the flywheel) |
| `/explainer:test-lens-induction` | The quality loop: induce a lens blind, score it against a domain rubric — for tuning the induction prompt |

## Direct CLI (secondary; the primary UX is Claude Code)

```
explainer ingest ./path --workspace myproj
explainer status --workspace myproj
explainer search "covenant" --workspace myproj
```

## Design notes

- **Lens = TBox, graph = ABox** (description-logic framing): the lens is a frozen, versioned
  schema; the graph holds the instances. Types anchor to a small upper spine
  (`agent · object · place · information_object · event · role · quality · time · relationship`)
  so graphs stay joinable across corpora, with optional soft references to standard vocabularies
  (schema.org, SKOS, PROV).
- **Claims, not facts:** every edge carries source, confidence, method, and an `asserted` flag —
  doc-drift (a doc that no longer matches the code) is representable, citable, and not "true."
- **Deterministic primitives are accelerators, not the spine.** The schema-guided LLM extraction
  pass is the universal mechanism — point the engine at an artifact type it has never seen and it
  still produces a typed graph; the pattern primitives just make structured artifacts cheaper and
  sharper.
- **Cost shape:** ingest is one-time and front-loaded; query cost is small and independent of
  corpus size. The trade pays off when a corpus is large and queried repeatedly.

## Development

```
uv sync
uv run --with pytest pytest -q     # 51 tests
```

`src/explainer/` — store, lens registry, primitives, ingestors, query, MCP server.
`skills/` — the pipeline prompts ("the soul").
`tests/` — unit tests for the store, primitives, lenses, resolution, provenance.

## License

MIT
