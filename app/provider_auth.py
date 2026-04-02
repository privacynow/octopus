from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path


SUPPORTED_PROVIDERS = ("claude", "codex")


def normalize_provider_name(provider: str) -> str:
    value = str(provider or "").strip().lower()
    if value not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported provider '{provider}'.")
    return value


def shared_auth_root(provider: str, base_dir: Path) -> Path:
    name = normalize_provider_name(provider)
    root = Path(base_dir)
    if name == "claude":
        return root
    return root / ".codex"


def runtime_auth_root(provider: str, *, home_dir: Path | None = None) -> Path:
    name = normalize_provider_name(provider)
    home = Path(home_dir or Path.home())
    if name == "claude":
        return home
    return Path(os.environ.get("CODEX_HOME", str(home / ".codex")))


def ensure_auth_layout(provider: str, auth_root: Path) -> Path:
    name = normalize_provider_name(provider)
    auth_root.mkdir(parents=True, exist_ok=True)
    auth_root.chmod(0o700)
    if name == "claude":
        (auth_root / ".claude").mkdir(parents=True, exist_ok=True)
        auth_file = auth_root / ".claude.json"
        if not auth_file.exists():
            auth_file.write_text("", encoding="utf-8")
            auth_file.chmod(0o600)
    else:
        auth_root.mkdir(parents=True, exist_ok=True)
    return auth_root


def auth_cleanup_targets(provider: str, auth_root: Path) -> tuple[Path, ...]:
    name = normalize_provider_name(provider)
    if name == "claude":
        return (auth_root / ".claude", auth_root / ".claude.json")
    return (auth_root,)


def has_auth_artifacts(provider: str, auth_root: Path) -> bool:
    name = normalize_provider_name(provider)
    root = Path(auth_root)
    if name == "claude":
        auth_file = root / ".claude.json"
        if auth_file.is_file() and auth_file.stat().st_size > 0:
            return True
        auth_dir = root / ".claude"
        if not auth_dir.is_dir():
            return False
        try:
            for path in auth_dir.rglob("*"):
                if path.is_file() and path.stat().st_size > 0:
                    return True
        except OSError:
            return False
        return False
    auth_file = root / "auth.json"
    return auth_file.is_file() and auth_file.stat().st_size > 0


def auth_artifact_errors(provider: str, auth_root: Path) -> list[str]:
    name = normalize_provider_name(provider)
    root = Path(auth_root)
    if not has_auth_artifacts(name, root):
        if name == "claude":
            return ["Claude auth not found. Run './octopus' and choose Diagnose -> Provider auth."]
        return ["Codex auth not found. Run './octopus' and choose Diagnose -> Provider auth."]
    errors: list[str] = []
    if name == "claude":
        auth_file = root / ".claude.json"
        if auth_file.is_file() and auth_file.stat().st_size > 0:
            try:
                json.loads(auth_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"Claude auth file is invalid JSON: {exc}")
    else:
        auth_file = root / "auth.json"
        if auth_file.is_file() and auth_file.stat().st_size > 0:
            try:
                json.loads(auth_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"Codex auth file is invalid JSON: {exc}")
    return errors


def cleanup_runtime_auth(provider: str, *, home_dir: Path | None = None) -> list[Path]:
    root = runtime_auth_root(provider, home_dir=home_dir)
    removed: list[Path] = []
    for path in auth_cleanup_targets(provider, root):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=False)
            removed.append(path)
        elif path.exists():
            path.unlink()
            removed.append(path)
    return removed


def sync_runtime_to_shared(provider: str, *, home_dir: Path | None = None, shared_base_dir: Path) -> None:
    name = normalize_provider_name(provider)
    runtime_root = runtime_auth_root(name, home_dir=home_dir)
    shared_root = ensure_auth_layout(name, shared_auth_root(name, shared_base_dir))
    if name == "codex":
        return
    runtime_auth_file = runtime_root / ".claude.json"
    runtime_auth_dir = runtime_root / ".claude"
    if runtime_auth_file.is_file():
        shutil.copy2(runtime_auth_file, shared_root / ".claude.json")
    if runtime_auth_dir.is_dir():
        target_dir = shared_root / ".claude"
        target_dir.mkdir(parents=True, exist_ok=True)
        for path in runtime_auth_dir.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(runtime_auth_dir)
            destination = target_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.provider_auth")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ensure_parser = subparsers.add_parser("ensure-shared-layout")
    ensure_parser.add_argument("provider")
    ensure_parser.add_argument("base_dir")

    has_runtime_parser = subparsers.add_parser("has-runtime-artifacts")
    has_runtime_parser.add_argument("provider")
    has_runtime_parser.add_argument("home_dir")

    cleanup_parser = subparsers.add_parser("cleanup-runtime")
    cleanup_parser.add_argument("provider")
    cleanup_parser.add_argument("home_dir")

    sync_parser = subparsers.add_parser("sync-runtime-to-shared")
    sync_parser.add_argument("provider")
    sync_parser.add_argument("home_dir")
    sync_parser.add_argument("shared_base_dir")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "ensure-shared-layout":
        ensure_auth_layout(args.provider, shared_auth_root(args.provider, Path(args.base_dir)))
        return 0
    if args.command == "has-runtime-artifacts":
        return 0 if has_auth_artifacts(args.provider, runtime_auth_root(args.provider, home_dir=Path(args.home_dir))) else 1
    if args.command == "cleanup-runtime":
        removed = cleanup_runtime_auth(args.provider, home_dir=Path(args.home_dir))
        if removed:
            for path in removed:
                print(path)
        return 0
    if args.command == "sync-runtime-to-shared":
        sync_runtime_to_shared(
            args.provider,
            home_dir=Path(args.home_dir),
            shared_base_dir=Path(args.shared_base_dir),
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
