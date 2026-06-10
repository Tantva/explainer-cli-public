---
description: Targeted extraction for entity types the cheap gazetteer can't produce — non-proper-noun things like quotes/epigraphs, costumes/objects, events. The session retrieves the relevant passages and writes typed nodes/relations into the same graph.
---

# Targeted extraction

The lens's gazetteer finds recurring **proper nouns** (characters, places, houses, factions). It cannot find things that aren't capitalized names: **quotes/epigraphs**, **costumes/objects**, **events**, **emotions**, typed **relationships** (betrayals, alliances). When the user's intent asks for one of those, run a targeted pass — you (the session) are the extractor; the engine gives you the read and write doors.

This is the "generous at ingest" pass: bounded, but real LLM work. Do it once at ingest, so query stays cheap.

## Flow — for each target type the gazetteer can't fill

1. **Retrieve the slice, don't read the book.** `search(workspace, <terms that surface this type>)` — e.g. costumes → `"stillsuit robe cloak cape uniform wore wearing garment"`; epigraphs/quotes → `"epigraph from the writings of by the Princess quote saying"` (or the known structural cue). Pull `k=10–20`. Optionally `get_chunk` for fuller context.
2. **Extract structured items** from the returned passages — the actual costume nouns, the actual quote text + who said/wrote it. Use your judgment; this is the work.
3. **Write nodes** — `add_entity(workspace, name, etype, props)`:
   - a quote → `etype="quote"`, `props={"text": "...", "speaker": "...", "page": N}` (name = a short slug or the line).
   - a costume → `etype="costume"`, `props={"description": "...", "page": N}`.
4. **Wire relations** — `add_relation(workspace, src, dst, relation, props)` to connect to existing entities:
   - `add_relation("Paul", "stillsuit", "wears")`, `add_relation("Princess Irulan", "<quote>", "wrote")`.
   - Add the character/source as an entity first if it isn't already in the graph.
5. **Cite.** Every extracted node carries its `page` (and/or `text`) in `props`, so the answer can quote and locate it.

## Rules
- **Bounded, not exhaustive.** Retrieve the relevant passages and extract from those — don't try to read all N pages. Generous where the intent points, quiet elsewhere.
- **Ground everything.** No quote without its text + page; no costume without a passage. Unsourced extractions are worse than omissions.
- These land in the same `entities`/`edges` store, so `entities(etype="costume")` and `neighbors("Paul", etype="costume")` become first-class immediately — same as any gazetteer type.
- Report domain-facing ("found 14 costumes, 22 epigraphs"); never surface the machinery.
