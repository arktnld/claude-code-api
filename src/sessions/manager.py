from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Optional

import structlog

from src.claude.client import ClaudeClient, ClaudeResponse
from src.config import Settings
from src.storage.database import Database

logger = structlog.get_logger()


class SessionManager:
    def __init__(self, db: Database, claude: ClaudeClient, config: Settings) -> None:
        self.db = db
        self.claude = claude
        self.config = config

    async def create(
        self,
        user_id: str,
        name: str,
        system_prompt: str | None = None,
        model: str | None = None,
        max_turns: int | None = None,
        permission_mode: str | None = None,
        effort: str | None = None,
        allowed_tools: str | None = None,
        disallowed_tools: str | None = None,
    ) -> dict[str, Any]:
        # Sanitize name — only allow safe characters
        safe_name = name.strip().replace("..", "").replace("/", "").replace("\\", "")
        if not safe_name:
            raise ValueError("Invalid project name")

        resolved = (self.config.approved_path / safe_name).resolve()

        if not resolved.is_relative_to(self.config.approved_path):
            raise ValueError(f"Project name '{name}' resolves outside approved directory")

        # Create directory if it doesn't exist
        resolved.mkdir(parents=True, exist_ok=True)

        # Enforce max sessions per user
        user_sessions = await self.db.list_sessions(user_id)
        if len(user_sessions) >= self.config.max_sessions_per_user:
            oldest = min(user_sessions, key=lambda s: s["updated_at"])
            sid = oldest["id"]
            if sid:
                await self.db.delete_session(sid)
            else:
                await self.db.db.execute(
                    "DELETE FROM sessions WHERE rowid = ?", (oldest["rowid"],)
                )
                await self.db.db.commit()
            logger.info("session_evicted", evicted_rowid=oldest["rowid"], user_id=user_id)

        session = await self.db.create_session(
            name=safe_name,
            session_id="",
            user_id=user_id,
            working_dir=str(resolved),
            system_prompt=system_prompt,
            model=model,
            max_turns=max_turns,
            permission_mode=permission_mode,
            effort=effort,
            allowed_tools=allowed_tools,
            disallowed_tools=disallowed_tools,
        )
        logger.info("session_created", name=safe_name, user_id=user_id, dir=str(resolved))
        return session

    async def get(self, session_id: str) -> dict[str, Any] | None:
        return await self.db.get_session(session_id)

    async def get_by_name(self, name: str) -> dict[str, Any] | None:
        return await self.db.get_session_by_name(name)

    async def get_by_rowid(self, rowid: int) -> dict[str, Any] | None:
        return await self.db.get_session_by_rowid(rowid)

    async def list(self, user_id: Optional[str] = None) -> list[dict[str, Any]]:
        return await self.db.list_sessions(user_id)

    async def delete(self, session_id: str, cleanup_files: bool = True) -> bool:
        if cleanup_files:
            session = await self.db.get_session(session_id)
            if session and session.get("working_dir"):
                wdir = Path(session["working_dir"])
                if (
                    wdir.exists()
                    and wdir.is_relative_to(self.config.approved_path)
                    and wdir != self.config.approved_path
                ):
                    shutil.rmtree(wdir, ignore_errors=True)
                    logger.info("session_dir_removed", path=str(wdir))

        deleted = await self.db.delete_session(session_id)
        if deleted:
            logger.info("session_deleted", session_id=session_id)
        return deleted

    async def set_repo(
        self, session_id: str, working_dir: str
    ) -> dict[str, Any] | None:
        resolved = Path(working_dir).resolve()

        if not resolved.is_relative_to(self.config.approved_path):
            raise ValueError("Directory outside approved path")
        if not resolved.is_dir():
            raise ValueError(f"Directory {working_dir} does not exist")

        await self.db.update_session(session_id, working_dir=str(resolved))
        return await self.db.get_session(session_id)

    async def update_from_response(
        self, session_rowid: int, response: ClaudeResponse
    ) -> dict[str, Any] | None:
        """Update session after Claude execution — assign real session_id, track cost."""
        session = await self.db.get_session_by_rowid(session_rowid)
        if not session:
            return None

        # Assign real session_id from Claude on first execution
        if not session["id"] and response.session_id:
            await self.db.update_session_id(session_rowid, response.session_id)
            logger.info(
                "session_id_assigned",
                rowid=session_rowid,
                claude_session_id=response.session_id,
            )

        # Track cost
        old_cost = float(session.get("total_cost", 0.0))
        updates: dict[str, Any] = {
            "total_cost": old_cost + response.cost,
            "total_turns": int(session.get("total_turns", 0)) + response.num_turns,
        }

        sid = response.session_id or session["id"]
        if sid:
            await self.db.update_session(sid, **updates)

        return await self.db.get_session_by_rowid(session_rowid)

    async def check_user_budget(self, user_id: str) -> None:
        """Raise if user exceeded max cost budget."""
        total_cost = await self.db.sum_user_cost(user_id)
        if total_cost >= self.config.claude_max_cost_per_user:
            raise ValueError(
                f"User budget exceeded: ${total_cost:.2f} >= ${self.config.claude_max_cost_per_user:.2f}"
            )

    async def find_resumable(
        self, user_id: str, working_dir: str
    ) -> dict[str, Any] | None:
        """Find most recent non-expired session with real session_id for user+dir."""
        resolved = str(Path(working_dir).resolve())
        return await self.db.find_resumable_session(
            user_id, resolved, self.config.session_timeout_hours
        )

    async def get_history(
        self, session_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        return await self.db.get_messages(session_id, limit)
