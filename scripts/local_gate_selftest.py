"""Assert that the laptop gate runs fully but cannot mint production attestation."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="hrz4-local-gate-") as directory:
        env = os.environ.copy()
        env["AI_QUALITY_PROFILE"] = "local"
        for name, filename in {
            "AI_QUALITY_LOCAL_DB": "knowledge.db",
            "AI_QUALITY_LOCAL_AUDIT": "audit.db",
            "AI_QUALITY_LOCAL_REGISTRY": "registry.db",
            "AI_QUALITY_LOCAL_MODEL_CARDS": "cards.db",
            "AI_QUALITY_LOCAL_METRICS": "metrics.db",
            "AI_QUALITY_LOCAL_DATASETS": "datasets.db",
        }.items():
            env[name] = str(Path(directory) / filename)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "model_quality_gate.cli.main",
                "gate",
                "gemini-3.5-flash",
                "v3",
                "compliance-qa-golden",
            ],
            cwd=root,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
    output = result.stdout
    required = (
        "Promotion gate",
        "[FAIL]",
        "Eval report",
        "[PASS]",
        "Red-team report",
        "evaluation passed but is not attested promotion evidence",
    )
    if result.returncode != 1 or any(value not in output for value in required):
        print(output)
        raise RuntimeError("local gate did not fail closed on missing managed attestation")
    print(output, end="")
    print("PASS local gate is functional and honestly denies production promotion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
