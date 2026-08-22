from __future__ import annotations

import argparse
import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("scripts/rename_fork.py")
SPEC = importlib.util.spec_from_file_location("rename_fork", SCRIPT)
assert SPEC and SPEC.loader
rename_fork = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rename_fork)


def _args(**overrides: str) -> argparse.Namespace:
    values = {
        "package": "bank_model_gate",
        "cli": "bank-quality",
        "service": "bank-model-risk",
        "distribution": "bank-model-risk",
        "env_prefix": "BANK_QUALITY",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_context_replacements_are_longest_first_and_env_is_normalized():
    pairs = rename_fork.replacements(_args())
    assert pairs[0] == ('name = "model-quality-gate"', 'name = "bank-model-risk"')
    assert ("AI_QUALITY_", "BANK_QUALITY_") in pairs


def test_rewrite_preserves_canonical_upstream_and_independent_distribution():
    original = (
        'name = "model-quality-gate"\n'
        "https://github.com/portable-genai/model-quality-gate\n"
        "service=model-quality-gate package=model_quality_gate env=AI_QUALITY_PROFILE\n"
    )
    updated = rename_fork.rewrite_text(original, _args(distribution="institution-quality-dist"))
    assert 'name = "institution-quality-dist"' in updated
    assert rename_fork.UPSTREAM_URL in updated
    assert "service=bank-model-risk package=bank_model_gate" in updated
    assert "env=BANK_QUALITY_PROFILE" in updated


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("package", "Bad-Package"),
        ("cli", "bad-"),
        ("service", "-bad"),
        ("distribution", "bad."),
        ("env_prefix", "lowercase"),
    ],
)
def test_invalid_names_fail_before_writes(field: str, value: str):
    with pytest.raises(ValueError):
        rename_fork.replacements(_args(**{field: value}))


def test_preview_plan_does_not_write_and_skips_canonical_skills(tmp_path: Path):
    source = tmp_path / "src" / "model_quality_gate"
    source.mkdir(parents=True)
    module = source / "sample.py"
    module.write_text('VALUE = "AI_QUALITY_PROFILE model-quality-gate"\n')
    canonical = tmp_path / ".agents" / "skills" / "canonical.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("model_quality_gate AI_QUALITY_\n")

    before = module.read_bytes()
    writes, moves = rename_fork.plan(tmp_path, _args())

    assert writes and moves
    assert module.read_bytes() == before
    assert canonical.read_text() == "model_quality_gate AI_QUALITY_\n"


def test_env_example_is_application_owned_text(tmp_path: Path):
    env_file = tmp_path / ".env.example"
    env_file.write_text("AI_QUALITY_PROFILE=local\n")
    writes, _ = rename_fork.plan(tmp_path, _args())
    assert (env_file, "BANK_QUALITY_PROFILE=local\n") in writes
    assert env_file.read_text() == "AI_QUALITY_PROFILE=local\n"


def test_missing_preflight_tool_leaves_every_file_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "source.txt"
    destination = tmp_path / "renamed.txt"
    source.write_text("original\n")

    def unavailable(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "python -m ruff")

    monkeypatch.setattr(rename_fork.subprocess, "run", unavailable)
    with pytest.raises(subprocess.CalledProcessError):
        rename_fork.apply(tmp_path, [(source, "changed\n")], [(source, destination)])
    assert source.read_text() == "original\n"
    assert not destination.exists()


def test_collision_fails_before_writes(tmp_path: Path):
    old = tmp_path / "src" / "model_quality_gate"
    old.mkdir(parents=True)
    (old / "module.py").write_text("model_quality_gate\n")
    new = tmp_path / "src" / "bank_model_gate"
    new.mkdir(parents=True)
    (new / "module.py").write_text("occupied\n")
    with pytest.raises(FileExistsError):
        rename_fork.plan(tmp_path, _args())
