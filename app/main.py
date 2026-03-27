"""Profile-driven bot entrypoint."""

from __future__ import annotations

import asyncio
import logging

from app.config import fail_fast, load_config, load_config_provider_health
from app.runtime.cli import parse_main_args
from app.runtime.provider_factory import make_provider
from app.runtime.services import build_runtime
from app.runtime.startup import (
    initialize_runtime_startup,
    run_runtime_process,
    run_doctor,
    run_provider_health,
)
from app.startup_diagnostics import configure_startup_logging

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
configure_startup_logging()
log = logging.getLogger(__name__)


def main() -> None:
    args = parse_main_args()

    if args.provider_health:
        provider_health_config = load_config_provider_health()
        asyncio.run(run_provider_health(make_provider(provider_health_config)))
        return

    config = load_config(args.instance)
    provider = make_provider(config)
    fail_fast(config)

    if args.doctor:
        asyncio.run(
            run_doctor(
                config,
                provider,
                include_provider_runtime_probe=args.doctor_live_provider,
            )
        )
        return

    initialize_runtime_startup(config, provider)
    runtime_build = build_runtime(config, provider)
    run_runtime_process(config, runtime_build)


if __name__ == "__main__":
    main()
