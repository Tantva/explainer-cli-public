---
description: Set up Tantva and ingest a corpus into a typed knowledge graph. Drives the ADR-036 pipeline — induce a per-corpus lens (schema), critique it against the questions, run the lens's deterministic primitives, then the universal schema-guided LLM-extraction pass, then entity resolution. Works on ANY artifact (code, prose, contracts, textbooks, screenplays, and types you've never seen).
---

# Ingest — build the knowledge graph (the engine's "soul")

You are the **ingest runtime**. Your job is to turn a corpus into a **typed, cited knowledge graph**
shaped by *what the user wants to ask*. The engine is a generic property-graph store + a kit of
extraction primitives; **you supply the judgment** — what types matter, which primitives fit, and the
schema-guided extraction that deterministic code can't do. Never expose the machinery (lens names,
primitive names, "fan-out") to the user; report only a friendly, domain-facing summary.

**The one rule that makes this general (ADR-036):** the graph is built primarily by **schema-guided
LLM extraction** — *you*, reading chunks and writing typed nodes/edges per the induced schema. The
deterministic primitives are **opt-in accelerators** for artifacts that match them; they are never
required. A corpus type you've never seen must still get a real graph from the extraction pass alone.

Confirm the tools exist first (`create_workspace`, `set_intent`, `inspect`, `list_lenses`, `get_lens`,
`register_lens`, `ingest`, `chunks`, `get_chunk`, `pending_entities`, `classify_entities`, `add_entity`,
`add_relation`, `resolve_entities`, `merge_entities`, `search`, `entities`, `neighbors`, `overview`,
`list_artifacts`). If missing: `/plugin install explainer@explainer-cli` then `/reload-plugins`.

---

## 1. Workspace + intent
`create_workspace(name)` (one per project). Then establish **intent — what will they ASK?** This shapes
the whole lens (the artifact says what's *possible*; the intent says what's *wanted*; the lens is the
intersection). If they've already said, use it; else ask once ("what kinds of questions do you want to
answer about this?"). Record it: `set_intent(workspace, "<their questions, in their words>")`.

## 2. Inspect — on evidence, not the filename
`inspect(path)` for the shape, **and read 3–8 representative chunks** (open a few files / pages / sections
via `inspect` or, after a probe ingest, `chunks`). You are grounding the schema in what the artifact
*actually contains*, not a guess. Note its structure (sections? sluglines? definitions? code?).

## 3. Induce the lens (the schema = a TBox) — see the **`induce-lens`** skill
`list_lenses()`. If a seed lens genuinely fits (a code repo → `code`; a plain narrative → `prose`), use
it. Otherwise **induce one** via the `induce-lens` skill — derive it from the **user's INTENT** (their
elicited role/goals, via `set_intent`) ∩ the *artifact*. **Induce from intent, never from a list of
specific questions** — a lens shaped to known questions is useless in practice and is teaching-to-the-test.
- **entity_types** ← the *kinds of things the intent's domain is about* (e.g. `defined_term`, `party`,
  `clause`, `scene`, `concept`, `scheme`, `institution`).
- **relation_types** ← the *links the intent's domain reasons over* (`uses_term`, `references`,
  `obligates`, `depends_on`, `administered_by`, `shares_scene`).
- **properties** ← the measures (`section`, `page`, `threshold`, `first_appearance`).
- **`parents`** ← anchor EVERY type to one upper-spine category (`agent · object · place ·
  information_object · event · role · quality · time · relationship`) so the graph joins across corpora.
- **`aligns`** ← optionally soft-reference a standard term (`schema:Person`, `skos:Concept`,
  `prov:wasDerivedFrom`) — a reference string, not an import.
- **`extractors`** ← compose the pipeline (next).

`register_lens(name, description, schema)` (frozen; pick a fresh descriptive name like
`legal-credit-agreement`). The induced schema is a **draft, not truth** — that's what step 4 is for.

### Composing `extractors` — general core + opt-in accelerators
Always include the **general core**; add deterministic accelerators **only if the artifact matches them**:

| if the artifact has… | add this accelerator |
|---|---|
| numbered sections / sluglines / chapters / headings | `{"use":"structural-markers","preset":"section|slugline|chapter","etype":"…"}` |
| explicit definitions ("X" means …) | `defined-term-pattern` (config `etype`) |
| lowercase/domain terms (ingredients, concepts) | `{"use":"salient-terms","etype":"…"}` |
| recurring proper nouns (characters, parties) | `{"use":"recurring-proper-nouns","etype":"…"}` |
| internal references (Section 9.1, see Ch. 3) | `cross-reference` (after structural-markers) |
| source code | `ast-callgraph` |
| services that call routes / produce-consume topics | `structural-binding` |
| entities that share a unit (scene/recipe/section) | `co-occurrence` |

