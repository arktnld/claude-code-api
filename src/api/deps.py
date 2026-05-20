from __future__ import annotations

from src.claude.client import ClaudeClient
from src.sessions.manager import SessionManager
from src.storage.database import Database

db: Database | None = None
claude_client: ClaudeClient | None = None
session_manager: SessionManager | None = None


def get_db() -> Database:
    assert db is not None, "Database not initialized"
    return db


def get_claude() -> ClaudeClient:
    assert claude_client is not None, "Claude client not initialized"
    return claude_client


def get_sessions() -> SessionManager:
    assert session_manager is not None, "Session manager not initialized"
    return session_manager
