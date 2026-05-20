# Configuration

All settings via environment variables or `.env` file.

## Server

| Variable | Default | Description |
|----------|---------|-------------|
| `API_HOST` | `0.0.0.0` | Server bind address |
| `API_PORT` | `8000` | Server port |
| `ENABLE_DOCS` | `true` | Enable Swagger UI at `/docs` and ReDoc at `/redoc` |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `CORS_ORIGINS` | `*` | Comma-separated CORS origins |

## Authentication

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEYS` | *(empty)* | Comma-separated API keys. Empty = no auth |
| `ANTHROPIC_API_KEY` | *(empty)* | Anthropic API key. Empty = use CLI login |

## Claude

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDE_CLI_PATH` | *(auto-detect)* | Path to `claude` binary |
| `CLAUDE_MODEL` | *(CLI default)* | Default model (e.g., `claude-sonnet-4-20250514`) |
| `CLAUDE_MAX_TURNS` | `25` | Max tool-use turns per request |
| `CLAUDE_TIMEOUT_SECONDS` | `300` | Request timeout in seconds |
| `CLAUDE_EFFORT` | *(none)* | Default effort level: `low`, `medium`, `high`, `max` |
| `CLAUDE_PERMISSION_MODE` | *(none)* | Default permission mode |
| `CLAUDE_SYSTEM_PROMPT` | *(none)* | Default system prompt |
| `CLAUDE_ALLOWED_TOOLS` | `Read,Write,Edit,Bash,...` | Comma-separated allowed tools |
| `CLAUDE_DISALLOWED_TOOLS` | *(empty)* | Comma-separated blocked tools |

## Security

| Variable | Default | Description |
|----------|---------|-------------|
| `APPROVED_DIRECTORY` | `.` | Root directory — sessions can only access within |
| `SANDBOX_ENABLED` | `true` | OS-level sandboxing for Bash commands |
| `SANDBOX_EXCLUDED_COMMANDS` | `git,npm,pip,...` | Commands exempt from sandbox |
| `CLAUDE_MAX_COST_PER_REQUEST` | `5.0` | Max USD per single request |
| `CLAUDE_MAX_COST_PER_USER` | `50.0` | Max USD total per API key |

## Sessions

| Variable | Default | Description |
|----------|---------|-------------|
| `SESSION_TIMEOUT_HOURS` | `24` | Session expiry time |
| `MAX_SESSIONS_PER_USER` | `10` | Max sessions per API key (oldest auto-evicted) |

## Rate Limiting

| Variable | Default | Description |
|----------|---------|-------------|
| `RATE_LIMIT_REQUESTS` | `30` | Max requests per window |
| `RATE_LIMIT_WINDOW` | `60` | Window duration in seconds |

## Storage

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite+aiosqlite:///data/sessions.db` | SQLite database path |

## Config Priority

Settings can be defined at multiple levels. Priority order (highest wins):

```
Per-request override  →  Session config  →  Environment variable  →  Default
```

Example: If `CLAUDE_MODEL=claude-sonnet-4-20250514` in `.env`, but a session was created with `model: claude-opus-4-20250514`, and a chat request passes `model: claude-haiku-4-5-20251001` — the request uses Haiku.
