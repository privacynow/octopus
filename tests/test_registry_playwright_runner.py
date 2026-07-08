from __future__ import annotations

import os
from pathlib import Path
import subprocess


def test_registry_playwright_runner_is_executable_from_pytest() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    runner = repo_root / "scripts" / "e2e" / "run_registry_playwright.sh"
    spec = repo_root / "tests" / "e2e" / "playwright" / "auto-protocol-ui.spec.js"
    package_lock = repo_root / "tests" / "e2e" / "playwright" / "package-lock.json"
    workflow = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    runner_text = runner.read_text(encoding="utf-8")

    assert runner.exists()
    assert package_lock.exists()
    assert os.access(runner, os.X_OK)
    assert "scripts/e2e/run_registry_playwright.sh" in workflow
    assert "timeout-minutes:" in workflow
    assert "npm ci --prefix" in runner_text

    subprocess.run(["bash", "-n", str(runner)], cwd=repo_root, check=True)
    subprocess.run(["node", "--check", str(spec)], cwd=repo_root, check=True)
    dry_run = subprocess.run(
        ["bash", str(runner), str(spec)],
        cwd=repo_root,
        check=True,
        text=True,
        capture_output=True,
        env={**os.environ, "PLAYWRIGHT_DRY_RUN": "1"},
    )
    assert "playwright test" in dry_run.stdout
    assert str(spec) in dry_run.stdout
    assert "tests/e2e/playwright.config.js" in dry_run.stdout
