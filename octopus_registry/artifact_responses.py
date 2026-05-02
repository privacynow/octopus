from __future__ import annotations

import mimetypes
from html import escape
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

from .artifact_paths import (
    artifact_directory_download_name,
    directory_artifact_index_html,
    directory_artifact_zip_bytes,
    resolve_directory_artifact_member,
)


def workspace_artifact_content_response(
    *,
    resolved_path: Path,
    artifact_key: str,
    preferred_path: str = "",
    preferred_name: str = "",
    download: bool = False,
    browse: bool = False,
    preview: bool = False,
    member_path: str = "",
    request: Request | None = None,
) -> Response:
    if resolved_path.is_dir():
        return _directory_artifact_response(
            resolved_path=resolved_path,
            artifact_key=artifact_key,
            preferred_path=preferred_path,
            download=download,
            browse=browse,
            preview=preview,
            member_path=member_path,
            request=request,
        )
    file_name = str(preferred_name or "").strip() or resolved_path.name
    if preview and not download:
        preview_response = rendered_artifact_preview_response(
            resolved_path=resolved_path,
            artifact_key=artifact_key,
            preferred_name=file_name,
        )
        if preview_response is not None:
            return preview_response
    media_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    return FileResponse(
        path=resolved_path,
        media_type=media_type,
        filename=file_name,
        content_disposition_type="attachment" if download else "inline",
    )


def _directory_artifact_response(
    *,
    resolved_path: Path,
    artifact_key: str,
    preferred_path: str,
    download: bool,
    browse: bool,
    preview: bool,
    member_path: str,
    request: Request | None,
) -> Response:
    requested_member_path = str(member_path or "").strip()
    if requested_member_path:
        member = resolve_directory_artifact_member(resolved_path, requested_member_path)
        if member is None:
            raise HTTPException(status_code=404, detail="Directory artifact member not found.")
        if member.is_dir():
            return _directory_listing_response(
                resolved_path=resolved_path,
                artifact_key=artifact_key,
                request=request,
            )
        if preview and not download:
            preview_response = rendered_artifact_preview_response(
                resolved_path=member,
                artifact_key=artifact_key,
                preferred_name=member.name,
            )
            if preview_response is not None:
                return preview_response
        media_type = mimetypes.guess_type(member.name)[0] or "application/octet-stream"
        return FileResponse(
            path=member,
            media_type=media_type,
            filename=member.name,
            content_disposition_type="attachment" if download else "inline",
        )

    if download:
        zip_name = artifact_directory_download_name(
            artifact_key=str(artifact_key or ""),
            preferred_path=preferred_path or str(resolved_path.name or ""),
        )
        return Response(
            content=directory_artifact_zip_bytes(resolved_path),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
        )

    if not browse:
        index_path = resolved_path / "index.html"
        if index_path.is_file():
            if request is not None and not str(request.url.path).endswith("/"):
                target = f"{request.url.path}/"
                if request.url.query:
                    target = f"{target}?{request.url.query}"
                return RedirectResponse(url=target, status_code=307)
            return FileResponse(
                path=index_path,
                media_type="text/html",
                filename="index.html",
                content_disposition_type="inline",
            )

    return _directory_listing_response(
        resolved_path=resolved_path,
        artifact_key=artifact_key,
        request=request,
    )


def _directory_listing_response(
    *,
    resolved_path: Path,
    artifact_key: str,
    request: Request | None,
) -> Response:
    base_href = str(request.url.path if request is not None else "").strip()
    title = str(resolved_path.name or artifact_key or "Artifact contents").strip()
    return Response(
        content=directory_artifact_index_html(
            resolved_path,
            artifact_title=title,
            base_href=base_href,
        ).encode("utf-8"),
        media_type="text/html",
        headers={"Content-Disposition": f'inline; filename="{title}.html"'},
    )


def rendered_artifact_preview_response(
    *,
    resolved_path: Path,
    artifact_key: str,
    preferred_name: str = "",
) -> Response | None:
    file_name = str(preferred_name or resolved_path.name or artifact_key or "artifact").strip()
    suffix = resolved_path.suffix.lower()
    if suffix not in {
        ".md",
        ".markdown",
        ".txt",
        ".log",
        ".json",
        ".jsonl",
        ".yaml",
        ".yml",
        ".csv",
        ".tsv",
        ".py",
        ".js",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".jsx",
        ".sh",
        ".sql",
        ".rb",
        ".go",
        ".java",
        ".rs",
        ".php",
    }:
        return None
    try:
        raw = resolved_path.read_bytes()
    except OSError:
        return None
    return rendered_artifact_text_preview_response(
        raw,
        artifact_key=artifact_key,
        preferred_name=file_name,
    )


