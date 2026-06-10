---
description: Induce a per-corpus lens (the schema/TBox) from the USER'S INTENT ∩ the ARTIFACT — entity types, relation types, properties, spine anchors, soft-reuse refs, and an extractor composition. The defensible "soul" of Tantva. Induce from what the user said they care about (their role/goals), NEVER from a list of specific questions a grader will ask.
---

# Induce a lens — intent ∩ artifact (the soul)

Turn **(the user's stated intent) ∩ (what the artifact actually contains)** into a lens schema. This is
the heart of the engine — a generic model reasoning *well* about what to index for *this* user on *this*
corpus. Get this right and a single index serves the questions the user will actually ask.

## The cardinal rule: induce from INTENT, not from questions
The lens is shaped by the **user's intent** — their *role and goals in their own words* ("I'm a credit
analyst reviewing covenant risk"; "I'm adapting this novel into a series"). It is **NOT** shaped by a list
of the specific questions someone will later ask. Two reasons:
- **Real usage:** the user states an interest once; the specific questions come later and are not known at
  ingest. A lens that only fits a pre-known question list is useless in practice.
- **Honesty:** shaping the schema to a known question set is teaching-to-the-test — it inflates apparent
  performance and proves nothing about generalization.

So: read the **intent** (the elicited "what do you want to ask of this?" answer / the user's role brief),
read the **artifact**, and design a schema that covers the *domain* the intent implies — broad enough to
answer unseen questions *in that domain*, grounded in what the artifact supports.

## Inputs
1. **Intent** — the user's role + goals (from `set_intent` / the elicitation). If absent, ask once:
   *"What do you want to be able to ask of this?"* — and take a role/goal answer, not a question list.
2. **Artifact evidence** — `inspect(path)` + 3–8 representative chunks. Ground every proposed type in
   something you actually saw; don't invent a `faction` for a book that has none.

## Produce the schema
**Name every type and relation in `snake_case`** (e.g. `defined_term`, `event_of_default`, `uses_term`).
Consistent naming is what lets graphs join across corpora — do not use PascalCase or spaces.

**Prefer the fewest types that cover the domain.** Split a type only if the *intent's domain* would
actually reason over the distinction — don't split `covenant` into `affirmative_covenant`/
`negative_covenant` unless the user cares about that difference. A leaner schema that covers the domain
beats a granular one that over-fits this one artifact.

- **entity_types** ← the *kinds of things* the intent's domain is about (a credit analyst's domain →
  `defined_term`, `covenant`, `event_of_default`, `party`, `section`, `threshold`). Nouns of the domain,
  not of the questions.
- **relation_types** ← the *links* the domain reasons over (`uses_term`, `references`, `obligates`,
  `conditioned_on`, `triggers`). Verbs of the domain.
- **properties** ← the measures worth capturing (`section`, `page`, `value`, `first_appearance`).
- **parents** ← anchor EVERY type to one upper-spine category (`agent · object · place ·
  information_object · event · role · quality · time · relationship`) so the graph joins across corpora.
  Use these worked rules to keep anchoring *consistent* (it's the most common source of drift):
  - a person / organization / actor → **agent**
  - a document, clause, term, section, concept, report → **information_object**
  - a covenant / obligation / condition / requirement (a binding *between* parties) → **relationship**
  - a ratio / threshold / score / margin / measurable attribute → **quality**
  - a default / payment / arrest / arrival / happening → **event**
  - a named position or capacity (Administrative Agent, narrator) → **role**
  - a physical thing or facility → **object** · a location → **place** · a date/period → **time**
- **aligns** ← optionally soft-reference a standard term (`schema:Person`, `skos:Concept`, `prov:*`) —
  a reference string, never an import.
- **extractors** ← the general core (`llm-extract`/`llm-relations` + `alias-merge`) **plus** the
  deterministic accelerators the artifact's *shape* matches (structural-markers if it has sections/
  sluglines; defined-term-pattern if it has `"X" means`; recurring-proper-nouns/salient-terms; etc.).

`register_lens(name, description, schema)` — frozen; fresh descriptive name.

## Self-critique before committing (the lens is a draft, not truth)
Induced schemas are unreliable — validate, don't assume:
1. **Domain coverage:** does the schema span the *whole* intent domain? List the intent's sub-areas; each
   should have a home (a type or relation). A sub-area with no home → add it.
2. **Extractability:** is each declared type actually present in the chunks you sampled? Drop types the
   artifact can't support.
3. **Anchoring:** every type has a spine `parent`.
4. **Not question-shaped:** sanity-check that you induced from the *intent's domain*, not from any specific
   questions you happened to see. If a type exists only to answer one narrow question, it's too narrow.

## Output (also the unit the lens-induction test scores)
Return the registered lens schema. A good lens **covers the intent's domain** such that specific, unseen
questions *in that domain* are answerable from the graph — that is the property the `test-lens-induction`
harness measures (induced types/relations vs. a domain rubric).
