"""Managed immutable skill store.

Layout under ~/.config/telegram-agent-bot/skills/:

    custom/<name>/              Operator-authored, editable
    managed/version.json        Schema version marker
    managed/.lock               Cross-instance flock
    managed/objects/<sha256>/   Immutable skill snapshots
    managed/refs/<name>.json    Logical name → digest + provenance
    managed/tmp/                Staging for in-progress installs
"""

import difflib
import fcntl
import hashlib
import json
import logging
import os
import shutil
import stat
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import frontmatter
import yaml

_log = logging.getLogger(__name__)

# Bundled store source (in repo, read-only)
STORE_DIR = Path(__file__).resolve().parent.parent / "skills" / "store"

# Managed store root — shared across instances
_SKILLS_ROOT = Path.home() / ".config" / "telegram-agent-bot" / "skills"
CUSTOM_DIR = _SKILLS_ROOT / "custom"
MANAGED_DIR = _SKILLS_ROOT / "managed"
OBJECTS_DIR = MANAGED_DIR / "objects"
REFS_DIR = MANAGED_DIR / "refs"
TMP_DIR = MANAGED_DIR / "tmp"
VERSION_FILE = MANAGED_DIR / "version.json"
LOCK_FILE = MANAGED_DIR / ".lock"

_SCHEMA_VERSION = 1
_GC_GRACE_SECONDS = 3600  # 1 hour


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StoreSkillInfo:
    """Metadata for a skill available in the bundled store."""
    name: str
    display_name: str
    description: str
    has_requirements: bool
    has_claude_config: bool
    has_codex_config: bool


@dataclass(frozen=True)
class SkillRef:
    """Logical ref: name → immutable object digest + provenance."""
    schema_version: int
    digest: str
    source: str
    source_uri: str
    installed_at: str
    version: str | None = None
    publisher: str | None = None
    signature: str | None = None
    pinned: bool = False


# ---------------------------------------------------------------------------
# Content hashing
# ---------------------------------------------------------------------------

def hash_directory(path: Path) -> str:
    """SHA-256 of all files in a directory.

    Hash includes relative path, file mode (octal), and content for each file.
    Sorted for determinism. Excludes metadata files (_store.json, _ref.json).
    """
    h = hashlib.sha256()
    exclude = {"_store.json", "_ref.json"}
    for fpath in sorted(path.rglob("*")):
        if fpath.is_file() and fpath.name not in exclude:
            rel = fpath.relative_to(path).as_posix()
            mode = oct(fpath.stat().st_mode & 0o777)
            h.update(rel.encode())
            h.update(b"\0")
            h.update(mode.encode())
            h.update(b"\0")
            h.update(fpath.read_bytes())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Directory init and schema guard
# ---------------------------------------------------------------------------

def ensure_managed_dirs() -> None:
    """Create the managed store layout if it doesn't exist."""
    for d in (CUSTOM_DIR, OBJECTS_DIR, REFS_DIR, TMP_DIR):
        d.mkdir(parents=True, exist_ok=True)
    if not VERSION_FILE.exists():
        VERSION_FILE.write_text(
            json.dumps({"schema": _SCHEMA_VERSION}) + "\n"
        )


def check_schema() -> None:
    """Verify schema version. Raises if incompatible."""
    if not VERSION_FILE.exists():
        return  # Fresh init, ensure_managed_dirs will create it
    try:
        data = json.loads(VERSION_FILE.read_text())
        version = data.get("schema", 0)
    except (json.JSONDecodeError, OSError):
        version = 0
    if version > _SCHEMA_VERSION:
        raise RuntimeError(
            f"Managed store schema version {version} is newer than "
            f"supported version {_SCHEMA_VERSION}. Upgrade the bot."
        )


# ---------------------------------------------------------------------------
# Cross-instance locking
# ---------------------------------------------------------------------------

@contextmanager
def _store_lock():
    """Acquire exclusive flock on the managed store.

    Used for all mutations: object creation, ref writes, GC, recovery.
    Read-only operations (skill resolution, catalog loading) do NOT lock.
    """
    MANAGED_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(LOCK_FILE), os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


# ---------------------------------------------------------------------------
# Ref read/write (atomic)
# ---------------------------------------------------------------------------

