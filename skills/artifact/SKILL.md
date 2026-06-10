---
description: Turn an explainer investigation into a polished, standalone HTML knowledge artifact with mermaid diagrams (architecture flow, cross-repo graph) and citations — a persistent document the user can open or print to PDF.
---

# Knowledge artifact

Use this when the user wants a **document / report / write-up / HTML / diagram** out of an investigation — not just a chat answer. It produces a self-contained `.html` (mermaid.js via CDN) they can open in a browser or print to PDF.

## Prime directive

**The artifact is about the user's system — nothing else.** A printed document that talks about the *tool* reads like an advertisement. So:
- No persona / mode / coverage line, no "N-agent fan-out", no binding counts or index stats, no narration of how the synthesizer behaved. Cut any sentence that's about the explainer rather than the user's domain.
- Express uncertainty about **their** system ("the docs may not document this path"), never about **ours** ("our synthesizer mis-linked it").
- The title and sections name *their* domain, not our process.

## Flow

1. **Investigate first.** If you haven't already gathered the evidence, run the `investigate` loop (pick persona + mode) so you have grounded, cited claims to write from. The artifact is only as good as the investigation behind it — never write claims you didn't ground with a tool.

2. **Get the diagram(s).**
   - `export_graph(workspace, cross_repo_only=true)` → a **mermaid** flowchart of the cross-repo connections (engine-drawn, always faithful to the bindings). Use `cross_repo_only=false` to show intra-repo wiring too.
   - You may also hand-author additional `mermaid` diagrams (a sequence diagram of a flow, a tree of a call graph) — but anything asserting a *connection* should trace back to a tool result.

3. **Compose the markdown.** Write the document body as markdown. Shape it for the persona (architect → impact list; onboarding → narrative trace; docs → drift table). Include:
   - the question + persona/mode/coverage line,
   - the diagram(s) inside ```mermaid fences,
   - a **citations table** (`repo/path:line` for each hop/claim),
   - honest **gaps** (low-confidence or unverified links — say so).

4. **Render.** `render_artifact(workspace, title, markdown, subtitle)` → returns the `.html` path. Tell the user the path and that they can open it (`open <path>`) or print to PDF. On macOS you may offer to open it.

## Rules

- **Every claim in the artifact carries a citation.** A persistent document with an unsourced claim is worse than no document — it looks authoritative and isn't. Demote anything you couldn't ground to a "gaps / to verify" section.
- **Diagrams must match the bindings.** Prefer `export_graph` over hand-drawing connection edges; if you draw your own, every edge must correspond to a real binding/edge/chunk you retrieved.
- Keep it readable: lead with the answer and the diagram, then the evidence. Don't paste raw tool JSON.