def rendered_artifact_text_preview_response(
    content: bytes | str,
    *,
    artifact_key: str,
    preferred_name: str = "",
) -> Response:
    file_name = str(preferred_name or artifact_key or "artifact").strip()
    if isinstance(content, bytes):
        text = content.decode("utf-8", errors="replace")
    else:
        text = str(content or "")
    max_chars = 280_000
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]
    suffix = Path(file_name).suffix.lower()
    if suffix in {".md", ".markdown"}:
        body = _render_basic_markdown(text)
    else:
        body = f"<pre>{escape(text)}</pre>"
    if truncated:
        body += "<p class=\"note\">Preview truncated. Download the artifact to inspect the full file.</p>"
    title = file_name or artifact_key or "Artifact preview"
    html = "\n".join(
        [
            "<!doctype html>",
            "<html lang=\"en\">",
            "<head>",
            "<meta charset=\"utf-8\">",
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
            f"<title>{escape(title)}</title>",
            "<style>",
            "body{margin:0;padding:32px;font:15px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f7f8fb;color:#172033;}",
            "main{max-width:960px;margin:0 auto;background:#fff;border:1px solid #dbe1ec;border-radius:8px;padding:28px;box-shadow:0 16px 40px rgba(20,31,54,.08);}",
            "h1{margin:0 0 18px;font-size:24px;line-height:1.2;}",
            "h2{margin:26px 0 10px;font-size:19px;}",
            "h3{margin:22px 0 8px;font-size:16px;}",
            "p{margin:0 0 12px;}",
            "ul,ol{margin:0 0 14px 22px;padding:0;}",
            "li{margin:4px 0;}",
            "pre{white-space:pre-wrap;overflow:auto;margin:0 0 14px;padding:14px;border:1px solid #dbe1ec;border-radius:6px;background:#f2f5f9;color:#102033;}",
            "code{font-family:'SFMono-Regular',Consolas,monospace;font-size:.92em;}",
            ".note{margin-top:18px;padding:10px 12px;border:1px solid #dbe1ec;border-radius:6px;background:#f7f8fb;color:#5f6b7a;}",
            "</style>",
            "</head>",
            "<body>",
            "<main>",
            f"<h1>{escape(title)}</h1>",
            body,
            "</main>",
            "</body>",
            "</html>",
        ]
    )
    return Response(
        content=html.encode("utf-8"),
        media_type="text/html",
        headers={"Content-Disposition": f'inline; filename="{Path(title).stem or "artifact"}-preview.html"'},
    )


def _render_basic_markdown(text: str) -> str:
    lines = str(text or "").splitlines()
    parts: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    code_lines: list[str] = []
    in_code = False

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            parts.append(f"<p>{escape(' '.join(paragraph))}</p>")
            paragraph = []

    def flush_list() -> None:
        nonlocal list_items
        if list_items:
            parts.append("<ul>" + "".join(f"<li>{escape(item)}</li>" for item in list_items) + "</ul>")
            list_items = []

    def flush_code() -> None:
        nonlocal code_lines
        parts.append(f"<pre><code>{escape(chr(10).join(code_lines))}</code></pre>")
        code_lines = []

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code:
                flush_code()
                in_code = False
            else:
                flush_paragraph()
                flush_list()
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        if not stripped:
            flush_paragraph()
            flush_list()
            continue
        if stripped.startswith("### "):
            flush_paragraph()
            flush_list()
            parts.append(f"<h3>{escape(stripped[4:].strip())}</h3>")
            continue
        if stripped.startswith("## "):
            flush_paragraph()
            flush_list()
            parts.append(f"<h2>{escape(stripped[3:].strip())}</h2>")
            continue
        if stripped.startswith("# "):
            flush_paragraph()
            flush_list()
            parts.append(f"<h2>{escape(stripped[2:].strip())}</h2>")
            continue
        if stripped.startswith(("- ", "* ")):
            flush_paragraph()
            list_items.append(stripped[2:].strip())
            continue
        paragraph.append(stripped)
    if in_code:
        flush_code()
    flush_paragraph()
    flush_list()
    return "\n".join(parts) or "<p>No previewable text.</p>"
