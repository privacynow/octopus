from __future__ import annotations

from collections.abc import Iterable
from html import escape
from io import BytesIO
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode
from zipfile import ZIP_DEFLATED, ZipFile

from octopus_sdk.protocols import ProtocolArtifactRecord, ProtocolRunDetailRecord
from octopus_sdk.registry.models import TaskRecord


def _resolve_artifact_file_path(
    *,
    candidate_paths: Iterable[str],
    candidate_roots: Iterable[str],
) -> Path | None:
    normalized_paths = [str(item or "").strip() for item in candidate_paths if str(item or "").strip()]
    normalized_roots = [str(item or "").strip() for item in candidate_roots if str(item or "").strip()]

    for candidate in normalized_paths:
        path = Path(candidate)
        if path.is_absolute() and (path.is_file() or path.is_dir()):
            return path

    relative_path = next((item for item in normalized_paths if not Path(item).is_absolute()), "")
    if not relative_path:
        return None

    relative_candidate = Path(relative_path)
    for root in normalized_roots:
        root_path = Path(root)
        if not root_path.is_absolute():
            continue
        try:
            resolved = (root_path / relative_candidate).resolve()
            resolved.relative_to(root_path.resolve())
        except Exception:
            continue
        if resolved.is_file() or resolved.is_dir():
            return resolved
    return None


def _resolve_artifact_target_path(
    *,
    candidate_path: str,
    candidate_roots: Iterable[str],
) -> Path | None:
    normalized_path = str(candidate_path or "").strip()
    if not normalized_path:
        return None
    direct = Path(normalized_path)
    if direct.is_absolute():
        parent = direct.parent
        return direct if parent.is_dir() else None
    relative_candidate = Path(normalized_path)
    for root in candidate_roots:
        root_path = Path(str(root or "").strip())
        if not root_path.is_absolute():
            continue
        try:
            resolved = (root_path / relative_candidate).resolve()
            resolved.relative_to(root_path.resolve())
        except Exception:
            continue
        return resolved
    return None


@lru_cache(maxsize=1)
def _mounted_workspace_roots() -> tuple[str, ...]:
    workspace_parent = Path("/workspace")
    if not workspace_parent.is_dir():
        return ()
    return tuple(
        str(child)
        for child in sorted(workspace_parent.iterdir())
        if child.is_dir()
    )


def _artifact_body_from_full_text(full_text: str) -> str:
    body_lines: list[str] = []
    for line in str(full_text or "").splitlines():
        marker = line.strip().upper()
        if marker.startswith("PROTOCOL_DECISION:") or marker.startswith("PROTOCOL_SUMMARY:"):
            continue
        body_lines.append(line.rstrip())
    return "\n".join(body_lines).strip()


def _result_payload_artifact_content(result_payload: object, artifact_key: str) -> str:
    if not isinstance(result_payload, dict):
        return ""
    target_key = str(artifact_key or "").strip()
    if not target_key:
        return ""
    artifact_contents = result_payload.get("artifact_contents", ())
    if not isinstance(artifact_contents, list):
        return ""
    for item in artifact_contents:
        if not isinstance(item, dict):
            continue
        if str(item.get("artifact_key", "") or "").strip() != target_key:
            continue
        content = str(item.get("content", "") or "")
        if content:
            return content
    return ""


def artifact_download_name(*, artifact_key: str, preferred_path: str = "") -> str:
    candidate = str(preferred_path or "").strip()
    if candidate:
        name = Path(candidate).name.strip()
        if name:
            return name
    return str(artifact_key or "").strip() or "artifact"


def artifact_directory_download_name(*, artifact_key: str, preferred_path: str = "") -> str:
    candidate = artifact_download_name(artifact_key=artifact_key, preferred_path=preferred_path)
    if candidate.lower().endswith(".zip"):
        return candidate
    return f"{candidate}.zip"


def directory_artifact_manifest(path: Path) -> str:
    lines = [f"# {path.name or 'artifact'}", "", "Directory artifact contents:", ""]
    entries: list[str] = []
    for child in sorted(path.rglob("*")):
        if child.is_symlink() or not child.is_file():
            continue
        try:
            relative_child = child.resolve().relative_to(path.resolve()).as_posix()
        except Exception:
            continue
        entries.append(f"- {relative_child} ({child.stat().st_size} bytes)")
    if entries:
        lines.extend(entries)
    else:
        lines.append("- No files found.")
    lines.append("")
    return "\n".join(lines)


