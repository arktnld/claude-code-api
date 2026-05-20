from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import structlog
import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.deps import get_sessions
from src.security.auth import verify_api_key
from src.sessions.manager import SessionManager

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1")


def _meta(request: Request) -> dict[str, Any]:
    return {
        "request_id": getattr(request.state, "request_id", None),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "v1",
    }


# ============================================================
# 1. Usage
# ============================================================


@router.get("/usage", tags=["Usage"], summary="Get usage statistics")
async def get_usage(
    request: Request,
    user_id: Optional[str] = None,
    sessions: SessionManager = Depends(get_sessions),
    api_key: str = Depends(verify_api_key),
):
    """Returns cost, sessions, messages, jobs stats. Filter by user_id."""
    effective_user = user_id or (api_key if api_key != "anonymous" else None)
    usage = await sessions.db.get_usage(effective_user)
    return {"data": usage, "user_id": effective_user, "meta": _meta(request)}


# ============================================================
# 3. Input Moderation
# ============================================================

_BLOCKED_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts)", re.I),
    re.compile(r"you\s+are\s+now\s+(DAN|jailbreak|unrestricted)", re.I),
    re.compile(r"system\s*:\s*you\s+are", re.I),
    re.compile(r"<\|im_start\|>", re.I),
    re.compile(r"rm\s+-rf\s+/(?!\w)", re.I),  # rm -rf / (but not rm -rf /tmp)
    re.compile(r":(){ :\|:& };:", re.I),  # fork bomb
    re.compile(r"curl\s+.*\|\s*(?:bash|sh|zsh)", re.I),  # curl pipe to shell
]


def moderate_input(text: str) -> tuple[bool, Optional[str]]:
    """Check input for dangerous/injection patterns. Returns (safe, reason)."""
    for pattern in _BLOCKED_PATTERNS:
        if pattern.search(text):
            return False, f"Blocked: input matches forbidden pattern"
    return True, None


# ============================================================
# 4. Token Counting
# ============================================================


class TokenCountRequest(BaseModel):
    model_config = {"extra": "forbid"}
    text: str = Field(..., min_length=1, max_length=1_000_000)


@router.post("/tokens/count", tags=["Utilities"], summary="Estimate token count")
async def count_tokens(
    req: TokenCountRequest,
    request: Request,
    _api_key: str = Depends(verify_api_key),
):
    """Rough token estimate (chars/4 heuristic). Accurate for planning."""
    char_count = len(req.text)
    word_count = len(req.text.split())
    estimated_tokens = max(char_count // 4, word_count)

    return {
        "data": {
            "characters": char_count,
            "words": word_count,
            "estimated_tokens": estimated_tokens,
        },
        "meta": _meta(request),
    }


# ============================================================
# 5. Session Templates (loaded from templates.yml)
# ============================================================

_TEMPLATES_PATH = Path(__file__).resolve().parent.parent.parent / "templates.yml"


def _load_templates() -> dict[str, dict[str, Any]]:
    if not _TEMPLATES_PATH.exists():
        logger.warning("templates_file_missing", path=str(_TEMPLATES_PATH))
        return {}
    with open(_TEMPLATES_PATH) as f:
        data = yaml.safe_load(f) or {}
    return data


TEMPLATES: dict[str, dict[str, Any]] = _load_templates()


@router.get("/templates", tags=["Templates"], summary="List session templates")
async def list_templates(request: Request):
    """List all available session templates.

    Templates are pre-configured agent profiles loaded from `templates.yml`.
    Each template defines a `system_prompt` and optional defaults like `effort`.

    Use a template when creating a session:
    ```json
    POST /api/v1/sessions
    {"name": "my-review", "template": "code-reviewer"}
    ```

    Explicit values in the request override template defaults.
    Edit `templates.yml` to add, remove, or customize templates — no restart needed
    (call `POST /api/v1/templates/reload`).
    """
    return {
        "data": {name: {**tmpl, "name": name} for name, tmpl in TEMPLATES.items()},
        "meta": _meta(request),
    }


@router.get("/templates/{template_name}", tags=["Templates"], summary="Get template details")
async def get_template(template_name: str, request: Request):
    """Get a specific template by name.

    Returns the template's `system_prompt`, `effort`, and any other configured fields.
    Use this to preview what a template provides before creating a session with it.
    """
    tmpl = TEMPLATES.get(template_name)
    if not tmpl:
        raise HTTPException(status_code=404, detail=f"Template '{template_name}' not found")
    return {"data": {**tmpl, "name": template_name}, "meta": _meta(request)}


@router.post("/templates/reload", tags=["Templates"], summary="Reload templates from disk")
async def reload_templates(request: Request, _api_key: str = Depends(verify_api_key)):
    """Hot-reload templates from `templates.yml` without restarting the server."""
    global TEMPLATES
    TEMPLATES = _load_templates()
    return {
        "data": {"count": len(TEMPLATES), "names": list(TEMPLATES.keys())},
        "meta": _meta(request),
    }


# ============================================================
# 6. Audit Trail
# ============================================================


@router.get("/audit", tags=["Audit"], summary="Get audit log")
async def get_audit(
    request: Request,
    user_id: Optional[str] = None,
    limit: int = 50,
    sessions: SessionManager = Depends(get_sessions),
    api_key: str = Depends(verify_api_key),
):
    """Returns recent messages (user prompts + assistant responses) as audit trail."""
    effective_user = user_id or (api_key if api_key != "anonymous" else None)

    if limit > 200:
        limit = 200

    rows = await sessions.db.get_audit(effective_user, limit)
    entries = []
    for d in rows:
        if d.get("content") and len(d["content"]) > 500:
            d["content"] = d["content"][:500] + "..."
        entries.append(d)

    return {
        "data": entries,
        "count": len(entries),
        "user_id": effective_user,
        "meta": _meta(request),
    }
