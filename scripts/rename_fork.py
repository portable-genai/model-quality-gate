"""Preview or apply a bounded, collision-safe rename for an institutional fork."""

from __future__ import annotations

import argparse
import contextlib
import re
import subprocess
import sys
from pathlib import Path

OLD_PACKAGE = "model_quality_gate"
OLD_CLI = "ai-quality"
OLD_SERVICE = "model-quality-gate"
OLD_ENV = "AI_QUALITY_"
UPSTREAM_URL = "https://github.com/portable-genai/model-quality-gate"

SKIP_PARTS = {
    ".git",
    ".venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".terraform",
    # The vendored upstream skills, and the Claude Code symlink beside them. Renaming inside
    # either forks them from the maintainer's shared agent skills, which is the whole
    # point of not doing it.
    ".agents",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    ".next",
}
SELF_FILES = {
    "scripts/rename_fork.py",
    "scripts/rename_fork_selftest.py",
    "tests/unit/test_rename_fork.py",
}
TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".txt",
    ".tf",
    ".tfvars",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".tsx",
}
TEXT_NAMES = {"Makefile", "Dockerfile", ".env.example"}


def _valid(value: str, pattern: str, label: str) -> str:
    if not re.fullmatch(pattern, value):
        raise ValueError(f"invalid {label}: {value!r}")
    return value


def replacements(args: argparse.Namespace) -> list[tuple[str, str]]:
    package = _valid(args.package, r"[a-z][a-z0-9_]*", "package")
    cli = _valid(args.cli, r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", "CLI")
    service = _valid(args.service, r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", "service")
    distribution = _valid(args.distribution, r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?", "distribution")
    env = _valid(args.env_prefix.rstrip("_"), r"[A-Z][A-Z0-9_]*", "env prefix") + "_"
    return [
        ('name = "model-quality-gate"', f'name = "{distribution}"'),
        (OLD_SERVICE, service),
        (OLD_PACKAGE, package),
        (OLD_ENV, env),
        (OLD_CLI, cli),
    ]


def rewrite_text(original: str, args: argparse.Namespace) -> str:
    """Rewrite app-owned identifiers while preserving the canonical upstream URL."""
    upstream_marker = "__HRZ4_CANONICAL_UPSTREAM_URL__"
    distribution_marker = "__HRZ4_FORK_DISTRIBUTION__"
    if upstream_marker in original or distribution_marker in original:
        raise ValueError("reserved rename marker already exists in source text")
    updated = original.replace(UPSTREAM_URL, upstream_marker)
    pairs = replacements(args)
    project_line, distribution_line = pairs[0]
    updated = updated.replace(project_line, distribution_marker)
    for old, new in pairs[1:]:
        updated = updated.replace(old, new)
    updated = updated.replace(distribution_marker, distribution_line)
    return updated.replace(upstream_marker, UPSTREAM_URL)


def _included(root: Path, path: Path) -> bool:
    rel = path.relative_to(root)
    return not (set(rel.parts) & SKIP_PARTS) and rel.as_posix() not in SELF_FILES


def plan(
    root: Path, args: argparse.Namespace
) -> tuple[list[tuple[Path, str]], list[tuple[Path, Path]]]:
    replacements(args)  # validate every identifier before scanning or writing
    writes: list[tuple[Path, str]] = []
    moves: list[tuple[Path, Path]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not _included(root, path):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_NAMES:
            original = path.read_text(encoding="utf-8")
            updated = rewrite_text(original, args)
            if updated != original:
                writes.append((path, updated))
        rel = path.relative_to(root)
        renamed = Path(*(part.replace(OLD_PACKAGE, args.package) for part in rel.parts))
        destination = root / renamed
        if destination != path:
            moves.append((path, destination))

    sources = {source for source, _ in moves}
    destinations: set[Path] = set()
    for source, destination in moves:
        if destination in destinations or (destination.exists() and destination not in sources):
            raise FileExistsError(f"rename collision: {source} -> {destination}")
        destinations.add(destination)
    return writes, moves


def preflight(root: Path) -> None:
    """Prove the formatter and clean source gate before any filesystem mutation."""
    subprocess.run([sys.executable, "-m", "ruff", "--version"], cwd=root, check=True)
    subprocess.run(
        [sys.executable, "-m", "ruff", "check", "src", "tests", "eval", "scripts"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "format",
            "--check",
            "src",
            "tests",
            "eval",
            "scripts",
        ],
        cwd=root,
        check=True,
    )


def apply(root: Path, writes: list[tuple[Path, str]], moves: list[tuple[Path, Path]]) -> None:
    preflight(root)
    for path, content in writes:
        path.write_text(content, encoding="utf-8")
    for source, destination in sorted(moves, key=lambda pair: len(pair[0].parts), reverse=True):
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
    for directory in sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        if _included(root, directory):
            with contextlib.suppress(OSError):
                directory.rmdir()
    subprocess.run(
        [sys.executable, "-m", "ruff", "format", "src", "tests", "eval", "scripts"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--fix",
            "src",
            "tests",
            "eval",
            "scripts",
        ],
        cwd=root,
        check=True,
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--root", type=Path, default=Path.cwd())
    result.add_argument("--package", required=True)
    result.add_argument("--cli", required=True)
    result.add_argument("--service", required=True)
    result.add_argument("--distribution", required=True)
    result.add_argument("--env-prefix", required=True)
    result.add_argument("--yes", action="store_true", help="Apply after preview")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    root = args.root.resolve()
    writes, moves = plan(root, args)
    print(f"{'APPLY' if args.yes else 'PREVIEW'}: {len(writes)} files, {len(moves)} paths")
    for source, destination in moves:
        print(f"  {source.relative_to(root)} -> {destination.relative_to(root)}")
    if args.yes:
        apply(root, writes, moves)
        print("rename applied; local data and external infrastructure were not migrated")
    else:
        print("no files changed; repeat with --yes to apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
