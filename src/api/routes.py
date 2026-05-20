from __future__ import annotations

import asyncio
import json
import shutil
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from src.api.deps import get_claude, get_sessions
from src.claude.client import ClaudeClient, ClaudeResponse, StreamUpdate
from src.claude.exceptions import ClaudeError, ClaudeTimeoutError
from src.api.extras import moderate_input
from sqlalchemy import text
from src.config import _csv_to_list
from src.security.auth import rate_limiter, verify_api_key
from src.sessions.manager import SessionManager

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1")

# Idempotency cache: key -> (timestamp, response_data)
# NOTE: In-memory, per-worker. For multi-worker deployments, replace with Redis.
_idempotency_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_IDEMPOTENCY_TTL = 300  # 5 minutes
_IDEMPOTENCY_MAX_SIZE = 1000


def _idempotency_cleanup() -> None:
    """Evict expired entries. Called before insert."""
    now = _time.time()
    expired = [k for k, (ts, _) in _idempotency_cache.items() if now - ts >= _IDEMPOTENCY_TTL]
    for k in expired:
        del _idempotency_cache[k]
    # Hard cap: evict oldest if still over limit
    while len(_idempotency_cache) > _IDEMPOTENCY_MAX_SIZE:
        oldest_key = min(_idempotency_cache, key=lambda k: _idempotency_cache[k][0])
        del _idempotency_cache[oldest_key]


# -- Schemas --


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# -- Request Models --


class ChatRequest(BaseModel):
    model_config = {"extra": "forbid"}

    message: str = Field(..., min_length=1, max_length=1_000_000)
    model: Optional[str] = Field(None, max_length=100, description="Model override for this request")
    system: Optional[str] = Field(None, max_length=50_000, description="System prompt override")
    effort: Optional[str] = Field(None, description="Thinking effort: low, medium, high, max")
    permission_mode: Optional[str] = Field(None, description="Permission mode: default, plan, bypassPermissions")
    output_format: Optional[dict[str, Any]] = Field(None, description="Structured output format (JSON schema)")


class SessionCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(..., min_length=1, max_length=128, description="Project name — subdirectory under APPROVED_DIRECTORY")
    template: Optional[str] = Field(None, description="Template name (e.g. code-reviewer, devops, debug). Fills defaults.")
    user_id: str = Field("default", max_length=128)
    system_prompt: Optional[str] = Field(None, max_length=50_000, description="Custom system prompt (overrides template)")
    model: Optional[str] = Field(None, max_length=100, description="Model override")
    max_turns: Optional[int] = Field(None, ge=1, le=100, description="Max turns per chat")
    permission_mode: Optional[str] = Field(None, description="Permission mode: default, plan, bypassPermissions")
    effort: Optional[str] = Field(None, description="Thinking effort: low, medium, high, max")
    allowed_tools: Optional[str] = Field(None, description="Comma-separated allowed tools override")
    disallowed_tools: Optional[str] = Field(None, description="Comma-separated disallowed tools")


class RepoRequest(BaseModel):
    model_config = {"extra": "forbid"}

    working_dir: str = Field(..., max_length=1024)


# -- Response Models --


