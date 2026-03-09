"""Skill store: discovery, search, install/uninstall, update checking.

Store skills live in skills/store/ within the repo. Install copies them
to the custom skills directory (~/.config/telegram-agent-bot/skills/).
A _store.json manifest distinguishes store-installed skills from
user-created custom skills.
"""

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import frontmatter
import yaml

_log = logging.getLogger(__name__)

STORE_DIR = Path(__file__).resolve().parent.parent / "skills" / "store"
CUSTOM_DIR = Path.home() / ".config" / "telegram-agent-bot" / "skills"
_STORE_JSON = "_store.json"


@dataclass(frozen=True)
class StoreSkillInfo:
    """Metadata for a skill available in the store."""
    name: str
    display_name: str
    description: str
    has_requirements: bool
    has_claude_config: bool
    has_codex_config: bool


@dataclass(frozen=True)
class StoreManifest:
    """Provenance record written as _store.json in installed skill dir."""
    source: str  # always "store"
    store_path: str
    installed_at: str
    content_sha256: str
    locally_modified: bool = False


# ---------------------------------------------------------------------------
# Content hashing
# ---------------------------------------------------------------------------

def _hash_directory(path: Path) -> str:
    """SHA-256 of all files in a directory (sorted, deterministic).

    Excludes _store.json itself so we can compare store source vs installed.
    """
    h = hashlib.sha256()
    for fpath in sorted(path.rglob("*")):
        if fpath.is_file() and fpath.name != _STORE_JSON:
            h.update(fpath.relative_to(path).as_posix().encode())
            h.update(fpath.read_bytes())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Store discovery
# ---------------------------------------------------------------------------

def _parse_skill_md(path: Path) -> tuple[dict, str] | None:
    """Parse a skill.md file. Returns (metadata, body) or None on failure."""
    try:
        post = frontmatter.load(str(path))
        return dict(post.metadata), post.content.strip()
    except Exception:
        return None


