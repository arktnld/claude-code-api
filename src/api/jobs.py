from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.deps import get_claude, get_sessions
from src.claude.client import ClaudeClient
from src.config import _csv_to_list
from src.security.auth import rate_limiter, verify_api_key
from src.sessions.manager import SessionManager

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1", tags=["Jobs"])

# Track running jobs for cancellation
_running_jobs: dict[str, asyncio.Event] = {}

# Session locks — 1 job at a time per session
_session_locks: dict[int, asyncio.Lock] = {}


def _get_session_lock(session_rowid: int) -> asyncio.Lock:
    if session_rowid not in _session_locks:
        _session_locks[session_rowid] = asyncio.Lock()
    return _session_locks[session_rowid]


# -- Schemas --


class JobCreate(BaseModel):
    model_config = {"extra": "forbid"}

    message: str = Field(..., min_length=1, max_length=1_000_000)
    webhook_url: Optional[str] = Field(None, max_length=2048, description="URL to POST result when done")
    model: Optional[str] = Field(None, max_length=100)
    system: Optional[str] = Field(None, max_length=50_000)
    effort: Optional[str] = Field(None, description="low, medium, high, max")
    permission_mode: Optional[str] = Field(None)
    output_format: Optional[dict[str, Any]] = Field(None)


class JobData(BaseModel):
    model_config = {"extra": "ignore"}

    id: str
    status: str
    message: str
    webhook_url: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    cost: float = 0.0
    duration_ms: int = 0
    tools_used: Optional[Any] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class JobEnvelope(BaseModel):
    data: JobData
    meta: dict[str, Any]


class JobListEnvelope(BaseModel):
    data: list[JobData]
    meta: dict[str, Any]


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


# -- Background worker --


async def _run_job(
    job_id: str,
    session: dict[str, Any],
    req: JobCreate,
    claude: ClaudeClient,
    sessions: SessionManager,
) -> None:
    """Execute Claude in background, update job status, call webhook."""
    lock = _get_session_lock(session["rowid"])

    async with lock:  # Only 1 job per session at a time
        await _run_job_inner(job_id, session, req, claude, sessions)


async def _run_job_inner(
    job_id: str,
    session: dict[str, Any],
    req: JobCreate,
    claude: ClaudeClient,
    sessions: SessionManager,
) -> None:
    interrupt = _running_jobs.get(job_id)
    now = datetime.now(timezone.utc).isoformat()

    await sessions.db.update_job(job_id, status="running", started_at=now)

    try:
        working_dir = Path(session["working_dir"])
        claude_sid = session["id"] or None

        if not claude_sid:
            resumable = await sessions.find_resumable(session["user_id"], str(working_dir))
            if resumable:
                claude_sid = resumable["id"]

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

        response = await claude.execute(
            prompt=req.message,
            working_directory=working_dir,
            session_id=claude_sid,
            continue_session=bool(claude_sid),
            interrupt_event=interrupt,
            model_override=effective_model,
            system_override=effective_system,
            effort=effective_effort,
            permission_mode=effective_perm,
            output_format=req.output_format,
            allowed_tools_override=effective_allowed,
            disallowed_tools_override=effective_disallowed,
            max_turns_override=session.get("max_turns"),
        )

        # Save interaction
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

        completed = datetime.now(timezone.utc).isoformat()
        result_data = {
            "session_id": response.session_id,
            "content": response.content,
            "cost": response.cost,
            "duration_ms": response.duration_ms,
            "num_turns": response.num_turns,
            "tools_used": response.tools_used,
        }

        status = "cancelled" if response.interrupted else "done"
        await sessions.db.update_job(
            job_id,
            status=status,
            result=json.dumps(result_data, ensure_ascii=False),
            cost=response.cost,
            duration_ms=response.duration_ms,
            tools_used=json.dumps(response.tools_used),
            completed_at=completed,
        )

    except Exception as e:
        logger.error("job_failed", job_id=job_id, error=str(e))
        completed = datetime.now(timezone.utc).isoformat()
        await sessions.db.update_job(
            job_id,
            status="failed",
            error=str(e),
            completed_at=completed,
        )
        result_data = None

    finally:
        _running_jobs.pop(job_id, None)

    # Webhook callback
    if req.webhook_url:
        job = await sessions.db.get_job(job_id)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(req.webhook_url, json={
                    "event": "job.completed",
                    "job": job,
                })
            logger.info("webhook_sent", job_id=job_id, url=req.webhook_url)
        except Exception as e:
            logger.warning("webhook_failed", job_id=job_id, url=req.webhook_url, error=str(e))


# -- Routes --


@router.post("/sessions/{name}/jobs", status_code=202, response_model=JobEnvelope, summary="Create async job")
async def create_job(
    name: str,
    req: JobCreate,
    request: Request,
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

    job_id = uuid.uuid4().hex[:16]
    job = await sessions.db.create_job(
        job_id=job_id,
        session_rowid=session["rowid"],
        message=req.message,
        webhook_url=req.webhook_url,
    )

    # Create interrupt event and start background task
    interrupt = asyncio.Event()
    _running_jobs[job_id] = interrupt
    asyncio.create_task(_run_job(job_id, session, req, claude, sessions))

    return JobEnvelope(data=JobData(**job), meta=_meta(request))


@router.get("/sessions/{name}/jobs", response_model=JobListEnvelope, summary="List jobs")
async def list_jobs(
    name: str,
    request: Request,
    sessions: SessionManager = Depends(get_sessions),
    _api_key: str = Depends(verify_api_key),
):
    session = await _resolve_session(sessions, name)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    jobs = await sessions.db.list_jobs(session["rowid"])
    return JobListEnvelope(
        data=[JobData(**j) for j in jobs],
        meta=_meta(request),
    )


@router.get("/sessions/{name}/jobs/{job_id}", response_model=JobEnvelope, summary="Get job status")
async def get_job(
    name: str,
    job_id: str,
    request: Request,
    sessions: SessionManager = Depends(get_sessions),
    _api_key: str = Depends(verify_api_key),
):
    job = await sessions.db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobEnvelope(data=JobData(**job), meta=_meta(request))


@router.post("/sessions/{name}/jobs/{job_id}/cancel", status_code=200, summary="Cancel running job")
async def cancel_job(
    name: str,
    job_id: str,
    request: Request,
    _api_key: str = Depends(verify_api_key),
    sessions: SessionManager = Depends(get_sessions),
):
    job = await sessions.db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] not in ("queued", "running"):
        raise HTTPException(status_code=409, detail=f"Job already {job['status']}")

    interrupt = _running_jobs.get(job_id)
    if interrupt:
        interrupt.set()

    return {"data": {"id": job_id, "status": "cancelling"}, "meta": _meta(request)}
