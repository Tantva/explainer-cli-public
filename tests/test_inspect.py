"""inspect: evidence for lens selection."""
from pathlib import Path

from explainer.inspect import inspect_artifact


def test_inspect_directory(tmp_path: Path):
    (tmp_path / "a.py").write_text("def f(): pass\n")
    (tmp_path / "b.rs").write_text("fn g() {}\n")
    (tmp_path / "README.md").write_text("# hi\n")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "junk.py").write_text("ignored\n")

    r = inspect_artifact(str(tmp_path))
    assert r["kind"] == "directory"
    assert r["file_count"] == 3  # .venv ignored
    assert ".py" in r["extensions"] and ".rs" in r["extensions"]


def test_inspect_file(tmp_path: Path):
    f = tmp_path / "notes.txt"
    f.write_text("the quick brown fox" * 5)
    r = inspect_artifact(str(f))
    assert r["kind"] == "file"
    assert r["ext"] == ".txt"
    assert "quick brown fox" in r["sample_text"]


def test_inspect_missing(tmp_path: Path):
    assert "error" in inspect_artifact(str(tmp_path / "nope"))
