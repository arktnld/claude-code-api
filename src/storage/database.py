from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import (
    Column,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    event,
    text,
)
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

logger = structlog.get_logger()

metadata = MetaData()

sessions_table = Table(
    "sessions",
    metadata,
    Column("rowid", Integer, primary_key=True, autoincrement=True),
    Column("name", String, nullable=False),
    Column("id", String, nullable=False, server_default=""),
    Column("user_id", String, nullable=False),
    Column("working_dir", String, nullable=False),
    Column("system_prompt", Text),
    Column("model", String),
    Column("max_turns", Integer),
    Column("permission_mode", String),
    Column("effort", String),
    Column("allowed_tools", Text),
    Column("disallowed_tools", Text),
    Column("total_cost", Float, server_default="0.0"),
    Column("total_turns", Integer, server_default="0"),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
)

messages_table = Table(
    "messages",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_rowid", Integer, nullable=False),
    Column("role", String, nullable=False),
    Column("content", Text, nullable=False),
    Column("tools_used", Text),
    Column("cost", Float, server_default="0.0"),
    Column("duration_ms", Integer, server_default="0"),
    Column("created_at", String, nullable=False),
)

jobs_table = Table(
    "jobs",
    metadata,
    Column("id", String, primary_key=True),
    Column("session_rowid", Integer, nullable=False),
    Column("status", String, nullable=False, server_default="queued"),
    Column("message", Text, nullable=False),
    Column("webhook_url", String),
    Column("result", Text),
    Column("error", Text),
    Column("cost", Float, server_default="0.0"),
    Column("duration_ms", Integer, server_default="0"),
    Column("tools_used", Text),
    Column("created_at", String, nullable=False),
    Column("started_at", String),
    Column("completed_at", String),
)

# Indexes
Index("idx_sessions_user", sessions_table.c.user_id)
Index("idx_sessions_name", sessions_table.c.name)
Index("idx_sessions_claude_id", sessions_table.c.id)
Index("idx_messages_session", messages_table.c.session_rowid)
Index("idx_jobs_session", jobs_table.c.session_rowid)
Index("idx_jobs_status", jobs_table.c.status)


