"""The hard gate must inspect every Python file this repository owns.

A lint exclusion is the cheapest way to turn a red gate green without fixing anything, so the
scope of `ruff check .` is itself under test. Only the vendored upstream skill copies under
`.agents/skills/` may be excluded; anything else is repo-owned source and must be linted.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

VENDORED_PREFIX = ".agents/skills/"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _ruff_config() -> dict[str, object]:
    config = tomllib.loads((_repo_root() / "pyproject.toml").read_text())
    tool = config["tool"]
    assert isinstance(tool, dict)
    ruff = tool["ruff"]
    assert isinstance(ruff, dict)
    return ruff


def _tracked_python_files() -> set[str]:
    listed = subprocess.run(
        ["git", "ls-files", "-z", "*.py"],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
    )
    if listed.returncode != 0:
        # scripts/rename_fork_selftest.py copies the tree without .git and runs the whole
        # gate on that copy. "what this repository owns" is a property of the repository,
        # so there is nothing to assert on a detached copy. Skipping keeps that run honest
        # rather than failing it on a missing index.
        pytest.skip("not a git work tree, so there is no tracked-file list to check")
    return {name for name in listed.stdout.split("\0") if name}


def _linted_python_files() -> set[str]:
    shown = subprocess.run(
        [sys.executable, "-m", "ruff", "check", ".", "--show-files"],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    root = _repo_root()
    files = set()
    for line in shown.splitlines():
        path = Path(line.strip())
        if path.suffix == ".py":
            files.add(path.relative_to(root).as_posix())
    return files


def test_ruff_excludes_only_the_vendored_skill_tree() -> None:
    """A blanket `.agents` exclusion would also hide repo-owned tooling added there later."""
    excluded = _ruff_config().get("extend-exclude", [])
    assert isinstance(excluded, list)
    assert excluded, "the exclusion list must stay explicit, not empty-by-accident"
    for entry in excluded:
        assert entry.startswith(VENDORED_PREFIX), (
            f"{entry!r} is broader than the vendored upstream skills; the gate must keep "
            "covering every file this repository owns"
        )


def test_every_repo_owned_python_file_is_linted() -> None:
    unlinted = _tracked_python_files() - _linted_python_files()
    assert unlinted == {
        name for name in _tracked_python_files() if name.startswith(VENDORED_PREFIX)
    }, f"these files are tracked but hidden from `ruff check .`: {sorted(unlinted)}"


def test_the_vendored_tree_holds_no_repo_owned_source() -> None:
    """Vendored means resynced verbatim from the shared agent skills, so nothing here is ours."""
    vendored = _repo_root() / ".agents" / "skills"
    for path in sorted(vendored.rglob("*.py")):
        text = path.read_text()
        assert "model_quality_gate" not in text, (
            f"{path} references this repo's package, so it is not a verbatim upstream copy "
            "and must not be excluded from the gate"
        )