def read_ref(name: str) -> SkillRef | None:
    """Read a logical ref by skill name. Returns None if missing or corrupt."""
    ref_path = REFS_DIR / f"{name}.json"
    if not ref_path.is_file():
        return None
    try:
        data = json.loads(ref_path.read_text(encoding="utf-8"))
        return SkillRef(
            schema_version=data.get("schema_version", 1),
            digest=data["digest"],
            source=data.get("source", "store"),
            source_uri=data.get("source_uri", ""),
            installed_at=data.get("installed_at", ""),
            version=data.get("version"),
            publisher=data.get("publisher"),
            signature=data.get("signature"),
            pinned=data.get("pinned", False),
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        _log.warning("Corrupt ref for '%s', treating as missing", name)
        return None


def _write_ref(name: str, ref: SkillRef) -> None:
    """Atomically write a ref: write .tmp then rename."""
    REFS_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": ref.schema_version,
        "digest": ref.digest,
        "source": ref.source,
        "source_uri": ref.source_uri,
        "installed_at": ref.installed_at,
        "version": ref.version,
        "publisher": ref.publisher,
        "signature": ref.signature,
        "pinned": ref.pinned,
    }
    tmp = REFS_DIR / f"{name}.json.tmp"
    tmp.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.rename(REFS_DIR / f"{name}.json")


def _delete_ref(name: str) -> bool:
    """Delete a ref file. Returns True if it existed."""
    ref_path = REFS_DIR / f"{name}.json"
    try:
        ref_path.unlink()
        return True
    except FileNotFoundError:
        return False


def list_refs() -> dict[str, SkillRef]:
    """Return all logical refs."""
    result: dict[str, SkillRef] = {}
    if not REFS_DIR.is_dir():
        return result
    for p in sorted(REFS_DIR.glob("*.json")):
        if p.name.endswith(".tmp"):
            continue
        name = p.stem
        ref = read_ref(name)
        if ref:
            result[name] = ref
    return result


# ---------------------------------------------------------------------------
# Object management (immutable, content-addressed)
# ---------------------------------------------------------------------------

def _object_dir(digest: str) -> Path:
    return OBJECTS_DIR / digest


def _object_exists(digest: str) -> bool:
    return _object_dir(digest).is_dir()


def _create_object(source_dir: Path) -> str:
    """Create an immutable object from source directory.

    Copies to tmp, hashes, moves to objects/<digest>/.
    Idempotent: if object already exists, skips.
    Returns the digest.
    """
    # Stage in tmp
    ts = f"{time.time():.6f}".replace(".", "_")
    staging = TMP_DIR / f"obj_{ts}"
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(source_dir, staging)

    # Remove any metadata files that shouldn't be in the object
    for meta in ("_store.json", "_ref.json"):
        meta_path = staging / meta
        if meta_path.exists():
            meta_path.unlink()

    digest = hash_directory(staging)
    dest = _object_dir(digest)

    if dest.is_dir():
        # Already exists — idempotent
        shutil.rmtree(staging)
    else:
        OBJECTS_DIR.mkdir(parents=True, exist_ok=True)
        staging.rename(dest)

    return digest


def resolve_object(name: str) -> Path | None:
    """Resolve a managed skill name to its immutable object directory.

    Returns None if no ref or object is missing.
    """
    ref = read_ref(name)
    if ref is None:
        return None
    obj = _object_dir(ref.digest)
    if not obj.is_dir():
        _log.warning("Ref '%s' points to missing object %s", name, ref.digest[:12])
        return None
    return obj


# ---------------------------------------------------------------------------
# Bundled store discovery (read-only, from repo)
# ---------------------------------------------------------------------------

def _parse_skill_md(path: Path) -> tuple[dict, str] | None:
    """Parse a skill.md file. Returns (metadata, body) or None on failure."""
    try:
        post = frontmatter.load(str(path))
        return dict(post.metadata), post.content.strip()
    except Exception:
        return None


def list_store_skills() -> dict[str, StoreSkillInfo]:
    """Discover all skills in the bundled store directory."""
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


def search(query: str) -> list[StoreSkillInfo]:
    """Substring match on name and description (case-insensitive)."""
    q = query.lower()
    return [
        info for info in list_store_skills().values()
        if q in info.name.lower() or q in (info.description or "").lower()
    ]


def skill_info(name: str) -> tuple[StoreSkillInfo, str] | None:
    """Return (info, instructions_body) for a bundled store skill."""
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
    """Return credential key names from a bundled store skill's requires.yaml."""
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
# Install / Uninstall / Update
# ---------------------------------------------------------------------------

