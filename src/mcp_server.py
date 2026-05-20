"""
Claude Code API — MCP Server
==============================
Exposes Claude Code sessions as MCP tools, resources, and prompts.

Run:
  claude-code-mcp                              # stdio (default)
  claude-code-mcp --transport streamable-http  # HTTP
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP

from src.claude.client import ClaudeClient
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

# ── MCP Server ──

mcp = FastMCP("Claude Code API")

# ── Shared state (initialized on first use) ──

_db: Database | None = None
_claude: ClaudeClient | None = None
_sessions: SessionManager | None = None
_initialized = False
_lock = asyncio.Lock()


async def _ensure_init() -> SessionManager:
    """Lazy-init DB, Claude client, and session manager."""
    global _db, _claude, _sessions, _initialized
    async with _lock:
        if not _initialized:
            _db = Database(settings.database_url)
            await _db.connect()

            security = SecurityValidator(settings.approved_path)
            _claude = ClaudeClient(config=settings, security_validator=security)
            _sessions = SessionManager(_db, _claude, config=settings)
            _initialized = True
            logger.info("mcp_initialized")
    return _sessions  # type: ignore


def _user_id() -> str:
    return "mcp-user"


# ── Tools ──


@mcp.tool()
async def create_session(
    name: str,
    template: str = "",
    system_prompt: str = "",
    model: str = "",
    effort: str = "",
) -> str:
    """Create a new Claude Code session.

    Args:
        name: Session name (creates workspace directory)
        template: Optional template preset (code-reviewer, debug, devops, refactor, test-writer, docs, architect, security, performance, api-designer, data-engineer, frontend)
        system_prompt: Optional custom system prompt (overrides template)
        model: Optional model override
        effort: Optional effort level (low, medium, high, max)
    """
    sessions = await _ensure_init()

    # Template merge
    tmpl: dict[str, Any] = {}
    if template:
        import yaml
        from pathlib import Path
        templates_path = Path(__file__).resolve().parent.parent / "templates.yml"
        if templates_path.exists():
            with open(templates_path) as f:
                all_templates = yaml.safe_load(f) or {}
            tmpl = all_templates.get(template, {})

    session = await sessions.create(
        _user_id(),
        name,
        system_prompt=system_prompt or tmpl.get("system_prompt") or None,
        model=model or tmpl.get("model") or None,
        effort=effort or tmpl.get("effort") or None,
    )
    return json.dumps({
        "name": session["name"],
        "working_dir": session["working_dir"],
        "status": "active" if session.get("id") else "pending",
    }, indent=2)


@mcp.tool()
async def chat(name: str, message: str, effort: str = "", model: str = "") -> str:
    """Send a message to a Claude Code session.

    Claude will execute code, create files, run commands — full Claude Code capabilities.

    Args:
        name: Session name
        message: Your prompt/instruction
        effort: Optional effort override (low, medium, high, max)
        model: Optional model override
    """
    sessions = await _ensure_init()

    session = await sessions.get_by_name(name)
    if not session:
        return json.dumps({"error": f"Session '{name}' not found"})

    from pathlib import Path
    from src.config import _csv_to_list

    working_dir = Path(session["working_dir"])
    claude_sid = session["id"] or None

    if not claude_sid:
        resumable = await sessions.find_resumable(session["user_id"], str(working_dir))
        if resumable:
            claude_sid = resumable["id"]

    effective_model = model or session.get("model")
    effective_effort = effort or session.get("effort")
    effective_allowed = _csv_to_list(session.get("allowed_tools")) if session.get("allowed_tools") else None
    effective_disallowed = _csv_to_list(session.get("disallowed_tools")) if session.get("disallowed_tools") else None

    response = await _sessions.claude.execute(  # type: ignore
        prompt=message,
        working_directory=working_dir,
        session_id=claude_sid,
        continue_session=bool(claude_sid),
        model_override=effective_model or None,
        system_override=session.get("system_prompt"),
        effort=effective_effort or None,
        permission_mode=session.get("permission_mode"),
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
        user_message=message,
        assistant_content=response.content,
        tools_used=response.tools_used,
        cost=response.cost,
        duration_ms=response.duration_ms,
    )

    return json.dumps({
        "content": response.content,
        "cost": response.cost,
        "duration_ms": response.duration_ms,
        "num_turns": response.num_turns,
        "tools_used": [t["name"] for t in (response.tools_used or [])],
    }, indent=2, ensure_ascii=False)


@mcp.tool()
async def list_sessions() -> str:
    """List all Claude Code sessions."""
    sessions = await _ensure_init()
    rows = await sessions.db.list_sessions(_user_id())
    result = []
    for s in rows:
        result.append({
            "name": s["name"],
            "status": "active" if s.get("id") else "pending",
            "total_cost": s["total_cost"],
            "total_turns": s["total_turns"],
            "working_dir": s["working_dir"],
        })
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_session(name: str) -> str:
    """Get details of a specific session.

    Args:
        name: Session name
    """
    sessions = await _ensure_init()
    session = await sessions.get_by_name(name)
    if not session:
        return json.dumps({"error": f"Session '{name}' not found"})
    return json.dumps({
        "name": session["name"],
        "status": "active" if session.get("id") else "pending",
        "working_dir": session["working_dir"],
        "system_prompt": session.get("system_prompt"),
        "model": session.get("model"),
        "effort": session.get("effort"),
        "total_cost": session["total_cost"],
        "total_turns": session["total_turns"],
    }, indent=2)


@mcp.tool()
async def delete_session(name: str) -> str:
    """Delete a Claude Code session and its workspace.

    Args:
        name: Session name
    """
    sessions = await _ensure_init()
    session = await sessions.get_by_name(name)
    if not session:
        return json.dumps({"error": f"Session '{name}' not found"})

    if session["id"]:
        await sessions.delete(session["id"])
    else:
        await sessions.db.delete_session_by_rowid(session["rowid"])

    return json.dumps({"deleted": name})


@mcp.tool()
async def get_history(name: str, limit: int = 20) -> str:
    """Get chat history for a session.

    Args:
        name: Session name
        limit: Max messages to return (default 20)
    """
    sessions = await _ensure_init()
    session = await sessions.get_by_name(name)
    if not session or not session["id"]:
        return json.dumps({"messages": []})

    messages = await sessions.db.get_messages(session["id"], limit)
    result = []
    for m in messages:
        result.append({
            "role": m["role"],
            "content": m["content"][:500] if m["content"] else "",
            "tools_used": [t["name"] for t in (m.get("tools_used") or [])] if isinstance(m.get("tools_used"), list) else [],
        })
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
async def list_files(name: str, path: str = "") -> str:
    """List files in a session's workspace.

    Args:
        name: Session name
        path: Subdirectory path (optional)
    """
    sessions = await _ensure_init()
    session = await sessions.get_by_name(name)
    if not session:
        return json.dumps({"error": f"Session '{name}' not found"})

    from pathlib import Path as P
    working_dir = P(session["working_dir"])
    target = (working_dir / path).resolve() if path else working_dir.resolve()

    if not target.is_relative_to(working_dir.resolve()) or not target.is_dir():
        return json.dumps({"error": "Invalid path"})

    entries = []
    for item in sorted(target.iterdir()):
        if item.name.startswith("."):
            continue
        entries.append({
            "name": item.name,
            "type": "directory" if item.is_dir() else "file",
            "size": item.stat().st_size if item.is_file() else None,
        })
    return json.dumps(entries, indent=2)


# ── Resources ──


@mcp.resource("sessions://list")
async def resource_sessions() -> str:
    """List all active sessions."""
    return await list_sessions()


@mcp.resource("templates://list")
async def resource_templates() -> str:
    """List available session templates."""
    import yaml
    from pathlib import Path
    templates_path = Path(__file__).resolve().parent.parent / "templates.yml"
    if not templates_path.exists():
        return json.dumps({})
    with open(templates_path) as f:
        data = yaml.safe_load(f) or {}
    return json.dumps(data, indent=2)


# ── Prompts ──


@mcp.prompt()
def code_review(code: str, language: str = "python") -> str:
    """Review code for bugs, security issues, and best practices.

    Args:
        code: The code to review
        language: Programming language
    """
    return f"Review this {language} code for bugs, security issues, performance problems, and best practices. Be concise and actionable.\n\n```{language}\n{code}\n```"


@mcp.prompt()
def refactor(code: str, goal: str = "improve readability") -> str:
    """Refactor code with a specific goal.

    Args:
        code: The code to refactor
        goal: What to improve (readability, performance, etc.)
    """
    return f"Refactor this code to {goal}. Keep functionality identical.\n\n```\n{code}\n```"


@mcp.prompt()
def write_tests(code: str, framework: str = "pytest") -> str:
    """Generate tests for code.

    Args:
        code: The code to test
        framework: Test framework to use
    """
    return f"Write comprehensive {framework} tests for this code. Cover edge cases, error paths, and happy paths.\n\n```\n{code}\n```"


@mcp.prompt()
def debug(error: str, context: str = "") -> str:
    """Debug an error with optional context.

    Args:
        error: The error message or traceback
        context: Additional context about what was happening
    """
    prompt = f"Analyze this error, find the root cause, and provide a fix.\n\nError:\n```\n{error}\n```"
    if context:
        prompt += f"\n\nContext: {context}"
    return prompt


# ── Entry point ──


def run():
    import sys
    transport = "stdio"
    for i, arg in enumerate(sys.argv):
        if arg == "--transport" and i + 1 < len(sys.argv):
            transport = sys.argv[i + 1]

    logger.info("mcp_server_starting", transport=transport)
    mcp.run(transport=transport)


if __name__ == "__main__":
    run()