def _sqlite_pragmas(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class Database:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._engine: AsyncEngine | None = None
        self._is_sqlite = "sqlite" in database_url

    async def connect(self) -> None:
        engine_kwargs: dict[str, Any] = {}

        if self._is_sqlite:
            # Ensure parent dir exists for SQLite
            from pathlib import Path
            db_path = self.database_url.split("///", 1)[-1] if "///" in self.database_url else ""
            if db_path:
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            engine_kwargs["connect_args"] = {"check_same_thread": False}

        self._engine = create_async_engine(self.database_url, **engine_kwargs)

        # SQLite pragmas
        if self._is_sqlite:
            event.listen(self._engine.sync_engine, "connect", _sqlite_pragmas)

        # Create tables
        async with self._engine.begin() as conn:
            await conn.run_sync(metadata.create_all)

        logger.info("database_connected", url=self._mask_url(self.database_url))

    async def close(self) -> None:
        if self._engine:
            await self._engine.dispose()
            self._engine = None

    @property
    def engine(self) -> AsyncEngine:
        if not self._engine:
            raise RuntimeError("Database not connected")
        return self._engine

    @staticmethod
    def _mask_url(url: str) -> str:
        if "@" in url:
            pre, post = url.rsplit("@", 1)
            return pre.split("://")[0] + "://***@" + post
        return url

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
        async with self.engine.begin() as conn:
            result = await conn.execute(
                sessions_table.insert().values(
                    name=name, id=session_id, user_id=user_id, working_dir=working_dir,
                    system_prompt=system_prompt, model=model, max_turns=max_turns,
                    permission_mode=permission_mode, effort=effort,
                    allowed_tools=allowed_tools, disallowed_tools=disallowed_tools,
                    total_cost=0.0, total_turns=0, created_at=now, updated_at=now,
                )
            )
            rowid = result.inserted_primary_key[0]
        return {
            "rowid": rowid, "name": name, "id": session_id, "user_id": user_id,
            "working_dir": working_dir, "system_prompt": system_prompt, "model": model,
            "max_turns": max_turns, "permission_mode": permission_mode, "effort": effort,
            "allowed_tools": allowed_tools, "disallowed_tools": disallowed_tools,
            "total_cost": 0.0, "total_turns": 0, "created_at": now, "updated_at": now,
        }

    async def _fetch_one(self, stmt) -> dict[str, Any] | None:
        async with self.engine.connect() as conn:
            result = await conn.execute(stmt)
            row = result.mappings().fetchone()
            return dict(row) if row else None

    async def _fetch_all(self, stmt) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            result = await conn.execute(stmt)
            return [dict(r) for r in result.mappings().fetchall()]

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        stmt = sessions_table.select().where(sessions_table.c.id == session_id)
        return await self._fetch_one(stmt)

    async def get_session_by_name(self, name: str) -> dict[str, Any] | None:
        stmt = (
            sessions_table.select()
            .where(sessions_table.c.name == name)
            .order_by(sessions_table.c.updated_at.desc())
            .limit(1)
        )
        return await self._fetch_one(stmt)

    async def get_session_by_rowid(self, rowid: int) -> dict[str, Any] | None:
        stmt = sessions_table.select().where(sessions_table.c.rowid == rowid)
        return await self._fetch_one(stmt)

    async def list_sessions(
        self,
        user_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        stmt = sessions_table.select().order_by(sessions_table.c.updated_at.desc()).limit(limit).offset(offset)
        if user_id:
            stmt = stmt.where(sessions_table.c.user_id == user_id)
        return await self._fetch_all(stmt)

    async def count_sessions(self, user_id: str | None = None) -> int:
        from sqlalchemy import func, select
        stmt = select(func.count()).select_from(sessions_table)
        if user_id:
            stmt = stmt.where(sessions_table.c.user_id == user_id)
        async with self.engine.connect() as conn:
            result = await conn.execute(stmt)
            return result.scalar() or 0

    async def sum_user_cost(self, user_id: str) -> float:
        from sqlalchemy import func, select
        stmt = select(func.coalesce(func.sum(sessions_table.c.total_cost), 0)).where(
            sessions_table.c.user_id == user_id
        )
        async with self.engine.connect() as conn:
            result = await conn.execute(stmt)
            return float(result.scalar() or 0.0)

    async def get_usage(self, user_id: str | None = None) -> dict[str, Any]:
        from sqlalchemy import case, func, select

        # Session stats
        stmt = select(
            func.count().label("sessions"),
            func.coalesce(func.sum(sessions_table.c.total_cost), 0).label("cost"),
            func.coalesce(func.sum(sessions_table.c.total_turns), 0).label("turns"),
        )
        if user_id:
            stmt = stmt.where(sessions_table.c.user_id == user_id)
        async with self.engine.connect() as conn:
            row = (await conn.execute(stmt)).mappings().fetchone()
        usage = dict(row) if row else {"sessions": 0, "cost": 0.0, "turns": 0}

        # Message count
        msg_stmt = select(func.count()).select_from(messages_table)
        if user_id:
            msg_stmt = msg_stmt.join(
                sessions_table, messages_table.c.session_rowid == sessions_table.c.rowid
            ).where(sessions_table.c.user_id == user_id)
        async with self.engine.connect() as conn:
            usage["messages"] = (await conn.execute(msg_stmt)).scalar() or 0

        # Job counts
        job_stmt = select(
            func.count().label("total"),
            func.sum(case((jobs_table.c.status == "done", 1), else_=0)).label("completed"),
            func.sum(case((jobs_table.c.status == "running", 1), else_=0)).label("running"),
            func.sum(case((jobs_table.c.status == "failed", 1), else_=0)).label("failed"),
        )
        if user_id:
            job_stmt = job_stmt.join(
                sessions_table, jobs_table.c.session_rowid == sessions_table.c.rowid
            ).where(sessions_table.c.user_id == user_id)
        async with self.engine.connect() as conn:
            job_row = (await conn.execute(job_stmt)).mappings().fetchone()
        usage["jobs"] = dict(job_row) if job_row else {"total": 0, "completed": 0, "running": 0, "failed": 0}

        return usage

    async def find_resumable_session(
        self, user_id: str, working_dir: str, timeout_hours: int
    ) -> dict[str, Any] | None:
        # Use raw text for datetime arithmetic (works on both SQLite and Postgres)
        if self._is_sqlite:
            time_filter = text(
                "datetime(sessions.updated_at) > datetime('now', :offset || ' hours')"
            )
        else:
            time_filter = text(
                "sessions.updated_at::timestamp > NOW() - make_interval(hours => :offset)"
            )
        stmt = (
            sessions_table.select()
            .where(sessions_table.c.user_id == user_id)
            .where(sessions_table.c.working_dir == working_dir)
            .where(sessions_table.c.id != "")
            .where(time_filter.bindparams(offset=timeout_hours))
            .order_by(sessions_table.c.updated_at.desc())
            .limit(1)
        )
        return await self._fetch_one(stmt)

    async def update_session(self, session_id: str, **kwargs: Any) -> None:
        _ALLOWED = {"working_dir", "total_cost", "total_turns", "updated_at"}
        bad = set(kwargs) - _ALLOWED
        if bad:
            raise ValueError(f"Invalid columns: {bad}")
        kwargs["updated_at"] = datetime.now(timezone.utc).isoformat()
        async with self.engine.begin() as conn:
            await conn.execute(
                sessions_table.update().where(sessions_table.c.id == session_id).values(**kwargs)
            )

    async def update_session_id(self, rowid: int, new_session_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with self.engine.begin() as conn:
            await conn.execute(
                sessions_table.update()
                .where(sessions_table.c.rowid == rowid)
                .values(id=new_session_id, updated_at=now)
            )

    async def delete_session(self, session_id: str) -> bool:
        async with self.engine.begin() as conn:
            # Delete related messages and jobs first (no FK cascade in all DBs)
            session = await self.get_session(session_id)
            if session:
                await conn.execute(
                    messages_table.delete().where(messages_table.c.session_rowid == session["rowid"])
                )
                await conn.execute(
                    jobs_table.delete().where(jobs_table.c.session_rowid == session["rowid"])
                )
            result = await conn.execute(
                sessions_table.delete().where(sessions_table.c.id == session_id)
            )
            return result.rowcount > 0

    async def delete_session_by_rowid(self, rowid: int) -> bool:
        async with self.engine.begin() as conn:
            await conn.execute(messages_table.delete().where(messages_table.c.session_rowid == rowid))
            await conn.execute(jobs_table.delete().where(jobs_table.c.session_rowid == rowid))
            result = await conn.execute(sessions_table.delete().where(sessions_table.c.rowid == rowid))
            return result.rowcount > 0

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
        async with self.engine.begin() as conn:
            result = await conn.execute(
                messages_table.insert().values(
                    session_rowid=session_rowid, role=role, content=content,
                    tools_used=tools_json, cost=cost, duration_ms=duration_ms, created_at=now,
                )
            )
            await conn.execute(
                sessions_table.update()
                .where(sessions_table.c.rowid == session_rowid)
                .values(updated_at=now)
            )
            return result.inserted_primary_key[0]

    async def get_messages(
        self, session_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        stmt = (
            messages_table.select()
            .join(sessions_table, messages_table.c.session_rowid == sessions_table.c.rowid)
            .where(sessions_table.c.id == session_id)
            .order_by(messages_table.c.id.asc())
            .limit(limit)
        )
        rows = await self._fetch_all(stmt)
        for d in rows:
            if d.get("tools_used") and isinstance(d["tools_used"], str):
                try:
                    d["tools_used"] = json.loads(d["tools_used"])
                except (json.JSONDecodeError, TypeError):
                    pass
        return rows

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
        """Atomic: update session + save user msg + save assistant msg in single transaction."""
        now = datetime.now(timezone.utc).isoformat()
        tools_json = json.dumps(tools_used) if tools_used else None

        async with self.engine.begin() as conn:
            if new_session_id:
                await conn.execute(
                    sessions_table.update()
                    .where(sessions_table.c.rowid == session_rowid)
                    .where(sessions_table.c.id == "")
                    .values(id=new_session_id)
                )
            await conn.execute(
                sessions_table.update()
                .where(sessions_table.c.rowid == session_rowid)
                .values(total_cost=total_cost, total_turns=total_turns, updated_at=now)
            )
            await conn.execute(
                messages_table.insert().values(
                    session_rowid=session_rowid, role="user", content=user_message,
                    tools_used=None, cost=0, duration_ms=0, created_at=now,
                )
            )
            await conn.execute(
                messages_table.insert().values(
                    session_rowid=session_rowid, role="assistant", content=assistant_content,
                    tools_used=tools_json, cost=cost, duration_ms=duration_ms, created_at=now,
                )
            )

    # -- Jobs --

    async def create_job(
        self, job_id: str, session_rowid: int, message: str, webhook_url: str | None = None
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        async with self.engine.begin() as conn:
            await conn.execute(
                jobs_table.insert().values(
                    id=job_id, session_rowid=session_rowid, status="queued",
                    message=message, webhook_url=webhook_url, cost=0.0,
                    duration_ms=0, created_at=now,
                )
            )
        return {
            "id": job_id, "session_rowid": session_rowid, "status": "queued",
            "message": message, "webhook_url": webhook_url, "created_at": now,
        }

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        stmt = jobs_table.select().where(jobs_table.c.id == job_id)
        d = await self._fetch_one(stmt)
        if not d:
            return None
        for field in ("tools_used", "result"):
            if d.get(field) and isinstance(d[field], str):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d

    async def list_jobs(self, session_rowid: int) -> list[dict[str, Any]]:
        stmt = (
            jobs_table.select()
            .where(jobs_table.c.session_rowid == session_rowid)
            .order_by(jobs_table.c.created_at.desc())
        )
        return await self._fetch_all(stmt)

    async def update_job(self, job_id: str, **kwargs: Any) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                jobs_table.update().where(jobs_table.c.id == job_id).values(**kwargs)
            )

    # -- Audit --

    async def get_audit(
        self, user_id: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        from sqlalchemy import select
        stmt = (
            select(
                messages_table,
                sessions_table.c.name.label("session_name"),
                sessions_table.c.user_id,
            )
            .join(sessions_table, messages_table.c.session_rowid == sessions_table.c.rowid)
            .order_by(messages_table.c.id.desc())
            .limit(limit)
        )
        if user_id:
            stmt = stmt.where(sessions_table.c.user_id == user_id)
        return await self._fetch_all(stmt)