def directory_artifact_index_html(
    path: Path,
    *,
    artifact_title: str,
    base_href: str,
    max_entries: int = 500,
) -> str:
    root = path.resolve()
    title = str(artifact_title or path.name or "Artifact contents").strip()
    base = str(base_href or "").strip() or "."
    entries: list[tuple[str, int]] = []
    truncated = False
    for child in sorted(path.rglob("*")):
        if child.is_symlink() or not child.is_file():
            continue
        try:
            relative_child = child.resolve().relative_to(root).as_posix()
        except Exception:
            continue
        if len(entries) >= max_entries:
            truncated = True
            break
        entries.append((relative_child, child.stat().st_size))

    def href_for(relative_path: str, *, download: bool = False) -> str:
        params: dict[str, str] = {"path": relative_path}
        if download:
            params["download"] = "1"
        return f"{base}?{urlencode(params)}"

    rows = []
    for relative_child, size_bytes in entries:
        rows.append(
            "<tr>"
            f"<td><a href=\"{escape(href_for(relative_child), quote=True)}\">{escape(relative_child)}</a></td>"
            f"<td>{size_bytes:,} bytes</td>"
            f"<td><a href=\"{escape(href_for(relative_child, download=True), quote=True)}\">Download</a></td>"
            "</tr>"
        )
    if not rows:
        rows.append("<tr><td colspan=\"3\">No files found.</td></tr>")

    truncated_note = (
        f"<p class=\"note\">Showing the first {max_entries:,} files. Download the package to inspect every file.</p>"
        if truncated
        else ""
    )
    return "\n".join(
        [
            "<!doctype html>",
            "<html lang=\"en\">",
            "<head>",
            "<meta charset=\"utf-8\">",
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
            f"<title>{escape(title)}</title>",
            "<style>",
            "body{margin:0;padding:32px;font:14px/1.45 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f7f8fb;color:#172033;}",
            "main{max-width:1040px;margin:0 auto;display:grid;gap:18px;}",
            "header{display:grid;gap:8px;}",
            "h1{margin:0;font-size:24px;line-height:1.2;}",
            "p{margin:0;color:#5f6b7a;}",
            ".actions{display:flex;flex-wrap:wrap;gap:10px;}",
            "a{color:#2458d3;text-decoration:none;font-weight:600;}",
            "a:hover{text-decoration:underline;}",
            ".button{display:inline-flex;align-items:center;min-height:34px;padding:0 12px;border:1px solid #cfd6e4;border-radius:6px;background:#fff;color:#172033;}",
            "table{width:100%;border-collapse:collapse;background:#fff;border:1px solid #dbe1ec;border-radius:8px;overflow:hidden;}",
            "th,td{padding:10px 12px;text-align:left;border-bottom:1px solid #e6ebf3;vertical-align:top;}",
            "th{font-size:12px;text-transform:uppercase;letter-spacing:0;color:#667085;background:#f0f3f8;}",
            "td:nth-child(2){white-space:nowrap;color:#667085;}",
            "tr:last-child td{border-bottom:0;}",
            ".note{padding:10px 12px;border:1px solid #dbe1ec;border-radius:6px;background:#fff;}",
            "</style>",
            "</head>",
            "<body>",
            "<main>",
            "<header>",
            f"<h1>{escape(title)}</h1>",
            "<p>Directory artifact contents. Open individual files inline or download the complete package.</p>",
            "<div class=\"actions\">",
            f"<a class=\"button\" href=\"{escape(base, quote=True)}\">Open default</a>",
            f"<a class=\"button\" href=\"{escape(base + '?download=1', quote=True)}\">Download package</a>",
            "</div>",
            "</header>",
            truncated_note,
            "<table>",
            "<thead><tr><th>File</th><th>Size</th><th>Action</th></tr></thead>",
            "<tbody>",
            *rows,
            "</tbody>",
            "</table>",
            "</main>",
            "</body>",
            "</html>",
        ]
    )


def directory_artifact_zip_bytes(path: Path) -> bytes:
    buffer = BytesIO()
    root = path.resolve()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for child in sorted(path.rglob("*")):
            if child.is_symlink() or not child.is_file():
                continue
            try:
                resolved_child = child.resolve()
                relative_child = resolved_child.relative_to(root).as_posix()
            except Exception:
                continue
            archive.write(resolved_child, arcname=relative_child)
    return buffer.getvalue()


