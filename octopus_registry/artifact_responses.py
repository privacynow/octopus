from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response

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
            member_path=member_path,
            request=request,
        )
    file_name = str(preferred_name or "").strip() or resolved_path.name
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
