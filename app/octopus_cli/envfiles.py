from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import re

from app.octopus_cli.models import RegistryConnection


_ENV_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def parse_env_file(path: Path) -> OrderedDict[str, str]:
    data: OrderedDict[str, str] = OrderedDict()
    if not path.exists():
        return data
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        match = _ENV_LINE_RE.match(raw_line)
        if not match:
            continue
        key, raw_value = match.groups()
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        data[key] = value
    return data


def escape_env_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def format_env_assignment(key: str, value: str) -> str:
    if not value or any(ch.isspace() for ch in value) or "#" in value:
        return f'{key}="{escape_env_value(value)}"'
    return f"{key}={value}"


def write_env_file(path: Path, values: OrderedDict[str, str]) -> None:
    lines = [format_env_assignment(key, value) for key, value in values.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)


def upsert_env_value(path: Path, key: str, value: str) -> None:
    values = parse_env_file(path)
    values[key] = value
    write_env_file(path, values)


def remove_env_value(path: Path, key: str) -> None:
    values = parse_env_file(path)
    values.pop(key, None)
    write_env_file(path, values)


def remove_env_matching(path: Path, pattern: re.Pattern[str]) -> None:
    if not path.exists():
        return
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if pattern.match(line):
            continue
        lines.append(line)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    path.chmod(0o600)


def list_registry_connection_records(path: Path) -> list[RegistryConnection]:
    values = parse_env_file(path)
    records: list[RegistryConnection] = []
    indices = sorted(
        {
            int(match.group(1))
            for key in values
            if (match := re.match(r"BOT_AGENT_REGISTRY_(\d+)_(ID|URL|ENROLL_TOKEN|SCOPE)$", key))
        }
    )
    for index in indices:
        registry_id = values.get(f"BOT_AGENT_REGISTRY_{index}_ID", f"registry-{index}")
        url = values.get(f"BOT_AGENT_REGISTRY_{index}_URL", "")
        token = values.get(f"BOT_AGENT_REGISTRY_{index}_ENROLL_TOKEN", "")
        scope = values.get(f"BOT_AGENT_REGISTRY_{index}_SCOPE", "full") or "full"
        if url or token:
            records.append(
                RegistryConnection(
                    registry_id=registry_id,
                    url=url,
                    enrollment_token=token,
                    scope=scope,
                )
            )
    if records:
        return records
    legacy_url = values.get("BOT_AGENT_REGISTRY_URL", "")
    legacy_token = values.get("BOT_AGENT_REGISTRY_ENROLL_TOKEN", "")
    legacy_scope = values.get("BOT_AGENT_REGISTRY_SCOPE", "full") or "full"
    if legacy_url or legacy_token:
        return [
            RegistryConnection(
                registry_id="default",
                url=legacy_url,
                enrollment_token=legacy_token,
                scope=legacy_scope,
            )
        ]
    return []


def write_registry_connection_records(path: Path, records: list[RegistryConnection]) -> None:
    values = parse_env_file(path)
    keys_to_remove = [
        key
        for key in values
        if re.match(r"BOT_AGENT_REGISTRY(_\d+_(ID|URL|ENROLL_TOKEN|SCOPE)|_(URL|ENROLL_TOKEN|SCOPE))$", key)
    ]
    for key in keys_to_remove:
        values.pop(key, None)
    for index, record in enumerate(records, start=1):
        values[f"BOT_AGENT_REGISTRY_{index}_ID"] = record.registry_id
        values[f"BOT_AGENT_REGISTRY_{index}_URL"] = record.url
        values[f"BOT_AGENT_REGISTRY_{index}_ENROLL_TOKEN"] = record.enrollment_token
        values[f"BOT_AGENT_REGISTRY_{index}_SCOPE"] = record.scope or "full"
    write_env_file(path, values)

