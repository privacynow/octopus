from __future__ import annotations

import json
from pathlib import Path
import sys


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


sys.path.insert(0, str(_repo_root()))

from octopus_registry.server import app


def main() -> None:
    repo_root = _repo_root()
    output_path = repo_root / "docs" / "registry-openapi.json"
    output_path.write_text(
        json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
