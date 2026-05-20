# Security

## API Key Authentication

All endpoints (except health check) require `X-API-Key` header. Configure keys in `.env`:

```env
API_KEYS=prod-key-abc,staging-key-xyz
```

Sessions are scoped to API keys — each key can only access its own sessions.

## Rate Limiting

Built-in per-key rate limiter:

```env
RATE_LIMIT_REQUESTS=30
RATE_LIMIT_WINDOW=60
```

Response headers on every request:
```
X-RateLimit-Limit: 30
X-RateLimit-Remaining: 28
X-RateLimit-Reset: 1716220800
```

`429 Too Many Requests` includes `Retry-After` header.

## Path Sandboxing

All file operations are restricted to `APPROVED_DIRECTORY`:

- Session workspaces created within the approved directory
- Path traversal blocked (`..`, symlinks outside boundary)
- Uses `Path.is_relative_to()` for safe comparison
- Claude's tool callbacks validate every file path before execution

## Bash Boundary Checks

When Claude uses the Bash tool:

- Commands are parsed for dangerous patterns
- Filesystem-modifying commands validated against approved paths
- Blocked patterns: `rm -rf /`, fork bombs, `curl | bash`

## Input Moderation

User messages are scanned for:

| Pattern | Description |
|---------|-------------|
| `ignore previous instructions` | Prompt injection |
| `you are now DAN/jailbreak` | Jailbreak attempts |
| `system: you are` | System prompt injection |
| `<\|im_start\|>` | Token injection |
| `rm -rf /` | Destructive commands |
| `:(){ :\|:& };:` | Fork bomb |
| `curl ... \| bash` | Remote code execution |

## Budget Limits

Two layers of cost protection:

```env
CLAUDE_MAX_COST_PER_REQUEST=5.0    # per single request
CLAUDE_MAX_COST_PER_USER=50.0      # total per API key
```

Exceeded budget returns `429` with explanation.

## Security Headers

Every response includes:

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-Request-ID: <uuid>
```

## Request Size Limit

Request body capped at **2 MB** (returns `413 Payload Too Large`).

## Tool Permission Callback

Claude's tool calls are intercepted by a security callback that validates:
- File paths are within approved directory
- Bash commands don't target sensitive paths
- No dangerous command patterns

This runs **before** every tool execution — not just at the API level.
