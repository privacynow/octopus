from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def test_octopus_cli_help_runs_without_site_packages() -> None:
    python3 = shutil.which("python3")
    assert python3, "python3 is required for the bootstrap check"

    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [python3, "-S", "-m", "app.octopus_cli", "help"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Usage: ./octopus" in result.stdout
