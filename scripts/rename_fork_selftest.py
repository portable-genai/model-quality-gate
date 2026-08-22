"""Apply the rename to a clean copy, then run the renamed repository's full gate."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.exists():
        return digest.hexdigest()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> int:
    source = Path(__file__).resolve().parents[1]
    ignored = shutil.ignore_patterns(
        ".git",
        ".venv",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".terraform",
        "__pycache__",
        "node_modules",
        ".next",
        "out",
        "build",
        "dist",
        "*.egg-info",
    )
    with tempfile.TemporaryDirectory(prefix="hrz4-renamed-") as tmp:
        fork = Path(tmp) / "bank-model-risk"
        shutil.copytree(source, fork, ignore=ignored)
        skills_before = _tree_digest(fork / ".agents" / "skills")
        subprocess.run(
            [
                sys.executable,
                str(fork / "scripts" / "rename_fork.py"),
                "--root",
                str(fork),
                "--package",
                "bank_model_gate",
                "--cli",
                "bank-quality",
                "--service",
                "bank-model-risk",
                "--distribution",
                "bank-model-risk",
                "--env-prefix",
                "BANK_QUALITY",
                "--yes",
            ],
            check=True,
        )
        assert not (fork / "src" / "model_quality_gate").exists()
        assert (fork / "src" / "bank_model_gate").is_dir()
        assert not (fork / "scripts" / "model_quality_gate_demo.py").exists()
        assert (fork / "scripts" / "bank_model_gate_demo.py").is_file()
        assert _tree_digest(fork / ".agents" / "skills") == skills_before
        env_template = (fork / ".env.example").read_text()
        assert "BANK_QUALITY_PROFILE" in env_template
        assert "AI_QUALITY_" not in env_template

        venv = fork / ".rename-venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        python = venv / "bin" / "python"
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "-r",
                str(fork / "requirements-dev.lock"),
            ],
            cwd=fork,
            check=True,
        )
        subprocess.run(
            [str(python), "-m", "pip", "install", "-e", ".", "--no-deps"],
            cwd=fork,
            check=True,
        )
        env = dict(os.environ)
        env["BANK_QUALITY_PROFILE"] = "local"
        subprocess.run(
            ["make", "check", f"PYTHON={python}"],
            cwd=fork,
            env=env,
            check=True,
        )
        print("rename self-test PASS: fresh locked install + renamed full gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