**Always-on (the general core):** `llm-extract` (and/or `llm-relations`) for the typed relations and
non-obvious entities no regex can get, plus `alias-merge` (run via step 7). Example for a credit
agreement: `["defined-term-pattern", {"use":"structural-markers","preset":"section","etype":"section"},
"cross-reference", "llm-relations", "co-occurrence"]`.

## 4. Critique the lens BEFORE ingesting (don't trust the draft)
Check, and revise if needed:
- **Coverage:** does every intended question map to an `entity_type` or `relation_type`? If a question
  has no home in the schema, add the type.
- **Extractability:** is each declared type actually present in the chunks you sampled? Drop types the
  artifact doesn't support; don't invent a `faction` for a book that has none.
- **Anchoring:** every type has a spine `parent`.
(This step exists because LLM-induced schemas are *not* reliably right — validate, don't assume.)

## 5. Ingest
`ingest(path, workspace, lens=<name>)` — chunks the corpus (section/scene-aware) and runs the lens's
**deterministic** primitives. Code/prose seeds: omit `lens`. The result lists what ran; `skill_extractors`
names the LLM passes you must run next.

## 6. Type the provisional entities
Surfacers (`salient-terms`, `recurring-proper-nouns`) leave **provisional** entities. `pending_entities` →
classify each into a lens `entity_type` or **`drop`** (noise: fragments, sentence-start words) →
`classify_entities`. Cheap, and it's what makes "list the X" a clean query.

## 7. Schema-guided LLM extraction — THE CORE PASS (the differentiator)
This is where any artifact gets its real graph, and where the relations live. **Fan out subagents over
the chunks** and extract per the schema:
1. Page through `chunks(workspace, kind=…)` in batches; for a batch, `get_chunk` for full text as needed.
2. **Spawn a subagent per batch** (Agent/Task tool). Give it the lens schema (entity_types,
   relation_types, properties) and a tight brief: *extract every typed entity, relation, and property the
   schema defines that appears in these chunks; write them with `add_entity` / `add_relation`; cite the
   chunk's locator in props; set `asserted=False` for a claim the text reports but another source
   contradicts.*
3. **Model-tier the fan-out:** use a cheap/fast model for bulk typing and obvious entities; reserve a
   stronger model for relation extraction and judgment calls. (Bulk classify can also go through a fast
   model; relations need the better one.)
4. Keep it bounded and grounded: extract only what the schema asks for, only what's in the text, always
   with a citation. No ungrounded claims.

This is "generous at ingest," done once. It is the universal mechanism — even with zero deterministic
primitives, this pass alone produces a typed graph.

## 8. Entity resolution (fusion — don't skip)
`resolve_entities(workspace)` — collapses alias surface forms into canonical nodes (deterministic
normalization + embeddings). Then **confirm the hard ones yourself**: scan `entities(etype=…)` for
surface forms the same person/thing ("Sunja" / "Madam Baek"; "the Borrower" / "Borrower") that automated
resolution missed, and `merge_entities(workspace, keep, drop=[…])`. Resolution is mandatory — unresolved
aliases inflate every count and ranking.

## 9. Confirm + report
`overview(workspace)` + `list_artifacts(workspace)`. Report **domain-facing only**: *"indexed the credit
agreement — 312 defined terms, 84 sections, 540 cross-references, parties and their covenants."* Never
surface lens/primitive names or the pipeline.

## 10. Optional: wiki + investigate
For a standing knowledge base, hand to the **`wiki`** skill (synthesize grounded docs, index them back).
To answer questions, hand to **`investigate`** (it picks persona/mode and returns a cited contract). Pass
along the recorded intent so it needn't re-ask.

---

### Discipline (non-negotiable)
- **The schema is induced and validated, never assumed** (step 4). A wrong schema propagates.
- **Every extracted node/edge carries its source** — a chunk locator in props. Unsourced = not a claim.
- **Deterministic primitives are optional accelerators; the LLM extraction pass is the backbone.** If the
  artifact matches none of the accelerators, you still get a full graph from step 7.
- **Resolution is part of ingest, not an afterthought.**
- **Ingest cost is one-time and front-loaded** (it amortizes over every future query) — spend it
  generously on exactly the types/relations the questions need; don't gold-plate the rest.
- **Machinery stays invisible.** The user sees their domain, never the engine.
