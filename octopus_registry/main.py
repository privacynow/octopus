"""Registry server entrypoint."""

from __future__ import annotations

import uvicorn

from .config import load_registry_config, validate_registry_config


def main() -> None:
    config = validate_registry_config(load_registry_config())
    uvicorn.run(
        "octopus_registry.server:app",
        host=config.bind_host,
        port=config.port,
    )


if __name__ == "__main__":
    main()
