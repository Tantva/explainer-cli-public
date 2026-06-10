"""Direct CLI. Primary UX is via Claude Code + the MCP server; this is for
ingestion, inspection, and quick checks.
"""
from __future__ import annotations

import json
from pathlib import Path

import typer

app = typer.Typer(add_completion=False, help="Tantva explainer — cross-artifact knowledge investigation.")


@app.command()
def create(name: str):
    """Create (set up) a workspace."""
    from .query import create_workspace
    typer.echo(json.dumps(create_workspace(name), indent=2))


@app.command()
def workspaces():
    """List configured workspaces with artifact counts."""
    from .query import list_workspaces
    typer.echo(json.dumps(list_workspaces(), indent=2))


@app.command()
def artifacts(workspace: str = typer.Option("default", "--workspace", "-w")):
    """List artifacts ingested in a workspace."""
    from .query import list_artifacts
    typer.echo(json.dumps(list_artifacts(workspace), indent=2))


@app.command()
def ingest(
    path: Path,
    workspace: str = typer.Option("default", "--workspace", "-w"),
):
    """Ingest a corpus (code repo, docs, PDFs) into a workspace, then synthesize."""
    from .ingest import ingest_path
    typer.echo(json.dumps(ingest_path(path, workspace), indent=2))


@app.command()
def status(workspace: str = typer.Option("default", "--workspace", "-w")):
    """Show what's in a workspace."""
    from .query import overview
    typer.echo(json.dumps(overview(workspace), indent=2))


@app.command()
def search(query: str, workspace: str = typer.Option("default", "--workspace", "-w"), k: int = 8):
    """Keyword search over chunks."""
    from .query import search as _search
    typer.echo(json.dumps(_search(workspace, query, k), indent=2))


@app.command()
def edges(name: str, workspace: str = typer.Option("default", "--workspace", "-w")):
    """Show cross-source edges touching an entity (the wedge)."""
    from .query import cross_edges
    typer.echo(json.dumps(cross_edges(workspace, name), indent=2))


@app.command()
def connections(
    workspace: str = typer.Option("default", "--workspace", "-w"),
    kind: str = typer.Option(None, "--kind", help="filter: http | topic"),
    cross_repo: bool = typer.Option(False, "--cross-repo", help="only across-repo links"),
):
    """Show structural cross-repo connections (HTTP routes / queue topics)."""
    from .query import connections as _connections
    typer.echo(json.dumps(_connections(workspace, kind, cross_repo_only=cross_repo), indent=2))


@app.command()
def candidates(
    workspace: str = typer.Option("default", "--workspace", "-w"),
    kind: str = typer.Option(None, "--kind", help="filter: http | topic"),
):
    """Show unbound connector endpoints (the LLM-assist worklist)."""
    from .query import binding_candidates
    typer.echo(json.dumps(binding_candidates(workspace, kind), indent=2))


@app.command()
def ask(question: str, workspace: str = typer.Option("default", "--workspace", "-w")):
    """Direct ask (thin). Primary UX: run inside Claude Code, which calls the MCP tools."""
    typer.echo(
        "Direct `ask` is a placeholder. Run explainer inside Claude Code via the MCP "
        "server — Claude Code is the agent and synthesizes the cited answer from the tools.\n"
        f"(workspace={workspace}) Q: {question}"
    )
    # TODO (optional): shell to `claude -p` with retrieved context for a headless answer.


if __name__ == "__main__":
    app()
