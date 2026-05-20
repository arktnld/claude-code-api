from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from src.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key: str | None = Security(api_key_header),
) -> str:
    if not settings.api_keys_list:
        return "anonymous"
    if not api_key or api_key not in settings.api_keys_list:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return api_key


@dataclass
class RateLimitInfo:
    limit: int
    remaining: int
    reset: float  # seconds until window resets


class RateLimiter:
    def __init__(
        self,
        max_requests: int | None = None,
        window: int | None = None,
    ) -> None:
        self.max_requests = max_requests or settings.rate_limit_requests
        self.window = window or settings.rate_limit_window
        self._hits: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> RateLimitInfo:
        now = time.monotonic()
        hits = [t for t in self._hits.get(key, []) if now - t < self.window]

        oldest = hits[0] if hits else now
        reset = self.window - (now - oldest)

        if len(hits) >= self.max_requests:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={
                    "X-RateLimit-Limit": str(self.max_requests),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(reset)),
                    "Retry-After": str(int(reset)),
                },
            )

        hits.append(now)
        self._hits[key] = hits

        remaining = self.max_requests - len(hits)

        # Purge stale keys periodically
        if sum(len(v) for v in self._hits.values()) % 100 == 0:
            stale = [k for k, v in self._hits.items() if not v]
            for k in stale:
                del self._hits[k]

        return RateLimitInfo(
            limit=self.max_requests,
            remaining=remaining,
            reset=reset,
        )


rate_limiter = RateLimiter()
