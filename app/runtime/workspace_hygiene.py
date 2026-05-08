"""Bot-side workspace usage and cleanup helpers."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from app.config import BotConfig
from octopus_sdk.registry.management import (
    WorkspaceCleanupEntryRecord,
    WorkspaceCleanupPlanRecord,
    WorkspaceCleanupRequest,
    WorkspaceCleanupResult,
    WorkspaceUsageRequest,
    WorkspaceUsageResult,
)


_BUILD_CACHE_NAMES = {"build", "dist", "target", ".pytest_cache", ".ruff_cache", ".mypy_cache", "__pycache__"}
_DEPENDENCY_CACHE_NAMES = {"node_modules", ".m2", ".gradle", ".npm", ".cache"}
_SCRATCH_NAMES = {".tmp", "tmp", "temp", "scratch", "artifacts-tmp"}
_PROTECTED_PATH_NAMES = {
    ".auth",
    ".claude",
    ".codex",
    ".credentials",
    ".gnupg",
    ".provider-auth",
    ".secrets",
    ".ssh",
    "auth",
    "credentials",
    "provider-auth",
    "secrets",
}
_PROTECTED_FILE_NAMES = {".claude.json", "auth.json", "credentials.json", "secrets.json"}


def _safe_roots(config: BotConfig) -> tuple[Path, ...]:
    roots: list[Path] = []
    for raw in (config.working_dir, config.data_dir, *tuple(config.extra_dirs or ())):
        try:
            root = Path(raw).expanduser().resolve()
        except OSError:
            continue
        if root.exists() and root not in roots:
            roots.append(root)
    return tuple(roots)


def _inside_roots(path: Path, roots: tuple[Path, ...]) -> bool:
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return False
    for root in roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _protected_roots(config: BotConfig) -> tuple[Path, ...]:
    candidates: list[Path] = []
    bases = [Path(config.working_dir), Path(config.data_dir), *tuple(config.extra_dirs or ()), Path.home()]
    for base in bases:
        for name in (".provider-auth", ".codex", ".claude", ".claude.json"):
            candidates.append(Path(base).expanduser() / name)
    if os.environ.get("CODEX_HOME"):
        candidates.append(Path(os.environ["CODEX_HOME"]).expanduser())
    protected: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved not in protected:
            protected.append(resolved)
    return tuple(protected)


def _is_protected_path(path: Path, config: BotConfig, roots: tuple[Path, ...] | None = None) -> bool:
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return True
    for protected in _protected_roots(config):
        if resolved == protected:
            return True
        try:
            resolved.relative_to(protected)
            return True
        except ValueError:
            continue
    for root in roots or _safe_roots(config):
        try:
            relative = resolved.relative_to(root)
        except ValueError:
            continue
        parts = {part.lower() for part in relative.parts}
        if parts.intersection(_PROTECTED_PATH_NAMES | _PROTECTED_FILE_NAMES):
            return True
    return False


def _workspace_root(config: BotConfig, workspace_ref: str) -> Path:
    roots = _safe_roots(config)
    raw = str(workspace_ref or "").strip()
    candidates: list[Path] = []
    if raw:
        candidate = Path(raw).expanduser()
        candidates.append(candidate if candidate.is_absolute() else Path(config.working_dir) / candidate)
    candidates.append(Path(config.working_dir))
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.exists() and _inside_roots(resolved, roots):
            return resolved
    return Path(config.working_dir).resolve()


def _tree_usage(path: Path, *, max_files: int = 10000) -> tuple[int, int]:
    total = 0
    files = 0
    try:
        if path.is_file():
            return path.stat().st_size, 1
        for root, dirs, filenames in os.walk(path):
            dirs[:] = [item for item in dirs if item not in {".git"}]
            for name in filenames:
                files += 1
                if files > max_files:
                    return total, files
                try:
                    total += (Path(root) / name).stat().st_size
                except OSError:
                    continue
    except OSError:
        return 0, 0
    return total, files


def _category_for(path: Path, config: BotConfig, roots: tuple[Path, ...] | None = None) -> tuple[str, bool, str]:
    if _is_protected_path(path, config, roots):
        return "unknown", False, "Auth and credential paths are retained and never cleaned by workspace cleanup."
    name = path.name
    try:
        path.resolve().relative_to((Path(config.data_dir) / "artifact-runtimes").resolve())
        return "runtime_logs", True, "Runtime logs are transient after their tail and events are recorded."
    except (OSError, ValueError):
        pass
    if name in _BUILD_CACHE_NAMES:
        return "build_caches", True, "Build output can be regenerated from retained sources or artifacts."
    if name in _DEPENDENCY_CACHE_NAMES:
        return "dependency_caches", True, "Dependency cache can be recreated by the toolchain."
    if name in _SCRATCH_NAMES:
        return "stage_scratch", True, "Scratch directory is not a declared retained artifact."
    return "unknown", False, "Unknown workspace content needs human review before deletion."


def _entry_already_covered(path: Path, seen_entries: set[str]) -> bool:
    for raw_seen in seen_entries:
        seen_path = Path(raw_seen)
        if path == seen_path:
            return True
        try:
            path.relative_to(seen_path)
            return True
        except ValueError:
            continue
    return False


def _candidate_entries(config: BotConfig, request: WorkspaceUsageRequest) -> list[WorkspaceCleanupEntryRecord]:
    roots = _safe_roots(config)
    workspace = _workspace_root(config, request.workspace_ref)
    requested = {str(item or "").strip() for item in request.categories if str(item or "").strip()}
    entries: list[WorkspaceCleanupEntryRecord] = []

    runtime_logs = Path(config.data_dir) / "artifact-runtimes"
    roots_to_scan = [runtime_logs, workspace]
    seen: set[str] = set()
    seen_entries: set[str] = set()
    for root in roots_to_scan:
        try:
            resolved_root = root.resolve()
        except OSError:
            continue
        if str(resolved_root) in seen or not resolved_root.exists() or not _inside_roots(resolved_root, roots):
            continue
        seen.add(str(resolved_root))
        if _is_protected_path(resolved_root, config, roots):
            continue
        root_category, root_safe, root_reason = _category_for(resolved_root, config, roots)
        if root_category == "runtime_logs":
            size, files = _tree_usage(resolved_root)
            if not requested or root_category in requested:
                entry_path = str(resolved_root)
                if not _entry_already_covered(resolved_root, seen_entries):
                    seen_entries.add(entry_path)
                    entries.append(WorkspaceCleanupEntryRecord(
                        path=entry_path,
                        category=root_category,
                        size_bytes=size,
                        file_count=files,
                        safe_to_delete=root_safe,
                        reason=root_reason,
                    ))
            continue

        for current, dirs, _files in os.walk(resolved_root):
            current_path = Path(current)
            dirs[:] = [
                dirname
                for dirname in dirs
                if not _is_protected_path(current_path / dirname, config, roots)
            ]
            depth = len(current_path.relative_to(resolved_root).parts)
            if depth > 5:
                dirs[:] = []
                continue
            for dirname in list(dirs):
                candidate = current_path / dirname
                category, safe, reason = _category_for(candidate, config, roots)
                if category == "unknown":
                    continue
                if requested and category not in requested:
                    continue
                resolved_candidate = candidate.resolve()
                if _entry_already_covered(resolved_candidate, seen_entries):
                    continue
                entry_path = str(resolved_candidate)
                seen_entries.add(entry_path)
                size, files = _tree_usage(candidate)
                entries.append(WorkspaceCleanupEntryRecord(
                    path=entry_path,
                    category=category,
                    size_bytes=size,
                    file_count=files,
                    safe_to_delete=safe,
                    reason=reason,
                ))
                if len(entries) >= request.max_entries:
                    return entries
    return entries


async def workspace_usage(request: WorkspaceUsageRequest, *, config: BotConfig) -> WorkspaceUsageResult:
    entries = _candidate_entries(config, request)
    total_bytes = sum(max(0, int(item.size_bytes or 0)) for item in entries)
    deletable_bytes = sum(max(0, int(item.size_bytes or 0)) for item in entries if item.safe_to_delete)
    file_count = sum(max(0, int(item.file_count or 0)) for item in entries)
    unknown_bytes = sum(max(0, int(item.size_bytes or 0)) for item in entries if item.category == "unknown")
    transient_bytes = sum(
        max(0, int(item.size_bytes or 0))
        for item in entries
        if item.category in {"runtime_logs", "build_caches", "dependency_caches", "stage_scratch"}
    )
    plan = WorkspaceCleanupPlanRecord(
        agent_id="",
        workspace_ref=request.workspace_ref,
        protocol_run_id=request.protocol_run_id,
        categories=list(request.categories),
        entries=entries,
        total_bytes=total_bytes,
        retained_bytes=max(0, total_bytes - deletable_bytes),
        transient_bytes=transient_bytes,
        unknown_bytes=unknown_bytes,
        deletable_bytes=deletable_bytes,
        file_count=file_count,
        warnings=[] if entries else ["No cleanup candidates were found inside approved bot workspace roots."],
    )
    return WorkspaceUsageResult(plan=plan)


async def workspace_cleanup(request: WorkspaceCleanupRequest, *, config: BotConfig) -> WorkspaceCleanupResult:
    if str(request.confirm or "").strip().upper() != "CLEAN":
        raise RuntimeError("Workspace cleanup requires confirm=CLEAN.")
    roots = _safe_roots(config)
    verification_request = WorkspaceUsageRequest(
        workspace_ref=request.plan.workspace_ref,
        protocol_run_id=request.plan.protocol_run_id,
        categories=list(request.plan.categories),
        max_entries=max(250, len(request.plan.entries)),
    )
    verified_entries = {
        str(Path(item.path).expanduser().resolve()): item
        for item in _candidate_entries(config, verification_request)
        if item.safe_to_delete
    }
    removed_paths: list[str] = []
    failures: list[str] = []
    removed_bytes = 0
    allowed_categories = {str(item or "").strip() for item in request.plan.categories if str(item or "").strip()}
    for entry in request.plan.entries:
        if not entry.safe_to_delete:
            continue
        if allowed_categories and entry.category not in allowed_categories:
            continue
        path = Path(entry.path).expanduser()
        try:
            resolved = path.resolve()
        except OSError as exc:
            failures.append(f"{entry.path}: {exc}")
            continue
        if resolved in roots or not _inside_roots(resolved, roots):
            failures.append(f"{entry.path}: refused outside approved workspace roots")
            continue
        if _is_protected_path(resolved, config, roots):
            failures.append(f"{entry.path}: refused protected auth or credential path")
            continue
        if path.is_symlink() or resolved.is_symlink():
            failures.append(f"{entry.path}: refused symlink cleanup")
            continue
        if not resolved.exists():
            continue
        verified = verified_entries.get(str(resolved))
        if verified is None:
            failures.append(f"{entry.path}: refused unverified cleanup candidate")
            continue
        if allowed_categories and verified.category not in allowed_categories:
            continue
        try:
            size, _files = _tree_usage(resolved)
            if resolved.is_dir():
                shutil.rmtree(resolved)
            else:
                resolved.unlink()
            removed_paths.append(str(resolved))
            removed_bytes += size
        except OSError as exc:
            failures.append(f"{entry.path}: {exc}")
    refreshed_entries = [entry for entry in request.plan.entries if str(entry.path) not in set(removed_paths)]
    plan = request.plan.model_copy(update={
        "entries": refreshed_entries,
        "deletable_bytes": max(0, int(request.plan.deletable_bytes or 0) - removed_bytes),
        "total_bytes": max(0, int(request.plan.total_bytes or 0) - removed_bytes),
    })
    return WorkspaceCleanupResult(
        plan=plan,
        removed_paths=removed_paths,
        removed_bytes=removed_bytes,
        failures=failures,
    )