def list_store_skills() -> dict[str, StoreSkillInfo]:
    """Discover all skills in the store directory."""
    if not STORE_DIR.is_dir():
        return {}
    result: dict[str, StoreSkillInfo] = {}
    for skill_dir in sorted(STORE_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "skill.md"
        if not skill_file.is_file():
            continue
        parsed = _parse_skill_md(skill_file)
        if parsed is None:
            _log.warning("Skipping malformed store skill: %s", skill_dir.name)
            continue
        meta, _ = parsed
        name = skill_dir.name
        result[name] = StoreSkillInfo(
            name=name,
            display_name=meta.get("display_name", name),
            description=meta.get("description", ""),
            has_requirements=(skill_dir / "requires.yaml").is_file(),
            has_claude_config=(skill_dir / "claude.yaml").is_file(),
            has_codex_config=(skill_dir / "codex.yaml").is_file(),
        )
    return result


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search(query: str) -> list[StoreSkillInfo]:
    """Substring match on name and description (case-insensitive)."""
    q = query.lower()
    results: list[StoreSkillInfo] = []
    for info in list_store_skills().values():
        if q in info.name.lower() or q in (info.description or "").lower():
            results.append(info)
    return results


# ---------------------------------------------------------------------------
# Skill info
# ---------------------------------------------------------------------------

def skill_info(name: str) -> tuple[StoreSkillInfo, str] | None:
    """Return (info, instructions_body) for a store skill, or None if not found."""
    store_path = STORE_DIR / name
    if not store_path.is_dir():
        return None
    skill_file = store_path / "skill.md"
    if not skill_file.is_file():
        return None
    parsed = _parse_skill_md(skill_file)
    if parsed is None:
        return None
    meta, body = parsed
    info = StoreSkillInfo(
        name=name,
        display_name=meta.get("display_name", name),
        description=meta.get("description", ""),
        has_requirements=(store_path / "requires.yaml").is_file(),
        has_claude_config=(store_path / "claude.yaml").is_file(),
        has_codex_config=(store_path / "codex.yaml").is_file(),
    )
    return info, body


def get_store_skill_requirements(name: str) -> list[str]:
    """Return credential key names from a store skill's requires.yaml.

    Falls back to the store directory for skills that aren't installed yet.
    Returns empty list if no requirements or skill not found.
    """
    store_path = STORE_DIR / name / "requires.yaml"
    if not store_path.is_file():
        return []
    try:
        data = yaml.safe_load(store_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    credentials = data.get("credentials", [])
    if not isinstance(credentials, list):
        return []
    return [str(item.get("key", "")) for item in credentials
            if isinstance(item, dict) and item.get("key")]


# ---------------------------------------------------------------------------
# _store.json helpers
# ---------------------------------------------------------------------------

def read_manifest(skill_dir: Path) -> StoreManifest | None:
    """Read _store.json from an installed skill directory."""
    manifest_path = skill_dir / _STORE_JSON
    if not manifest_path.is_file():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return StoreManifest(
            source=data.get("source", ""),
            store_path=data.get("store_path", ""),
            installed_at=data.get("installed_at", ""),
            content_sha256=data.get("content_sha256", ""),
            locally_modified=data.get("locally_modified", False),
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def _write_manifest(skill_dir: Path, manifest: StoreManifest) -> None:
    """Write _store.json to an installed skill directory."""
    data = {
        "source": manifest.source,
        "store_path": manifest.store_path,
        "installed_at": manifest.installed_at,
        "content_sha256": manifest.content_sha256,
        "locally_modified": manifest.locally_modified,
    }
    (skill_dir / _STORE_JSON).write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def is_store_installed(name: str) -> bool:
    """Check if a skill in the custom dir was installed from the store."""
    return read_manifest(CUSTOM_DIR / name) is not None


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------

def install(name: str) -> tuple[bool, str]:
    """Install a skill from the store to the custom skills directory.

    Returns (success, message).
    """
    store_path = STORE_DIR / name
    if not store_path.is_dir() or not (store_path / "skill.md").is_file():
        return False, f"Skill '{name}' not found in store."

    dest = CUSTOM_DIR / name
    if dest.is_dir():
        manifest = read_manifest(dest)
        if manifest is None:
            # User-created skill — don't overwrite
            return False, (
                f"Skill '{name}' already exists as a custom skill. "
                f"Use /skills uninstall first if you want to replace it with the store version."
            )
        # Already installed from store — treat as update
        return _do_install(name, store_path, dest, is_update=True)

    return _do_install(name, store_path, dest, is_update=False)


def _do_install(name: str, store_path: Path, dest: Path, *, is_update: bool) -> tuple[bool, str]:
    """Copy store skill to custom dir and write _store.json."""
    content_hash = _hash_directory(store_path)

    if is_update:
        # Check for local modifications
        manifest = read_manifest(dest)
        if manifest and manifest.content_sha256 != _hash_directory(dest):
            _log.warning("Skill '%s' was locally modified, overwriting", name)

    # Clean and copy
    if dest.is_dir():
        shutil.rmtree(dest)
    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copytree(store_path, dest)

    # Write provenance manifest
    _write_manifest(dest, StoreManifest(
        source="store",
        store_path=f"skills/store/{name}",
        installed_at=datetime.now(timezone.utc).isoformat(),
        content_sha256=content_hash,
        locally_modified=False,
    ))

    # Verify SHA-256
    installed_hash = _hash_directory(dest)
    if installed_hash != content_hash:
        # Should not happen, but guard against filesystem issues
        shutil.rmtree(dest, ignore_errors=True)
        return False, f"SHA-256 verification failed after install for '{name}'."

    action = "updated" if is_update else "installed"
    return True, f"Skill '{name}' {action} from store. Use /skills add {name} to activate."


# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------

def uninstall(
    name: str,
    default_skills: tuple[str, ...],
    session_sweep_fn=None,
) -> tuple[bool, str]:
    """Remove a store-installed skill from the custom directory.

    Returns (success, message).
    - Refuses if skill is in BOT_SKILLS (operator intent).
    - Calls session_sweep_fn(name) to deactivate from all chats.
    - Only removes directories with _store.json (won't touch user-created).
    """
    dest = CUSTOM_DIR / name
    if not dest.is_dir():
        return False, f"Skill '{name}' is not installed."

    manifest = read_manifest(dest)
    if manifest is None:
        return False, f"Skill '{name}' is a custom skill, not a store install. Use the filesystem to manage it."

    # Config guard
    if name in default_skills:
        return False, (
            f"Skill '{name}' is listed in BOT_SKILLS. "
            f"Remove it from your .env config before uninstalling."
        )

    # Session sweep
    swept = 0
    if session_sweep_fn:
        swept = session_sweep_fn(name)

    # Remove
    shutil.rmtree(dest)

    parts = [f"Skill '{name}' uninstalled."]
    if swept:
        parts.append(f"Deactivated from {swept} chat(s).")
    return True, " ".join(parts)


# ---------------------------------------------------------------------------
# Update checking
# ---------------------------------------------------------------------------

def check_updates() -> list[tuple[str, str]]:
    """Compare installed store skills against current store content.

    Returns list of (name, status) where status is one of:
    - "update_available" — store content changed since install
    - "locally_modified" — installed content differs from both store and manifest
    - "up_to_date" — no changes
    """
    results: list[tuple[str, str]] = []
    if not CUSTOM_DIR.is_dir():
        return results

    for skill_dir in sorted(CUSTOM_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        manifest = read_manifest(skill_dir)
        if manifest is None:
            continue  # Not a store-installed skill

        name = skill_dir.name
        installed_hash = _hash_directory(skill_dir)

        # Check if locally modified
        if installed_hash != manifest.content_sha256:
            if not manifest.locally_modified:
                _write_manifest(skill_dir, StoreManifest(
                    source=manifest.source,
                    store_path=manifest.store_path,
                    installed_at=manifest.installed_at,
                    content_sha256=manifest.content_sha256,
                    locally_modified=True,
                ))
            results.append((name, "locally_modified"))
            continue

        # Check if store has a newer version
        store_path = STORE_DIR / name
        if not store_path.is_dir():
            continue  # Store skill removed — nothing to update
        store_hash = _hash_directory(store_path)
        if store_hash != manifest.content_sha256:
            results.append((name, "update_available"))
        else:
            results.append((name, "up_to_date"))

    return results


def update_skill(name: str) -> tuple[bool, str]:
    """Re-install a single store skill.

    Returns (success, message). Warns if locally modified.
    """
    dest = CUSTOM_DIR / name
    if not dest.is_dir():
        return False, f"Skill '{name}' is not installed."

    manifest = read_manifest(dest)
    if manifest is None:
        return False, f"Skill '{name}' is a custom skill, not a store install."

    store_path = STORE_DIR / name
    if not store_path.is_dir():
        return False, f"Skill '{name}' is no longer available in the store."

    # Check if actually needs update
    store_hash = _hash_directory(store_path)
    installed_hash = _hash_directory(dest)
    locally_modified = installed_hash != manifest.content_sha256

    warning = ""
    if locally_modified:
        warning = " (local modifications overwritten)"

    if store_hash == installed_hash and not locally_modified:
        return True, f"Skill '{name}' is already up to date."

    ok, msg = _do_install(name, store_path, dest, is_update=True)
    if ok and warning:
        msg += warning
    return ok, msg


def update_all() -> list[tuple[str, bool, str]]:
    """Update all store-installed skills that have updates available.

    Returns list of (name, success, message).
    """
    results: list[tuple[str, bool, str]] = []
    for name, status in check_updates():
        if status in ("update_available", "locally_modified"):
            ok, msg = update_skill(name)
            results.append((name, ok, msg))
    return results

def diff_skill(name: str, max_chars: int = 2000) -> tuple[bool, str]:
    """Show diff between installed skill and store version.

    Returns (ok, diff_text). If not a store skill or no differences, returns
    a descriptive message instead of a diff.
    """
    import difflib

    dest = CUSTOM_DIR / name
    if not dest.is_dir():
        return False, f"Skill '{name}' is not installed."

    manifest = read_manifest(dest)
    if manifest is None:
        return False, f"Skill '{name}' is a custom skill, not a store install."

    store_path = STORE_DIR / name
    if not store_path.is_dir():
        return False, f"Skill '{name}' is no longer in the store."

    # Collect text files from both sides
    lines: list[str] = []
    all_files = set()
    for d in (store_path, dest):
        for f in sorted(d.rglob("*")):
            if f.is_file() and f.name != "_store.json":
                all_files.add(f.relative_to(d))

    for rel in sorted(all_files):
        store_file = store_path / rel
        installed_file = dest / rel
        store_lines = store_file.read_text().splitlines(keepends=True) if store_file.exists() else []
        installed_lines = installed_file.read_text().splitlines(keepends=True) if installed_file.exists() else []
        if store_lines == installed_lines:
            continue
        diff = difflib.unified_diff(
            store_lines, installed_lines,
            fromfile=f"store/{name}/{rel}", tofile=f"installed/{name}/{rel}",
        )
        lines.extend(diff)

    if not lines:
        return True, f"Skill '{name}' has no differences from store version."

    text = "".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n... (truncated at {max_chars} chars)"
    return True, text


def is_locally_modified(name: str) -> bool:
    """Check if an installed store skill has local modifications."""
    dest = CUSTOM_DIR / name
    if not dest.is_dir():
        return False
    manifest = read_manifest(dest)
    if manifest is None:
        return False
    return _hash_directory(dest) != manifest.content_sha256

