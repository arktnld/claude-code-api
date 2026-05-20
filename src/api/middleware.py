from __future__ import annotations

import time
import uuid

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = structlog.get_logger()

MAX_BODY_SIZE = 2 * 1024 * 1024  # 2MB


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        # Body size check
        content_length = request.headers.get("content-length")
        try:
            content_too_large = content_length and int(content_length) > MAX_BODY_SIZE
        except (ValueError, TypeError):
            content_too_large = False
        if content_too_large:
            return JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": "PAYLOAD_TOO_LARGE",
                        "message": f"Request body exceeds {MAX_BODY_SIZE} bytes",
                        "request_id": request_id,
                    }
                },
            )

        # Security headers + latency logging
        start = time.monotonic()
        response = await call_next(request)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{elapsed_ms}ms"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"

        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            elapsed_ms=elapsed_ms,
        )

        return response
