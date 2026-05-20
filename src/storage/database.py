from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

logger = structlog.get_logger()

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    id TEXT NOT NULL DEFAULT '',
    user_id TEXT NOT NULL,
    working_dir TEXT NOT NULL,
    system_prompt TEXT,
    model TEXT,
    max_turns INTEGER,
    permission_mode TEXT,
    effort TEXT,
    allowed_tools TEXT,
    disallowed_tools TEXT,
    total_cost REAL DEFAULT 0.0,
    total_turns INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_rowid INTEGER NOT NULL REFERENCES sessions(rowid) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tools_used TEXT,
    cost REAL DEFAULT 0.0,
    duration_ms INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    session_rowid INTEGER NOT NULL REFERENCES sessions(rowid) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'queued',
    message TEXT NOT NULL,
    webhook_url TEXT,
    result TEXT,
    error TEXT,
    cost REAL DEFAULT 0.0,
    duration_ms INTEGER DEFAULT 0,
    tools_used TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_name ON sessions(name);
CREATE INDEX IF NOT EXISTS idx_sessions_claude_id ON sessions(id);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_rowid);
CREATE INDEX IF NOT EXISTS idx_jobs_session ON jobs(session_rowid);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""


class Database:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        logger.info("database_connected", path=str(self.db_path))

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if not self._db:
            raise RuntimeError("Database not connected")
        return self._db

    # -- Sessions --

    async def create_session(
        self,
        name: str,
        session_id: str,
        user_id: str,
        working_dir: str,
        system_prompt: str | None = None,
        model: str | None = None,
        max_turns: int | None = None,
        permission_mode: str | None = None,
        effort: str | None = None,
        allowed_tools: str | None = None,
        disallowed_tools: str | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self.db.execute(
            "INSERT INTO sessions (name, id, user_id, working_dir, system_prompt, model, max_turns, "
            "permission_mode, effort, allowed_tools, disallowed_tools, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, session_id, user_id, working_dir, system_prompt, model, max_turns,
             permission_mode, effort, allowed_tools, disallowed_tools, now, now),
        )
        await self.db.commit()
        rowid = cursor.lastrowid or 0
        return {
            "rowid": rowid,
            "name": name,
            "id": session_id,
            "user_id": user_id,
            "working_dir": working_dir,
            "system_prompt": system_prompt,
            "model": model,
            "max_turns": max_turns,
            "permission_mode": permission_mode,
            "effort": effort,
            "allowed_tools": allowed_tools,
            "disallowed_tools": disallowed_tools,
            "total_cost": 0.0,
            "total_turns": 0,
            "created_at": now,
            "updated_at": now,
        }

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            "SELECT rowid, * FROM sessions WHERE id = ?", (session_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_session_by_name(self, name: str) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            "SELECT rowid, * FROM sessions WHERE name = ? ORDER BY updated_at DESC LIMIT 1",
            (name,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_session_by_rowid(self, rowid: int) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            "SELECT rowid, * FROM sessions WHERE rowid = ?", (rowid,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_sessions(
        self,
        user_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if user_id:
            cursor = await self.db.execute(
                "SELECT rowid, * FROM sessions WHERE user_id = ? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (user_id, limit, offset),
            )
        else:
            cursor = await self.db.execute(
                "SELECT rowid, * FROM sessions ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        return [dict(r) for r in await cursor.fetchall()]

    async def count_sessions(self, user_id: str | None = None) -> int:
        if user_id:
            cursor = await self.db.execute(
                "SELECT COUNT(*) FROM sessions WHERE user_id = ?", (user_id,)
            )
        else:
            cursor = await self.db.execute("SELECT COUNT(*) FROM sessions")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def sum_user_cost(self, user_id: str) -> float:
        cursor = await self.db.execute(
            "SELECT COALESCE(SUM(total_cost), 0) FROM sessions WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return float(row[0]) if row else 0.0

    async def get_usage(self, user_id: str | None = None) -> dict[str, Any]:
        if user_id:
            cursor = await self.db.execute(
                "SELECT COUNT(*) as sessions, COALESCE(SUM(total_cost), 0) as cost, "
                "COALESCE(SUM(total_turns), 0) as turns FROM sessions WHERE user_id = ?",
                (user_id,),
            )
        else:
            cursor = await self.db.execute(
                "SELECT COUNT(*) as sessions, COALESCE(SUM(total_cost), 0) as cost, "
                "COALESCE(SUM(total_turns), 0) as turns FROM sessions"
            )
        row = await cursor.fetchone()
        usage = dict(row) if row else {"sessions": 0, "cost": 0.0, "turns": 0}

        # Message counts
        if user_id:
            cursor = await self.db.execute(
                "SELECT COUNT(*) FROM messages m JOIN sessions s ON m.session_rowid = s.rowid "
                "WHERE s.user_id = ?", (user_id,),
            )
        else:
            cursor = await self.db.execute("SELECT COUNT(*) FROM messages")
        msg_row = await cursor.fetchone()
        usage["messages"] = msg_row[0] if msg_row else 0

        # Job counts
        if user_id:
            cursor = await self.db.execute(
                "SELECT COUNT(*) as total, "
                "SUM(CASE WHEN j.status = 'done' THEN 1 ELSE 0 END) as completed, "
                "SUM(CASE WHEN j.status = 'running' THEN 1 ELSE 0 END) as running, "
                "SUM(CASE WHEN j.status = 'failed' THEN 1 ELSE 0 END) as failed "
                "FROM jobs j JOIN sessions s ON j.session_rowid = s.rowid WHERE s.user_id = ?",
                (user_id,),
            )
        else:
            cursor = await self.db.execute(
                "SELECT COUNT(*) as total, "
                "SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) as completed, "
                "SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) as running, "
                "SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed "
                "FROM jobs"
            )
        job_row = await cursor.fetchone()
        usage["jobs"] = dict(job_row) if job_row else {"total": 0, "completed": 0, "running": 0, "failed": 0}

        return usage

    async def find_resumable_session(
        self, user_id: str, working_dir: str, timeout_hours: int
    ) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            "SELECT rowid, * FROM sessions "
            "WHERE user_id = ? AND working_dir = ? AND id != '' "
            "AND datetime(updated_at) > datetime('now', ? || ' hours') "
            "ORDER BY updated_at DESC LIMIT 1",
            (user_id, working_dir, f"-{timeout_hours}"),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    _ALLOWED_SESSION_COLUMNS = {"working_dir", "total_cost", "total_turns", "updated_at"}

    async def update_session(self, session_id: str, **kwargs: Any) -> None:
        bad = set(kwargs) - self._ALLOWED_SESSION_COLUMNS
        if bad:
            raise ValueError(f"Invalid columns: {bad}")
        kwargs["updated_at"] = datetime.now(timezone.utc).isoformat()
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [session_id]
        await self.db.execute(
            f"UPDATE sessions SET {sets} WHERE id = ?", vals  # noqa: S608
        )
        await self.db.commit()

    async def update_session_id(self, rowid: int, new_session_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            "UPDATE sessions SET id = ?, updated_at = ? WHERE rowid = ?",
            (new_session_id, now, rowid),
        )
        await self.db.commit()

    async def delete_session(self, session_id: str) -> bool:
        cursor = await self.db.execute(
            "DELETE FROM sessions WHERE id = ?", (session_id,)
        )
        await self.db.commit()
        return cursor.rowcount > 0

    # -- Messages --

    async def add_message(
        self,
        session_rowid: int,
        role: str,
        content: str,
        tools_used: list[dict] | None = None,
        cost: float = 0.0,
        duration_ms: int = 0,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        tools_json = json.dumps(tools_used) if tools_used else None
        cursor = await self.db.execute(
            "INSERT INTO messages (session_rowid, role, content, tools_used, cost, duration_ms, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_rowid, role, content, tools_json, cost, duration_ms, now),
        )
        await self.db.execute(
            "UPDATE sessions SET updated_at = ? WHERE rowid = ?",
            (now, session_rowid),
        )
        await self.db.commit()
        return cursor.lastrowid or 0

    # -- Jobs --

    async def create_job(
        self, job_id: str, session_rowid: int, message: str, webhook_url: str | None = None
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            "INSERT INTO jobs (id, session_rowid, status, message, webhook_url, created_at) "
            "VALUES (?, ?, 'queued', ?, ?, ?)",
            (job_id, session_rowid, message, webhook_url, now),
        )
        await self.db.commit()
        return {
            "id": job_id, "session_rowid": session_rowid, "status": "queued",
            "message": message, "webhook_url": webhook_url, "created_at": now,
        }

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        cursor = await self.db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        for field in ("tools_used", "result"):
            if d.get(field) and isinstance(d[field], str):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d

    async def list_jobs(self, session_rowid: int) -> list[dict[str, Any]]:
        cursor = await self.db.execute(
            "SELECT * FROM jobs WHERE session_rowid = ? ORDER BY created_at DESC",
            (session_rowid,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def update_job(self, job_id: str, **kwargs: Any) -> None:
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [job_id]
        await self.db.execute(f"UPDATE jobs SET {sets} WHERE id = ?", vals)  # noqa: S608
        await self.db.commit()

    # -- Messages --

    async def get_messages(
        self, session_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        cursor = await self.db.execute(
            "SELECT m.* FROM messages m "
            "JOIN sessions s ON m.session_rowid = s.rowid "
            "WHERE s.id = ? ORDER BY m.id ASC LIMIT ?",
            (session_id, limit),
        )
        rows = await cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("tools_used"):
                try:
                    d["tools_used"] = json.loads(d["tools_used"])
                except (json.JSONDecodeError, TypeError):
                    pass
            result.append(d)
        return result

    async def save_interaction(
        self,
        session_rowid: int,
        new_session_id: str | None,
        total_cost: float,
        total_turns: int,
        user_message: str,
        assistant_content: str,
        tools_used: list[dict] | None = None,
        cost: float = 0.0,
        duration_ms: int = 0,
    ) -> None:
        """Atomic: update session + save user msg + save assistant msg in single commit."""
        now = datetime.now(timezone.utc).isoformat()
        tools_json = json.dumps(tools_used) if tools_used else None

        # Update session_id if needed
        if new_session_id:
            await self.db.execute(
                "UPDATE sessions SET id = ? WHERE rowid = ? AND id = ''",
                (new_session_id, session_rowid),
            )

        # Update session stats
        await self.db.execute(
            "UPDATE sessions SET total_cost = ?, total_turns = ?, updated_at = ? "
            "WHERE rowid = ?",
            (total_cost, total_turns, now, session_rowid),
        )

        # User message
        await self.db.execute(
            "INSERT INTO messages (session_rowid, role, content, tools_used, cost, duration_ms, created_at) "
            "VALUES (?, ?, ?, NULL, 0, 0, ?)",
            (session_rowid, "user", user_message, now),
        )

        # Assistant message
        await self.db.execute(
            "INSERT INTO messages (session_rowid, role, content, tools_used, cost, duration_ms, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_rowid, "assistant", assistant_content, tools_json, cost, duration_ms, now),
        )

        await self.db.commit()
