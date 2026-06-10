"""Persistent knowledge artifacts (ADR-028): render an investigation into a
standalone, good-looking **HTML** document with **mermaid** diagrams.

Two pieces:
- ``mermaid_bindings`` — a deterministic flowchart of the workspace's cross-repo
  connections (the wedge), straight from the binder. The agent embeds this.
- ``render_html`` / ``write_artifact`` — turn the agent's composed markdown
  (narrative + citations + ```mermaid blocks) into a single self-contained .html
  file (mermaid.js from CDN, clean print-friendly CSS). No server, just open it.

The narrative + synthesis is the agent's job; this module is the deterministic
rendering + the one diagram the engine can draw on its own.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from . import store
from .query import connections

ARTIFACT_ROOT = Path.home() / ".explainer" / "artifacts"


# ------------------------------------------------------------------ mermaid (engine-drawn)

def _safe(label: str) -> str:
    return label.replace('"', "'").replace("`", "'").replace("\n", " ").strip()


def _repo_of(path: str, roots: list[str]) -> str:
    best = ""
    for r in roots:
        if path.startswith(r) and len(r) > len(best):
            best = r
    return Path(best).name if best else "external"


def mermaid_bindings(workspace: str, cross_repo_only: bool = True, db=store.DEFAULT_DB) -> str:
    """A mermaid flowchart of the workspace's structural connections: artifacts as
    nodes grouped into per-repo subgraphs, bindings as labeled edges. This is the
    'connective tissue' picture — engine-drawn, always faithful to the bindings."""
    conn = store.connect(db)
    roots = store.list_sources(conn, workspace)
    conn.close()
    conns = connections(workspace, cross_repo_only=cross_repo_only, db=db)
    if not conns:
        return "flowchart LR\n  empty[\"no connections found\"]"

    ids: dict[str, str] = {}
    repos: dict[str, list[str]] = {}

    def node(path: str) -> str:
        if path not in ids:
            nid = f"n{len(ids)}"
            ids[path] = nid
            repo = _repo_of(path, roots)
            repos.setdefault(repo, []).append(nid)
        return ids[path]

    lines = ["flowchart LR"]
    edges = []
    for c in conns:
        cn, sn = node(c["client_path"]), node(c["server_path"])
        label = _safe(f'{c["kind"]} {c["key"]}')
        style = "==>" if c.get("cross_repo") else "-->"
        edges.append(f'  {cn} {style}|"{label}"| {sn}')
    # subgraphs (one per repo) with friendly file-name labels
    name_of = {nid: Path(p).name for p, nid in ids.items()}
    for repo, nids in repos.items():
        lines.append(f'  subgraph {re.sub(r"[^A-Za-z0-9_]", "_", repo)}["{_safe(repo)}"]')
        for nid in nids:
            lines.append(f'    {nid}["{_safe(name_of[nid])}"]')
        lines.append("  end")
    lines.extend(edges)
    lines.append("  classDef x stroke-width:2px;")
    return "\n".join(lines)


# ------------------------------------------------------------------ markdown → standalone HTML

_CSS = """
:root { --fg:#1c1e21; --muted:#65676b; --accent:#2563eb; --line:#e3e6ea; --bg:#fff; --code:#f5f6f8; }
* { box-sizing:border-box; }
body { font:16px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
  color:var(--fg); background:#f0f2f5; margin:0; }
.page { max-width:860px; margin:32px auto; background:var(--bg); border:1px solid var(--line);
  border-radius:12px; box-shadow:0 1px 3px rgba(0,0,0,.06); }
header { padding:28px 40px 20px; border-bottom:1px solid var(--line); }
header .eyebrow { color:var(--accent); font-weight:600; font-size:13px; letter-spacing:.04em; text-transform:uppercase; }
header h1 { margin:6px 0 4px; font-size:26px; line-height:1.25; }
header .meta { color:var(--muted); font-size:13px; }
main { padding:24px 40px 40px; }
main h2 { font-size:20px; margin:28px 0 10px; padding-bottom:6px; border-bottom:1px solid var(--line); }
main h3 { font-size:16px; margin:20px 0 8px; }
a { color:var(--accent); text-decoration:none; } a:hover { text-decoration:underline; }
code { background:var(--code); padding:1px 5px; border-radius:4px; font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace; }
pre { background:var(--code); padding:14px 16px; border-radius:8px; overflow:auto; }
pre code { background:none; padding:0; }
blockquote { margin:14px 0; padding:8px 16px; border-left:3px solid var(--accent); background:#f7f9ff; color:#333; }
table { border-collapse:collapse; width:100%; margin:14px 0; font-size:14px; }
th,td { border:1px solid var(--line); padding:7px 10px; text-align:left; vertical-align:top; }
th { background:#f7f8fa; }
.mermaid { margin:18px 0; text-align:center; }
.cite { color:var(--muted); font-size:13px; }
footer { padding:16px 40px 28px; color:var(--muted); font-size:12px; border-top:1px solid var(--line); }
@media print { body{background:#fff;} .page{border:none; box-shadow:none; margin:0; max-width:none;} }
"""

_TPL = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{css}</style></head>
<body><div class="page">
<header>
  <div class="eyebrow">Tantva · cross-artifact investigation</div>
  <h1>{title}</h1>
  <div class="meta">{subtitle}</div>
</header>
<main>{body}</main>
<footer>Generated by the Tantva explainer · {ts}</footer>
</div>
<script type="module">
  import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
  mermaid.initialize({{ startOnLoad:true, theme:'neutral', securityLevel:'loose' }});
</script>
</body></html>"""


def render_html(title: str, markdown_body: str, subtitle: str = "") -> str:
    """Render agent-composed markdown (may contain ```mermaid fences) into a single
    self-contained HTML string. Mermaid blocks are passed through raw (not escaped)
    so the client-side library renders them as diagrams."""
    from markdown_it import MarkdownIt

    # Pull mermaid fences out before markdown escaping; restore as raw <div>s after.
    blocks: list[str] = []

    def _stash(m: re.Match) -> str:
        blocks.append(m.group(1).strip())
        return f"\n\nMERMAIDBLOCK{len(blocks) - 1}\n\n"

    src = re.sub(r"```mermaid\s*\n(.*?)```", _stash, markdown_body, flags=re.S)

    md = MarkdownIt("commonmark", {"html": False, "linkify": True}).enable("table")
    html = md.render(src)
    for i, code in enumerate(blocks):
        html = html.replace(f"<p>MERMAIDBLOCK{i}</p>", f'<div class="mermaid">\n{code}\n</div>')

    return _TPL.format(
        title=_safe(title), css=_CSS, body=html,
        subtitle=subtitle or "", ts=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )


def write_artifact(workspace: str, title: str, markdown_body: str,
                   subtitle: str = "", db=store.DEFAULT_DB) -> str:
    """Render + write a knowledge artifact to disk; return the file path."""
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "artifact"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = ARTIFACT_ROOT / f"{workspace}-{slug}-{stamp}.html"
    out.write_text(render_html(title, markdown_body, subtitle), "utf-8")
    return str(out)
