"""Synthesis — THE WEDGE.

Resolve entities across artifacts and emit typed, confidence- + provenance-bearing
**cross-source edges** — the connective tissue plain repo-chat tools lack.

v1 resolution:
  - **exact**: a doc/pdf mention whose surface equals a code symbol name (conf 0.7).
  - **fuzzy**: same after normalization (strip `_`/`-`/space, lowercase) — catches
    snake_case ↔ camelCase ↔ PascalCase, e.g. `verify_jwt` ≈ `verifyJwt` (conf 0.5).
  Edges are `doc_describes_code`, cross_source=1, with provenance (contributing chunks).
  Idempotent: clears prior cross-source edges for the workspace before rebuilding.

TODO (richer wedge): structural inference (HTTP URL ↔ route, env var ↔ config),
LLM-assist for ambiguous cases (Claude Code resolves the residue), confidence
calibration, code↔code cross-repo edges.
"""
from __future__ import annotations

import json
import re


def _norm(s: str) -> str:
    return re.sub(r"[_\s-]+", "", s).lower()


def resolve_workspace(conn, workspace: str) -> int:
    """Run the synthesis pass for a workspace. Returns # cross-source edges created."""
    # Rebuild cleanly (idempotent across re-ingests).
    conn.execute(
        "DELETE FROM edges WHERE workspace=? AND edge_type='doc_describes_code'",
        (workspace,),
    )

    # Code symbols actually defined in code artifacts.
    code_syms = conn.execute(
        """
        SELECT DISTINCT e.id AS eid, e.name AS name, m.chunk_id AS chunk
        FROM entities e
        JOIN mentions m ON m.entity_id = e.id
        JOIN chunks c   ON c.id = m.chunk_id
        JOIN artifacts a ON a.id = c.artifact_id
        WHERE e.workspace = ? AND e.etype = 'symbol' AND a.kind = 'code'
        """,
        (workspace,),
    ).fetchall()

    by_exact: dict[str, dict] = {}
    by_norm: dict[str, dict] = {}
    for r in code_syms:
        by_exact.setdefault(r["name"], r)
        by_norm.setdefault(_norm(r["name"]), r)

    # Mentions found in docs/pdf prose.
    doc_mentions = conn.execute(
        """
        SELECT e.id AS eid, e.name AS name, m.chunk_id AS chunk, a.kind AS akind
        FROM entities e
        JOIN mentions m ON m.entity_id = e.id
        JOIN chunks c   ON c.id = m.chunk_id
        JOIN artifacts a ON a.id = c.artifact_id
        WHERE e.workspace = ? AND a.kind IN ('docs', 'pdf')
        """,
        (workspace,),
    ).fetchall()

    created = 0
    seen: set[tuple[int, int]] = set()
    for r in doc_mentions:
        name = r["name"]
        match, method, conf = None, None, None
        if name in by_exact:
            match, method, conf = by_exact[name], "exact", 0.7
        elif len(_norm(name)) >= 4 and _norm(name) in by_norm:
            match, method, conf = by_norm[_norm(name)], "fuzzy", 0.5
        if match is None:
            continue
        key = (r["eid"], match["eid"])
        if key in seen:
            continue
        seen.add(key)
        provenance = json.dumps({
            "name": name,
            "code_symbol": match["name"],
            "doc_chunk": r["chunk"],
            "code_chunk": match["chunk"],
            "doc_kind": r["akind"],
        })
        conn.execute(
            """
            INSERT INTO edges(workspace, src_id, dst_id, edge_type, cross_source,
                              confidence, method, provenance)
            VALUES (?,?,?,?,1,?,?,?)
            """,
            (workspace, r["eid"], match["eid"], "doc_describes_code", conf, method, provenance),
        )
        created += 1
    return created
