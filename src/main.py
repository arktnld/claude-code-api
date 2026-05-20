from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api import deps
from src.api.extras import router as extras_router
from src.api.files import router as files_router
from src.api.jobs import router as jobs_router
from src.api.middleware import RequestIDMiddleware
from src.api.routes import router
from src.claude.client import ClaudeClient
from src.claude.exceptions import ClaudeError, ClaudeTimeoutError
from src.config import settings
from src.security.validators import SecurityValidator
from src.sessions.manager import SessionManager
from src.storage.database import Database

logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO))

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger()


# -- RFC 9457 Problem Details helper --

def _problem_response(
    status: int,
    title: str,
    detail: str,
    error_type: str = "about:blank",
    request: Request | None = None,
    extra: dict | None = None,
) -> JSONResponse:
    """Build RFC 9457 Problem Details response."""
    request_id = None
    instance = None
    if request:
        request_id = getattr(request.state, "request_id", None)
        instance = str(request.url)

    body: dict = {
        "type": error_type,
        "title": title,
        "status": status,
        "detail": detail,
    }
    if instance:
        body["instance"] = instance
    if request_id:
        body["request_id"] = request_id
    if extra:
        body.update(extra)

    return JSONResponse(
        status_code=status,
        content=body,
        media_type="application/problem+json",
    )


# -- Lifespan --

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    db = Database(settings.database_url)
    await db.connect()

    security = SecurityValidator(settings.approved_path)
    claude = ClaudeClient(config=settings, security_validator=security)
    sessions = SessionManager(db, claude, config=settings)

    deps.db = db
    deps.claude_client = claude
    deps.session_manager = sessions

    logger.info(
        "app_started",
        host=settings.api_host,
        port=settings.api_port,
        model=settings.claude_model or "default",
        approved_dir=str(settings.approved_path),
        sandbox=settings.sandbox_enabled,
    )

    yield

    await db.close()
    logger.info("app_stopped")


# -- App --

app = FastAPI(
    title="Claude Code API",
    description="REST API for Claude Code — execute code, read/write files, run commands via Claude CLI.",
    version="0.2.0",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "Health", "description": "Server health and readiness checks"},
        {"name": "Sessions", "description": "Create, list, get, delete sessions and change working directory"},
        {"name": "Chat", "description": "Send messages to Claude — sync or SSE stream"},
        {"name": "History", "description": "Retrieve chat history for a session"},
        {"name": "Jobs", "description": "Async job execution — fire & forget with webhook callbacks"},
        {"name": "Files", "description": "Upload, download, and list files in session workspace"},
        {"name": "Usage", "description": "Cost and usage statistics"},
        {"name": "Templates", "description": "Pre-configured session templates"},
        {"name": "Utilities", "description": "Token counting and other tools"},
        {"name": "Audit", "description": "Audit trail of all actions"},
    ],
    docs_url="/docs" if settings.enable_docs else None,
    redoc_url="/redoc" if settings.enable_docs else None,
    openapi_url="/openapi.json" if settings.enable_docs else None,
)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials="*" not in settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -- Error handlers (RFC 9457 Problem Details) --

_STATUS_TITLES = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
    413: "Payload Too Large",
    422: "Validation Error",
    429: "Too Many Requests",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    status = exc.status_code
    title = _STATUS_TITLES.get(status, "Error")
    detail = str(exc.detail) if exc.detail else title

    resp = _problem_response(
        status=status,
        title=title,
        detail=detail,
        request=request,
    )

    # Preserve headers (e.g., rate limit headers on 429)
    if hasattr(exc, "headers") and exc.headers:
        for k, v in exc.headers.items():
            resp.headers[k] = v

    return resp


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = []
    for err in exc.errors():
        errors.append({
            "field": " -> ".join(str(loc) for loc in err.get("loc", [])),
            "message": err.get("msg", ""),
            "type": err.get("type", ""),
        })

    return _problem_response(
        status=422,
        title="Validation Error",
        detail=f"{len(errors)} validation error(s)",
        request=request,
        extra={"errors": errors},
    )


@app.exception_handler(ClaudeTimeoutError)
async def claude_timeout_handler(request: Request, exc: ClaudeTimeoutError) -> JSONResponse:
    return _problem_response(
        status=504,
        title="Gateway Timeout",
        detail=str(exc),
        error_type="claude:timeout",
        request=request,
    )


@app.exception_handler(ClaudeError)
async def claude_error_handler(request: Request, exc: ClaudeError) -> JSONResponse:
    return _problem_response(
        status=502,
        title="Bad Gateway",
        detail=str(exc),
        error_type=f"claude:{type(exc).__name__}",
        request=request,
    )


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled_error", error=str(exc), type=type(exc).__name__)
    return _problem_response(
        status=500,
        title="Internal Server Error",
        detail="An unexpected error occurred",
        request=request,
    )


app.include_router(router)
app.include_router(jobs_router)
app.include_router(files_router)
app.include_router(extras_router)


def run() -> None:
    uvicorn.run(
        "src.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    run()