class SessionData(BaseModel):
    model_config = {"extra": "ignore"}

    name: str
    user_id: str
    working_dir: str
    system_prompt: Optional[str] = None
    model: Optional[str] = None
    max_turns: Optional[int] = None
    permission_mode: Optional[str] = None
    effort: Optional[str] = None
    allowed_tools: Optional[str] = None
    disallowed_tools: Optional[str] = None
    status: str = "pending"
    total_cost: float = 0.0
    total_turns: int = 0
    created_at: str
    updated_at: str

    @classmethod
    def from_db(cls, row: dict) -> "SessionData":
        status = "active" if row.get("id") else "pending"
        return cls(
            name=row["name"],
            user_id=row["user_id"],
            working_dir=row["working_dir"],
            system_prompt=row.get("system_prompt"),
            model=row.get("model"),
            max_turns=row.get("max_turns"),
            permission_mode=row.get("permission_mode"),
            effort=row.get("effort"),
            allowed_tools=row.get("allowed_tools"),
            disallowed_tools=row.get("disallowed_tools"),
            status=status,
            total_cost=row.get("total_cost", 0.0),
            total_turns=row.get("total_turns", 0),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class ChatData(BaseModel):
    session_id: str
    content: str
    cost: float = 0.0
    duration_ms: int = 0
    num_turns: int = 0
    tools_used: list[dict[str, Any]] = []


class MessageData(BaseModel):
    model_config = {"extra": "ignore"}
    role: str
    content: str
    tools_used: Optional[list[dict[str, Any]]] = None
    cost: float = 0.0
    duration_ms: int = 0
    created_at: str


# -- Envelope Wrappers --


class MetaInfo(BaseModel):
    request_id: Optional[str] = None
    timestamp: str
    version: str = "v1"


class SessionEnvelope(BaseModel):
    data: SessionData
    meta: MetaInfo


class ChatEnvelope(BaseModel):
    data: ChatData
    meta: MetaInfo


class SessionListEnvelope(BaseModel):
    data: list[SessionData]
    meta: MetaInfo
    pagination: dict[str, int]


class HistoryEnvelope(BaseModel):
    data: list[MessageData]
    meta: MetaInfo
    session_id: str
    count: int


def _meta(request: Optional[Request] = None) -> MetaInfo:
    request_id = None
    if request:
        request_id = getattr(request.state, "request_id", None)
    return MetaInfo(request_id=request_id, timestamp=_now_iso())


# -- Health --


@router.get("/health", tags=["Health"], summary="Health check")
async def health(
    request: Request,
    sessions: SessionManager = Depends(get_sessions),
):
    checks: dict[str, str] = {}
    try:
        async with sessions.db.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"

    found = await asyncio.to_thread(shutil.which, "claude")
    checks["claude_cli"] = "ok" if found else "not_found"

    all_ok = all(v == "ok" for v in checks.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "checks": checks,
        "meta": _meta(request).model_dump(),
    }


# -- Chat --


@router.post("/sessions/{name}/chat", response_model=ChatEnvelope, tags=["Chat"], summary="Send message (sync)")
async def chat(
    name: str,
    req: ChatRequest,
    request: Request,
    sessions: SessionManager = Depends(get_sessions),
    claude: ClaudeClient = Depends(get_claude),
    api_key: str = Depends(verify_api_key),
):
    rate_limiter.check(api_key)

    # Input moderation
    safe, reason = moderate_input(req.message)
    if not safe:
        raise HTTPException(status_code=400, detail=reason)

    # Idempotency check
    idem_key = request.headers.get("Idempotency-Key")
    if idem_key:
        cached = _idempotency_cache.get(idem_key)
        if cached:
            ts, data = cached
            if _time.time() - ts < _IDEMPOTENCY_TTL:
                return ChatEnvelope(data=ChatData(**data), meta=_meta(request))
            del _idempotency_cache[idem_key]

    owner = None if api_key == "anonymous" else api_key
    session = await _resolve_session(sessions, name, user_id=owner)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        await sessions.check_user_budget(session["user_id"])
    except ValueError as e:
        raise HTTPException(status_code=429, detail=str(e))

    working_dir = Path(session["working_dir"])
    claude_sid = session["id"] or None

    if not claude_sid:
        resumable = await sessions.find_resumable(session["user_id"], str(working_dir))
        if resumable:
            claude_sid = resumable["id"]

    should_resume = bool(claude_sid)

    # Per-request overrides > session config > global config
    effective_model = req.model or session.get("model")
    effective_system = req.system or session.get("system_prompt")
    effective_effort = req.effort or session.get("effort")
    effective_perm = req.permission_mode or session.get("permission_mode")
    effective_allowed = (
        _csv_to_list(session.get("allowed_tools")) if session.get("allowed_tools") else None
    )
    effective_disallowed = (
        _csv_to_list(session.get("disallowed_tools")) if session.get("disallowed_tools") else None
    )
    effective_max_turns = session.get("max_turns")

    execute_kwargs: dict[str, Any] = dict(
        prompt=req.message,
        working_directory=working_dir,
        model_override=effective_model,
        system_override=effective_system,
        effort=effective_effort,
        permission_mode=effective_perm,
        output_format=req.output_format,
        allowed_tools_override=effective_allowed,
        disallowed_tools_override=effective_disallowed,
        max_turns_override=effective_max_turns,
    )

    try:
        try:
            response = await claude.execute(
                session_id=claude_sid,
                continue_session=should_resume,
                **execute_kwargs,
            )
        except Exception as e:
            if should_resume:
                logger.warning("resume_failed_retrying_fresh", error=str(e), session_id=claude_sid)
                response = await claude.execute(
                    session_id=None,
                    continue_session=False,
                    **execute_kwargs,
                )
            else:
                raise
    except ClaudeTimeoutError:
        raise HTTPException(status_code=504, detail="Claude timed out")
    except ClaudeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    old_cost = float(session.get("total_cost", 0.0))
    old_turns = int(session.get("total_turns", 0))
    await sessions.db.save_interaction(
        session_rowid=session["rowid"],
        new_session_id=response.session_id if not session["id"] else None,
        total_cost=old_cost + response.cost,
        total_turns=old_turns + response.num_turns,
        user_message=req.message,
        assistant_content=response.content,
        tools_used=response.tools_used,
        cost=response.cost,
        duration_ms=response.duration_ms,
    )

    chat_data = ChatData(
        session_id=response.session_id,
        content=response.content,
        cost=response.cost,
        duration_ms=response.duration_ms,
        num_turns=response.num_turns,
        tools_used=response.tools_used,
    )

    if idem_key:
        _idempotency_cleanup()
        _idempotency_cache[idem_key] = (_time.time(), chat_data.model_dump())

    return ChatEnvelope(data=chat_data, meta=_meta(request))


@router.post("/sessions/{name}/chat/stream", tags=["Chat"], summary="Send message (SSE stream)")
async def chat_stream(
    name: str,
    req: ChatRequest,
    sessions: SessionManager = Depends(get_sessions),
    claude: ClaudeClient = Depends(get_claude),
    api_key: str = Depends(verify_api_key),
):
    rate_limiter.check(api_key)

    owner = None if api_key == "anonymous" else api_key
    session = await _resolve_session(sessions, name, user_id=owner)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        await sessions.check_user_budget(session["user_id"])
    except ValueError as e:
        raise HTTPException(status_code=429, detail=str(e))

    if not session["id"]:
        resumable = await sessions.find_resumable(session["user_id"], session["working_dir"])
        if resumable:
            session["id"] = resumable["id"]

    return EventSourceResponse(
        _stream_chat(req, session, sessions, claude),
        media_type="text/event-stream",
        ping=15,  # heartbeat every 15s to keep connection alive
    )


async def _stream_chat(
    req: ChatRequest,
    session: dict[str, Any],
    sessions: SessionManager,
    claude: ClaudeClient,
):
    working_dir = Path(session["working_dir"])
    claude_sid = session["id"] or None
    should_resume = bool(claude_sid)

    # Build execute kwargs with session config (same as sync chat)
    effective_model = req.model or session.get("model")
    effective_system = req.system or session.get("system_prompt")
    effective_effort = req.effort or session.get("effort")
    effective_perm = req.permission_mode or session.get("permission_mode")
    effective_allowed = (
        _csv_to_list(session.get("allowed_tools")) if session.get("allowed_tools") else None
    )
    effective_disallowed = (
        _csv_to_list(session.get("disallowed_tools")) if session.get("disallowed_tools") else None
    )

    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def _callback(update: StreamUpdate) -> None:
        await queue.put({
            "type": update.type,
            "content": update.content,
            "tool_name": update.tool_name,
        })

    execute_kwargs: dict[str, Any] = dict(
        prompt=req.message,
        working_directory=working_dir,
        stream_callback=_callback,
        model_override=effective_model,
        system_override=effective_system,
        effort=effective_effort,
        permission_mode=effective_perm,
        output_format=req.output_format,
        allowed_tools_override=effective_allowed,
        disallowed_tools_override=effective_disallowed,
        max_turns_override=session.get("max_turns"),
    )

    response_holder: list[ClaudeResponse] = []
    error_holder: list[Exception] = []

    async def _run() -> None:
        try:
            try:
                resp = await claude.execute(
                    session_id=claude_sid,
                    continue_session=should_resume,
                    **execute_kwargs,
                )
            except Exception:
                if should_resume:
                    logger.warning("stream_resume_failed_retrying_fresh", session_id=claude_sid)
                    resp = await claude.execute(
                        session_id=None,
                        continue_session=False,
                        **execute_kwargs,
                    )
                else:
                    raise
            response_holder.append(resp)
        except Exception as e:
            error_holder.append(e)
        finally:
            await queue.put(None)

    task = asyncio.create_task(_run())
    event_id = 0

    def _sse(event_type: str, data: dict) -> dict:
        nonlocal event_id
        event_id += 1
        return {
            "event": event_type,
            "id": str(event_id),
            "data": json.dumps(data, ensure_ascii=False),
        }

    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            yield _sse(event["type"], {
                "content": event.get("content"),
                "tool_name": event.get("tool_name"),
            })
    finally:
        await task

    if error_holder:
        yield _sse("error", {"error": str(error_holder[0])})
        return

    if response_holder:
        response = response_holder[0]
        old_cost = float(session.get("total_cost", 0.0))
        old_turns = int(session.get("total_turns", 0))
        await sessions.db.save_interaction(
            session_rowid=session["rowid"],
            new_session_id=response.session_id if not session["id"] else None,
            total_cost=old_cost + response.cost,
            total_turns=old_turns + response.num_turns,
            user_message=req.message,
            assistant_content=response.content,
            tools_used=response.tools_used,
            cost=response.cost,
            duration_ms=response.duration_ms,
        )
        yield _sse("done", {
            "session_id": response.session_id,
            "content": response.content,
            "cost": response.cost,
            "duration_ms": response.duration_ms,
            "num_turns": response.num_turns,
            "tools_used": response.tools_used,
        })


async def _resolve_session(
    sessions: SessionManager, identifier: str, user_id: Optional[str] = None
) -> dict[str, Any] | None:
    """Resolve session by name (primary), rowid, or claude session_id."""
    # Try by name first (most intuitive)
    session = await sessions.get_by_name(identifier)

    # Fallback: try rowid if numeric
    if not session and identifier.isdigit():
        session = await sessions.get_by_rowid(int(identifier))

    # Fallback: try claude session_id
    if not session:
        session = await sessions.get(identifier)

    if session and user_id and session["user_id"] != user_id:
        logger.warning("session_ownership_denied", session_id=identifier,
                        owner=session["user_id"], requester=user_id)
        return None
    return session


# -- Sessions --


@router.post("/sessions", response_model=SessionEnvelope, status_code=201, tags=["Sessions"], summary="Create session")
async def create_session(
    req: SessionCreate,
    request: Request,
    response: Response,
    sessions: SessionManager = Depends(get_sessions),
    api_key: str = Depends(verify_api_key),
):
    rate_limiter.check(api_key)

    # Apply template defaults, then override with explicit values
    from src.api.extras import TEMPLATES
    tmpl = TEMPLATES.get(req.template) if req.template else {}
    if req.template and not tmpl:
        raise HTTPException(status_code=400, detail=f"Template '{req.template}' not found")

    user_id = req.user_id if req.user_id != "default" else api_key
    try:
        session = await sessions.create(
            user_id, req.name,
            system_prompt=req.system_prompt or tmpl.get("system_prompt"),
            model=req.model or tmpl.get("model"),
            max_turns=req.max_turns or tmpl.get("max_turns"),
            permission_mode=req.permission_mode or tmpl.get("permission_mode"),
            effort=req.effort or tmpl.get("effort"),
            allowed_tools=req.allowed_tools or tmpl.get("allowed_tools"),
            disallowed_tools=req.disallowed_tools or tmpl.get("disallowed_tools"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    response.headers["Location"] = f"/api/v1/sessions/{session['rowid']}"
    return SessionEnvelope(data=SessionData.from_db(session), meta=_meta(request))


@router.get("/sessions", response_model=SessionListEnvelope, tags=["Sessions"], summary="List sessions")
async def list_sessions(
    request: Request,
    user_id: str | None = None,
    page: int = 1,
    limit: int = 20,
    sessions: SessionManager = Depends(get_sessions),
    _api_key: str = Depends(verify_api_key),
):
    if limit > 100:
        limit = 100
    if page < 1:
        page = 1

    offset = (page - 1) * limit
    total = await sessions.db.count_sessions(user_id)
    items_raw = await sessions.db.list_sessions(user_id, limit=limit, offset=offset)

    return SessionListEnvelope(
        data=[SessionData.from_db(s) for s in items_raw],
        meta=_meta(request),
        pagination={
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit if total > 0 else 0,
        },
    )


@router.get("/sessions/{session_id}", response_model=SessionEnvelope, tags=["Sessions"], summary="Get session")
async def get_session(
    session_id: str,
    request: Request,
    sessions: SessionManager = Depends(get_sessions),
    _api_key: str = Depends(verify_api_key),
):
    session = await _resolve_session(sessions, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionEnvelope(data=SessionData.from_db(session), meta=_meta(request))


@router.delete("/sessions/{session_id}", status_code=204, tags=["Sessions"], summary="Delete session")
async def delete_session(
    session_id: str,
    sessions: SessionManager = Depends(get_sessions),
    _api_key: str = Depends(verify_api_key),
):
    session = await _resolve_session(sessions, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session["id"]:
        # Pending session — clean up directory and DB row
        wdir = Path(session["working_dir"]) if session.get("working_dir") else None
        if (
            wdir
            and wdir.exists()
            and wdir.is_relative_to(sessions.config.approved_path)
            and wdir != sessions.config.approved_path
        ):
            shutil.rmtree(wdir, ignore_errors=True)
        await sessions.db.delete_session_by_rowid(session["rowid"])
    else:
        deleted = await sessions.delete(session["id"])
        if not deleted:
            raise HTTPException(status_code=404, detail="Session not found")


# -- Repo --


@router.post("/sessions/{session_id}/repo", response_model=SessionEnvelope, tags=["Sessions"], summary="Change working directory")
async def set_repo(
    session_id: str,
    req: RepoRequest,
    request: Request,
    sessions: SessionManager = Depends(get_sessions),
    _api_key: str = Depends(verify_api_key),
):
    session = await _resolve_session(sessions, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session["id"]:
        raise HTTPException(status_code=400, detail="Session has no claude session_id yet")
    try:
        updated = await sessions.set_repo(session["id"], req.working_dir)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not updated:
        raise HTTPException(status_code=404, detail="Session not found after update")
    return SessionEnvelope(data=SessionData.from_db(updated), meta=_meta(request))


# -- History --


@router.get("/sessions/{session_id}/history", response_model=HistoryEnvelope, tags=["History"], summary="Get chat history")
async def get_history(
    session_id: str,
    request: Request,
    limit: int = 100,
    sessions: SessionManager = Depends(get_sessions),
    _api_key: str = Depends(verify_api_key),
):
    session = await _resolve_session(sessions, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session["id"]:
        return HistoryEnvelope(
            data=[], meta=_meta(request),
            session_id=str(session["rowid"]), count=0,
        )
    messages = await sessions.get_history(session["id"], limit)
    return HistoryEnvelope(
        data=[MessageData(**m) for m in messages],
        meta=_meta(request),
        session_id=session["id"],
        count=len(messages),
    )
