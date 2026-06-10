# explainer-cli — build context

Tantva v1: a local **cross-artifact knowledge-investigation** tool driven by the user's installed **Claude Code** (ADR-033). Ingest code + docs + PDFs; synthesize cross-source connections; answer cited questions. The wedge is **synthesis** (entity resolution + cross-source edges) — build it well; everything else is plumbing.

Design home / ADRs: `~/workspace/tantva` (this is the *code* repo; that is the *spec* repo). ADR-033 = this plan; ADR-032 = the v2 managed-AWS architecture this engine ports to.

## Principles
- **Buy > build.** Reuse libraries (tree-sitter, PyMuPDF, markdown-it, the `mcp` SDK, SQLite). Hand-write only the synthesis logic — the moat.
- **Claude Code is the LLM.** The engine does deterministic ingest + retrieval + graph; the live Claude Code session does the reasoning/synthesis via MCP tools. No model API calls in the engine for v1.
- **Retrieval = semble** (ADR-002, now realized): Model2Vec embeddings + BM25 + RRF + code-aware reranking over the workspace's source roots (code, docs, config). CPU-only, disk-cached. **PDFs**: our layer extracts each page to a `.md` under `~/.explainer/derived/<ws>/` (registered as a semble source), so PDF text is semantically searchable too; results are mapped back to the original PDF + page for citation. Keyword search is the fallback when semble is absent. The graph + synthesis stay ours (the wedge). Supersedes ADR-033's "defer embeddings" note — semble gives embeddings for free (buy > build). Embedding model: default **`minishlab/potion-retrieval-32M`** — MinishLab's best static retrieval model (picked because docs/PDFs rely wholly on embeddings while code is also graph-backed). Override via **`EXPLAINER_MODEL`** (any Model2Vec HF id, or a local model dir).

## Architecture (this package)
- `store.py` — SQLite schema: workspaces, artifacts, chunks, entities, edges.
- `ingest.py` — artifact-type router → code (tree-sitter) / docs (markdown) / pdf (PyMuPDF) → chunks + entities.
- `synthesis.py` — **the wedge**: resolve entities across artifacts; emit typed cross-source edges with `confidence` + `provenance`. Heuristic-first; LLM-assist deferred.
- `query.py` — retrieval + workspace helpers (search, cross_edges, overview, list_workspaces, list_artifacts) used by the MCP tools.
- `retriever.py` — semble content-retrieval wrapper (guarded; keyword fallback).
- `mcp_server.py` — FastMCP server exposing the tools to Claude Code.
- `cli.py` — direct CLI (`explainer ingest/ask/status`).

## Packaging
- Claude Code **plugin**: `.claude-plugin/plugin.json` + `.mcp.json` (MCP server via `uv run`) + `skills/` (auto-discovered) + `.claude-plugin/marketplace.json` (repo is its own marketplace).
- MCP server launches with `uv run --project ${CLAUDE_PLUGIN_ROOT} explainer-mcp` (uv resolves deps on first run).

## Conventions
- Python ≥3.11, `uv` for env/run. `typer` CLI, `mcp` (FastMCP) server.
- Never commit ingested corpora or `.db` files (see `.gitignore`).
- Keep tool outputs token-efficient (Claude Code reads them) — return structured, citation-ready records, not raw dumps.