def resolve_directory_artifact_member(root: Path, relative_path: str) -> Path | None:
    normalized = str(relative_path or "").strip().replace("\\", "/")
    if not normalized:
        return root if root.exists() else None
    candidate = Path(normalized)
    if candidate.is_absolute():
        return None
    try:
        resolved_root = root.resolve()
        resolved = (root / candidate).resolve()
        resolved.relative_to(resolved_root)
    except Exception:
        return None
    if not resolved.exists() or resolved.is_symlink():
        return None
    return resolved


def resolve_workspace_artifact_target(*, workspace_ref: str = "", artifact_path: str = "") -> Path | None:
    return _resolve_artifact_target_path(
        candidate_path=artifact_path,
        candidate_roots=[
            str(workspace_ref or "").strip(),
            *_mounted_workspace_roots(),
        ],
    )


def resolve_protocol_artifact_path(detail: ProtocolRunDetailRecord, artifact: ProtocolArtifactRecord) -> Path | None:
    produced_stage_id = str(artifact.produced_by_stage_execution_id or "").strip()
    candidate_roots: list[str] = []
    if produced_stage_id:
        for task in detail.tasks or []:
            if str(task.protocol_stage_execution_id or "").strip() != produced_stage_id:
                continue
            candidate_roots.extend([
                str(task.working_dir or "").strip(),
                str(task.project_id_override or "").strip(),
            ])
            break
    candidate_roots.extend([
        str(detail.run.workspace_ref or "").strip(),
        str(detail.run.repo_ref or "").strip(),
    ])
    candidate_roots.extend(_mounted_workspace_roots())
    return _resolve_artifact_file_path(
        candidate_paths=[
            str(artifact.location or "").strip(),
            str(artifact.workspace_path or "").strip(),
        ],
        candidate_roots=candidate_roots,
    )


def resolve_protocol_artifact_rehearsal_text(
    detail: ProtocolRunDetailRecord,
    artifact: ProtocolArtifactRecord,
) -> str:
    if not bool(getattr(detail.run, "is_rehearsal", False)):
        return ""
    produced_stage_id = str(artifact.produced_by_stage_execution_id or "").strip()
    for task in detail.tasks or ():
        if produced_stage_id and str(task.protocol_stage_execution_id or "").strip() != produced_stage_id:
            continue
        if task.result is None:
            continue
        result_payload = task.result.as_dict()
        if not isinstance(result_payload, dict):
            continue
        content = _result_payload_artifact_content(result_payload, str(artifact.artifact_key or ""))
        if content:
            return content
        body = _artifact_body_from_full_text(str(result_payload.get("full_text", "") or ""))
        if body:
            return body
    return ""


def resolve_task_artifact_path(
    task: TaskRecord,
    artifact_key: str,
    *,
    run_detail: ProtocolRunDetailRecord | None = None,
) -> Path | None:
    result_payload = task.result.as_dict() if task.result is not None else {}
    artifacts = result_payload.get("artifacts", ()) if isinstance(result_payload, dict) else ()
    if not isinstance(artifacts, list):
        return None
    artifact = next(
        (
            item for item in artifacts
            if isinstance(item, dict) and str(item.get("artifact_key", "") or "").strip() == str(artifact_key or "").strip()
        ),
        None,
    )
    if artifact is None:
        return None
    candidate_roots = [
        str(task.working_dir or result_payload.get("working_dir", "") or "").strip(),
        str(task.project_id_override or "").strip(),
    ]
    if run_detail is not None:
        candidate_roots.extend([
            str(run_detail.run.workspace_ref or "").strip(),
            str(run_detail.run.repo_ref or "").strip(),
        ])
    candidate_roots.extend(_mounted_workspace_roots())
    return _resolve_artifact_file_path(
        candidate_paths=[str(artifact.get("path", "") or "").strip()],
        candidate_roots=candidate_roots,
    )


def resolve_task_artifact_rehearsal_text(
    task: TaskRecord,
    artifact_key: str,
    *,
    run_detail: ProtocolRunDetailRecord | None = None,
) -> str:
    if run_detail is None or not bool(getattr(run_detail.run, "is_rehearsal", False)):
        return ""
    result_payload = task.result.as_dict() if task.result is not None else {}
    artifacts = result_payload.get("artifacts", ()) if isinstance(result_payload, dict) else ()
    if not isinstance(artifacts, list):
        return ""
    matched = any(
        isinstance(item, dict) and str(item.get("artifact_key", "") or "").strip() == str(artifact_key or "").strip()
        for item in artifacts
    )
    if not matched:
        return ""
    content = _result_payload_artifact_content(result_payload, artifact_key)
    if content:
        return content
    return _artifact_body_from_full_text(str(result_payload.get("full_text", "") or ""))
