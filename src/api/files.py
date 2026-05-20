from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse

from src.api.deps import get_sessions
from src.security.auth import verify_api_key
from src.sessions.manager import SessionManager

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1", tags=["Files"])

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB


def _meta(request: Request) -> dict[str, Any]:
    return {
        "request_id": getattr(request.state, "request_id", None),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "v1",
    }


async def _resolve_session(sessions: SessionManager, name: str, user_id: Optional[str] = None):
    session = await sessions.get_by_name(name)
    if not session and name.isdigit():
        session = await sessions.get_by_rowid(int(name))
    if not session:
        session = await sessions.get(name)
    if session and user_id and session["user_id"] != user_id:
        return None
    return session


@router.post("/sessions/{name}/files", status_code=201, summary="Upload file to workspace")
async def upload_file(
    name: str,
    request: Request,
    file: UploadFile = File(...),
    path: str = "",
    sessions: SessionManager = Depends(get_sessions),
    api_key: str = Depends(verify_api_key),
):
    """Upload a file to the session workspace."""
    owner = None if api_key == "anonymous" else api_key
    session = await _resolve_session(sessions, name, user_id=owner)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    working_dir = Path(session["working_dir"])

    # Determine target path
    filename = file.filename or "upload"
    if path:
        target = working_dir / path / filename
    else:
        target = working_dir / filename

    target = target.resolve()
    if not target.is_relative_to(working_dir.resolve()):
        raise HTTPException(status_code=400, detail="Path outside session workspace")

    # Size check
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail=f"File exceeds {MAX_UPLOAD_SIZE // 1024 // 1024}MB limit")

    # Write file
    target.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(target.write_bytes, content)

    return {
        "data": {
            "path": str(target.relative_to(working_dir)),
            "size": len(content),
            "name": filename,
        },
        "meta": _meta(request),
    }


@router.get("/sessions/{name}/files", summary="List files in workspace")
async def list_files(
    name: str,
    request: Request,
    path: str = "",
    page: int = 1,
    limit: int = 100,
    sessions: SessionManager = Depends(get_sessions),
    _api_key: str = Depends(verify_api_key),
):
    """List files in session workspace."""
    session = await _resolve_session(sessions, name)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    working_dir = Path(session["working_dir"])
    target = (working_dir / path).resolve() if path else working_dir.resolve()

    if not target.is_relative_to(working_dir.resolve()):
        raise HTTPException(status_code=400, detail="Path outside session workspace")
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    all_entries = []
    for item in sorted(target.iterdir()):
        if item.name.startswith("."):
            continue
        rel = str(item.relative_to(working_dir))
        all_entries.append({
            "name": item.name,
            "path": rel,
            "type": "directory" if item.is_dir() else "file",
            "size": item.stat().st_size if item.is_file() else None,
        })

    total = len(all_entries)
    offset = (max(page, 1) - 1) * limit
    entries = all_entries[offset:offset + limit]

    return {
        "data": entries,
        "path": str(target.relative_to(working_dir)) if target != working_dir else ".",
        "meta": _meta(request),
        "pagination": {"total": total, "page": page, "limit": limit, "pages": max(1, -(-total // limit))},
    }


@router.get("/sessions/{name}/files/{file_path:path}", summary="Download file from workspace")
async def download_file(
    name: str,
    file_path: str,
    sessions: SessionManager = Depends(get_sessions),
    _api_key: str = Depends(verify_api_key),
):
    """Download a file from session workspace."""
    session = await _resolve_session(sessions, name)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    working_dir = Path(session["working_dir"])
    target = (working_dir / file_path).resolve()

    if not target.is_relative_to(working_dir.resolve()):
        raise HTTPException(status_code=400, detail="Path outside session workspace")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=str(target),
        filename=target.name,
    )
