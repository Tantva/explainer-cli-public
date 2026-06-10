"""Workspace intent: the questions the user wants to ask, stored to shape the lens."""
from pathlib import Path

from explainer.query import set_intent, overview, create_workspace


def test_intent_round_trip(tmp_path: Path):
    db = tmp_path / "e.db"
    create_workspace("w", db=db)
    set_intent("w", "the political factions and who allies with whom", db=db)
    assert overview("w", db=db)["intent"] == "the political factions and who allies with whom"


def test_set_intent_creates_workspace(tmp_path: Path):
    db = tmp_path / "e.db"
    set_intent("fresh", "character arcs", db=db)  # workspace need not pre-exist
    assert overview("fresh", db=db)["intent"] == "character arcs"