def install(name: str) -> tuple[bool, str]:
    """Install a skill from the bundled store.

    Creates an immutable object and writes a ref.
    Returns (success, message).
    """
    store_path = STORE_DIR / name
    if not store_path.is_dir() or not (store_path / "skill.md").is_file():
        return False, f"Skill '{name}' not found in store."

    with _store_lock():
        existing_ref = read_ref(name)

        # Check for custom skill with same name (not a managed override)
        custom_path = CUSTOM_DIR / name
        if custom_path.is_dir() and existing_ref is None:
            return False, (
                f"Skill '{name}' already exists as a custom skill. "
                f"Remove it first if you want to install the store version."
            )

        digest = _create_object(store_path)
        ref = SkillRef(
            schema_version=_SCHEMA_VERSION,
            digest=digest,
            source="store",
            source_uri=f"skills/store/{name}",
            installed_at=datetime.now(timezone.utc).isoformat(),
        )
        _write_ref(name, ref)

    if existing_ref:
        action = "updated" if existing_ref.digest != digest else "reinstalled"
    else:
        action = "installed"
    return True, f"Skill '{name}' {action} from store. Use /skills add {name} to activate."


def uninstall(name: str, default_skills: tuple[str, ...] = ()) -> tuple[bool, str]:
    """Remove a managed skill ref.

    The object becomes unreferenced and will be cleaned up by GC.
    Sessions self-heal: missing refs are pruned on next load.
    Returns (success, message).
    """
    with _store_lock():
        ref = read_ref(name)
        if ref is None:
            return False, f"Skill '{name}' is not installed as a managed skill."

        if name in default_skills:
            return False, (
                f"Skill '{name}' is listed in BOT_SKILLS. "
                f"Remove it from your .env config before uninstalling."
            )

        _delete_ref(name)

    custom_path = CUSTOM_DIR / name
    parts = [f"Skill '{name}' uninstalled."]
    if custom_path.is_dir():
        parts.append(
            f"Note: custom override '{name}' still exists and will remain active."
        )
    return True, " ".join(parts)


def update_skill(name: str) -> tuple[bool, str]:
    """Update a managed skill from the bundled store.

    Creates a new object and atomically swaps the ref.
    Returns (success, message).
    """
    store_path = STORE_DIR / name
    if not store_path.is_dir():
        return False, f"Skill '{name}' is no longer available in the store."

    with _store_lock():
        ref = read_ref(name)
        if ref is None:
            return False, f"Skill '{name}' is not installed as a managed skill."

        new_digest = _create_object(store_path)

        if new_digest == ref.digest:
            return True, f"Skill '{name}' is already up to date."

        new_ref = SkillRef(
            schema_version=_SCHEMA_VERSION,
            digest=new_digest,
            source="store",
            source_uri=f"skills/store/{name}",
            installed_at=datetime.now(timezone.utc).isoformat(),
            pinned=ref.pinned,
        )
        _write_ref(name, new_ref)

    msg = f"Skill '{name}' updated from store."
    custom_path = CUSTOM_DIR / name
    if custom_path.is_dir():
        msg += " Note: custom override is still active."
    return True, msg


def update_all() -> list[tuple[str, bool, str]]:
    """Update all managed skills that have updates available.

    Returns list of (name, success, message). Skips pinned refs.
    """
    results: list[tuple[str, bool, str]] = []
    for name, status in check_updates():
        if status == "update_available":
            ref = read_ref(name)
            if ref and ref.pinned:
                results.append((name, True, f"Skill '{name}' is pinned, skipping."))
                continue
            ok, msg = update_skill(name)
            results.append((name, ok, msg))
    return results


# ---------------------------------------------------------------------------
# Update checking
# ---------------------------------------------------------------------------

def check_updates() -> list[tuple[str, str]]:
    """Compare managed refs against bundled store content.

    Returns list of (name, status) where status is one of:
    - "update_available" — store content changed since install
    - "up_to_date" — no changes
    """
    results: list[tuple[str, str]] = []
    refs = list_refs()
    for name, ref in refs.items():
        store_path = STORE_DIR / name
        if not store_path.is_dir():
            continue  # Store skill removed — nothing to update
        store_hash = hash_directory(store_path)
        if store_hash != ref.digest:
            results.append((name, "update_available"))
        else:
            results.append((name, "up_to_date"))
    return results


# ---------------------------------------------------------------------------
# Custom override detection
# ---------------------------------------------------------------------------

def has_custom_override(name: str) -> bool:
    """Check if a custom skill shadows a managed ref."""
    return (CUSTOM_DIR / name).is_dir() and read_ref(name) is not None


def is_store_installed(name: str) -> bool:
    """Check if a managed ref exists for this skill name."""
    return read_ref(name) is not None


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

