"""CLI parsing for the bot entrypoint."""

from __future__ import annotations

import argparse


def parse_main_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Octopus Agent Platform")
    parser.add_argument(
        "instance",
        nargs="?",
        default=None,
        help="Instance name (default: BOT_INSTANCE env)",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Run full health checks (config, DB, provider auth, Telegram) and exit",
    )
    parser.add_argument(
        "--doctor-live-provider",
        action="store_true",
        help="With --doctor, also run the live provider runtime probe",
    )
    parser.add_argument(
        "--provider-health",
        action="store_true",
        help="Run provider auth and live runtime checks only (no DB or Telegram)",
    )
    args = parser.parse_args()
    if args.doctor_live_provider and not args.doctor:
        parser.error("--doctor-live-provider requires --doctor")
    return args
