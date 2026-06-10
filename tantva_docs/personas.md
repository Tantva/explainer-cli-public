
# Personas

Tantva is broad by design: one engine over any corpus. The risk of a broad tool is that it feels
unfocused. We answer that two ways:

1. **Breadth is principled, not vague.** Every corpus is indexed through a **lens** into a typed,
   cited graph, not a blob of text. Code becomes a call graph plus cross-repo wiring; a novel
   becomes a character/place/scene graph; a contract becomes a web of defined terms and the
   clauses that depend on them.
2. **Each story stands on its own.** Every persona below maps to a corpus in the evaluation, and
   the claimed win is one the eval actually measured.

The common thread: questions that span the corpus and need connective tissue, not just retrieval.

---

## 1. Priya — staff engineer onboarding to a multi-repo system

**Needs:** to understand how a large system fits together — how services talk, and what breaks if
she changes something.

**Difficulty:** the knowledge is tribal and undocumented. `grep` across repos drowns her in
matches and misses dynamic wiring (a URL built at runtime, a Kafka topic resolved through
config). Nothing shows the cross-repo picture.

**How Tantva helps:** ingest the repos once; the graph holds cross-repo route/topic bindings, the
call graph, and doc↔code links, so a single question returns a cited, cross-repo trace.

> *From the eval (Sentry, six repos):* "How does an event get from the SDK to ClickHouse?" — a
> five-hop trace across `sentry-python → relay → snuba`, each hop cited `repo/file:line`. One
> agent and ~63 tool calls, where the same model reading from scratch used 39 agents and 818.

## 2. Alex — credit analyst working a contract

**Needs:** before a refinancing: what the covenants require, what triggers a default, and how the
defined terms interlock — for any term, what relies on it.

**Difficulty:** a credit agreement is a web of definitions. Amending one definition silently moves
ratios and baskets elsewhere in the document; assembling that blast radius by reading means
re-scanning 93k words per term, and it is easy to get wrong.

**How Tantva helps:** the legal lens extracts every defined term with its definition, wires
section cross-references and term-dependency (`uses_term`) edges, and resolves aliases
("the Borrower" / "Borrower"). Blast radius becomes one graph call.

> *From the eval:* Tantva found all six consumers of a changed defined term where the
> read-everything baseline found three — and the baseline confidently inverted the contract's
> default-cure logic, while the graph's covenant→default edges got it right.

## 3. Sam — screenwriter adapting a novel

**Needs:** the cast and how central each character is, who shares scenes with whom, the arcs
across the whole book — to decide what to cut, merge, and dramatize.

**Difficulty:** a 500-page cast doesn't fit in a mental map, and characters go by multiple names
(maiden name, married name, honorific). Text search counts strings, not people, so every census
and ranking is silently wrong.

**How Tantva helps:** the prose lens builds the character/place/scene graph; entity resolution
collapses each character's surface forms into one node, so presence rankings and co-occurrence
are real.

> *From the eval (Pachinko):* the baseline string-counted a family census (9 vs the true 10–12)
> and ranked first appearances by first mention; the alias-resolved graph got both right.

## 4. Dr. Rao — researcher over an unfamiliar domain corpus

**Needs:** structured investigation of a corpus (reports, textbooks, mixed sources) where the
right way to index isn't known up front.

**Difficulty:** off-the-shelf RAG returns passages, not typed relationships ("what depends on
what," "who administers what"). Building a bespoke extraction pipeline per domain is weeks of
engineering.

**How Tantva helps:** intent-driven lenses. State your role and goals; the system induces a
schema (entities, relations, properties) for that domain, registers it, and extracts into it —
deterministically where the artifact has structure, with a schema-guided LLM pass everywhere
else. The artifact constrains what's possible; your intent decides what's built. The induced
schema is validated before ingest and must generalize to questions you haven't asked yet.

## 5. Maya — docs / knowledge-management owner

**Needs:** to keep documentation aligned with the system it describes, and to catch drift before
it misleads people.

**Difficulty:** docs go stale silently. Nothing links what the doc claims to what the code does.

**How Tantva helps:** the synthesis pass emits doc↔code edges with confidence and provenance —
where a doc describes a symbol, and where it no longer matches. Drift becomes a first-class,
cited finding. (On the Sentry corpus, Tantva flagged that an authoritative ingest doc had been
mis-linked to a test fixture by its own synthesizer — it surfaced its own weak spot, with
evidence.)

---

## Why one tool, not five

Priya, Alex, Sam, Dr. Rao, and Maya would otherwise reach for five different point tools. Tantva
serves all five from one generic property-graph store, a lens registry, and the user's Claude
Code as the reasoning engine. The lens is what makes breadth principled: it turns "index
anything" into "index this domain into a typed, cited graph shaped by what this user needs."