def diff_skill(name: str, max_chars: int = 4000) -> tuple[bool, str]:
    """Show diff for a skill.

    If custom override exists with a managed ref: diffs custom vs managed object.
    If only managed ref: diffs managed object vs store source (preview of update).
    """
    ref = read_ref(name)
    custom_path = CUSTOM_DIR / name

    if custom_path.is_dir() and ref is not None:
        # Diff custom override vs managed object
        obj_path = _object_dir(ref.digest)
        if not obj_path.is_dir():
            return False, f"Managed object for '{name}' is missing."
        return _diff_dirs(
            obj_path, custom_path, name,
            from_label="managed", to_label="custom",
            max_chars=max_chars,
        )

    if ref is not None:
        # Diff managed object vs store source
        obj_path = _object_dir(ref.digest)
        store_path = STORE_DIR / name
        if not store_path.is_dir():
            return False, f"Skill '{name}' is no longer in the store."
        if not obj_path.is_dir():
            return False, f"Managed object for '{name}' is missing."
        return _diff_dirs(
            obj_path, store_path, name,
            from_label="installed", to_label="store",
            max_chars=max_chars,
        )

    if custom_path.is_dir():
        return False, f"Skill '{name}' is a custom skill with no managed version to compare."

    return False, f"Skill '{name}' is not installed."


def _diff_dirs(
    dir_a: Path, dir_b: Path, name: str, *,
    from_label: str, to_label: str,
    max_chars: int,
) -> tuple[bool, str]:
    """Unified diff between two skill directories."""
    all_files: set[Path] = set()
    for d in (dir_a, dir_b):
        for f in sorted(d.rglob("*")):
            if f.is_file() and f.name not in ("_store.json", "_ref.json"):
                all_files.add(f.relative_to(d))

    lines: list[str] = []
    for rel in sorted(all_files):
        fa, fb = dir_a / rel, dir_b / rel
        la = fa.read_text(errors="replace").splitlines(keepends=True) if fa.exists() else []
        lb = fb.read_text(errors="replace").splitlines(keepends=True) if fb.exists() else []
        if la == lb:
            continue
        diff = difflib.unified_diff(
            la, lb,
            fromfile=f"{from_label}/{name}/{rel}",
            tofile=f"{to_label}/{name}/{rel}",
        )
        lines.extend(diff)

    if not lines:
        return True, f"Skill '{name}' has no differences ({from_label} vs {to_label})."
    text = "".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n... (truncated at {max_chars} chars)"
    return True, text


# ---------------------------------------------------------------------------
# Garbage collection
# ---------------------------------------------------------------------------

def gc(grace_seconds: int = _GC_GRACE_SECONDS) -> list[str]:
    """Remove unreferenced objects older than grace_seconds.

    Also cleans up abandoned tmp dirs. Must be called under _store_lock.
    Returns list of removed object digests.
    """
    removed: list[str] = []
    now = time.time()

    # Collect referenced digests
    referenced = {ref.digest for ref in list_refs().values()}

    # Remove unreferenced objects past grace window
    if OBJECTS_DIR.is_dir():
        for obj_dir in OBJECTS_DIR.iterdir():
            if not obj_dir.is_dir():
                continue
            digest = obj_dir.name
            if digest in referenced:
                continue
            age = now - obj_dir.stat().st_mtime
            if age < grace_seconds:
                _log.info("GC: skipping young unreferenced object %s (%.0fs old)", digest[:12], age)
                continue
            _log.info("GC: removing unreferenced object %s (%.0fs old)", digest[:12], age)
            shutil.rmtree(obj_dir, ignore_errors=True)
            removed.append(digest)

    # Clean abandoned tmp dirs
    if TMP_DIR.is_dir():
        for tmp in TMP_DIR.iterdir():
            age = now - tmp.stat().st_mtime
            if age > grace_seconds:
                _log.info("GC: removing stale tmp %s", tmp.name)
                if tmp.is_dir():
                    shutil.rmtree(tmp, ignore_errors=True)
                else:
                    tmp.unlink(missing_ok=True)

    # Clean stale .tmp ref files
    if REFS_DIR.is_dir():
        for p in REFS_DIR.glob("*.json.tmp"):
            age = now - p.stat().st_mtime
            if age > grace_seconds:
                _log.info("GC: removing stale ref tmp %s", p.name)
                p.unlink(missing_ok=True)

    return removed


# ---------------------------------------------------------------------------
# Startup recovery
# ---------------------------------------------------------------------------

def startup_recovery() -> None:
    """Run on startup: ensure dirs, check schema, GC under lock."""
    ensure_managed_dirs()
    check_schema()
    with _store_lock():
        gc()
