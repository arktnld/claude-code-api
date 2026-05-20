from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


def _csv_to_list(v: str | list | None) -> list[str]:
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return v
    return [x.strip() for x in v.split(",") if x.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # API Server
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_keys: str = ""  # comma-separated

    # Claude CLI / SDK
    anthropic_api_key: str = ""
    claude_cli_path: Optional[str] = None
    claude_model: Optional[str] = None
    claude_max_turns: int = 25
    claude_timeout_seconds: int = 300
    claude_system_prompt: Optional[str] = None
    claude_permission_mode: Optional[str] = None  # default, plan, bypassPermissions
    claude_effort: Optional[str] = None  # low, medium, high, max

    # Tools (comma-separated strings to avoid JSON parse issues)
    claude_allowed_tools: str = "Read,Write,Edit,Bash,Glob,Grep,LS,MultiEdit,NotebookRead,NotebookEdit,WebFetch,WebSearch"
    claude_disallowed_tools: str = ""

    # Sandbox
    sandbox_enabled: bool = True
    sandbox_excluded_commands: str = "git,npm,pip,poetry,make,docker"

    # Budget
    claude_max_cost_per_request: float = 5.0
    claude_max_cost_per_user: float = 50.0

    # Retry
    claude_retry_max_attempts: int = 2
    claude_retry_base_delay: float = 1.0
    claude_retry_backoff_factor: float = 2.0
    claude_retry_max_delay: float = 10.0

    # Sessions
    approved_directory: str = "."
    database_url: str = "sqlite+aiosqlite:///data/sessions.db"
    session_timeout_hours: int = 24
    max_sessions_per_user: int = 10

    # Security
    rate_limit_requests: int = 30
    rate_limit_window: int = 60
    cors_origins: str = "*"

    # Server
    enable_docs: bool = True
    log_level: str = "INFO"

    @property
    def api_keys_list(self) -> list[str]:
        return _csv_to_list(self.api_keys)

    @property
    def allowed_tools_list(self) -> list[str] | None:
        result = _csv_to_list(self.claude_allowed_tools)
        return result if result else None

    @property
    def disallowed_tools_list(self) -> list[str] | None:
        result = _csv_to_list(self.claude_disallowed_tools)
        return result if result else None

    @property
    def excluded_commands_list(self) -> list[str]:
        return _csv_to_list(self.sandbox_excluded_commands)

    @property
    def cors_origins_list(self) -> list[str]:
        return _csv_to_list(self.cors_origins)

    @property
    def db_path(self) -> Path:
        url = self.database_url
        path = url.split("///", 1)[-1] if "///" in url else url
        return Path(path)

    @property
    def approved_path(self) -> Path:
        return Path(self.approved_directory).resolve()


settings = Settings()
