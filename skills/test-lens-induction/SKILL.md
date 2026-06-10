---
description: Verify that intent + the induction prompt produce a GOOD lens. Given a user-context (intent) and a corpus sample, run induce-lens, then score the resulting schema against a hand-authored domain rubric (must-have entity/relation types + domain coverage). A repeatable loop for refining the lens-induction "soul": tweak the prompt → re-run → watch coverage move.
---

# Test lens induction (refine the soul)

This is the feedback loop for the most important and least deterministic part of the engine: does
**intent + the `induce-lens` prompt** produce a lens that covers the domain? The induction is LLM work
(non-deterministic), so this is an eval, not a unit test — but the **scoring is deterministic** given the
induced schema, so prompt changes are directly comparable.

## Inputs (per workspace)
- **`user-context.md`** — the user's intent (role + goals, in their words). **The induction sees ONLY
  this** — never `eval-questions-only.md`. (Seeing the questions would be teaching-to-the-test.)
- **the corpus** — for `inspect` + a few sample chunks.
- **`lens-rubric.md`** — the hand-authored "right lens" spec for this domain: the `must_have` entity_types
  and relation_types a good lens needs, `nice_to_have` ones, and a `domain_areas` list (each area must map
  to ≥1 type/relation). This encodes the judgment of what a good lens looks like — it is the answer key
  for induction.

## Procedure
1. **Induce, blind to the questions.** Read `user-context.md` + `inspect(corpus)` + 3–8 sample chunks.
   Run the **`induce-lens`** skill → get the schema (entity_types, relation_types, properties, parents,
   extractors). Do **not** open `eval-questions-only.md`.
2. **Score deterministically against `lens-rubric.md`:**
   - **entity coverage** = |induced.entity_types ∩ rubric.must_have_entities| / |must_have_entities|
     (allow synonyms — `clause`≈`section`, `borrower`≈`party` — judged generously, but record the mapping).
   - **relation coverage** = same for `must_have_relations`.
   - **domain coverage** = fraction of `rubric.domain_areas` that map to ≥1 induced type/relation.
   - **spine anchoring** = every induced type has a `parent` (pass/fail).
   - **discipline** = no type exists solely to answer one narrow thing; extractors match the artifact shape.
3. **Report a scorecard** → `lens-induction-score.md`:
   ```
   # Lens induction score — <workspace>
   induced: entity_types=[…] relation_types=[…] extractors=[…]
   entity coverage:   X/Y  (missing: …)
   relation coverage: X/Y  (missing: …)
   domain coverage:   X/Z  (uncovered areas: …)
   spine anchored:    yes/no
   verdict: <one line — does this lens serve the domain?>
   ```
4. **Refine:** if coverage is low, the gap tells you what the `induce-lens` prompt failed to elicit. Edit
   `induce-lens/SKILL.md`, reinstall, re-run this test, compare scores. Iterate until coverage is high
   *without* the prompt ever seeing the questions.

## What good looks like
A lens induced from a vague, realistic intent that still covers the domain's must-have types/relations —
so specific, unseen questions in that domain are answerable. **High coverage from intent alone = the
induction prompt generalizes.** Low coverage = the prompt is under-eliciting (or the intent is too thin).

## Honesty
- The induction is non-deterministic; run it 2–3× and report the spread, not a single lucky draw.
- The rubric is a human judgment of "the right lens" — keep it about the *domain*, not the eval questions
  (don't reverse-engineer the rubric from the question list, or you've just moved the leak).
