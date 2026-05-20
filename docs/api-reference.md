# API Reference

Base URL: `http://localhost:8000/api/v1`

All endpoints (except health) require `X-API-Key` header.

---

## Health

### `GET /health`

Health check. No authentication required.

**Response:**
```json
{
  "status": "ok",
  "checks": {"database": "ok", "claude_cli": "ok"},
  "meta": {"request_id": "...", "timestamp": "...", "version": "v1"}
}
```

---

## Sessions

### `POST /sessions`

Create a new session.

**Body:**
```json
{
  "name": "my-project",
  "template": "code-reviewer",
  "system_prompt": "You are a Python expert",
  "model": "claude-sonnet-4-20250514",
  "effort": "high",
  "max_turns": 50,
  "permission_mode": "auto",
  "allowed_tools": "Read,Write,Edit,Bash",
  "disallowed_tools": "Glob"
}
```

All fields except `name` are optional. `template` applies defaults that explicit fields override.

### `GET /sessions`

List sessions (paginated). Query params: `page` (default 1), `limit` (default 20).

### `GET /sessions/{name}`

Get session details.

### `DELETE /sessions/{name}`

Delete session. Returns `204 No Content`.

### `POST /sessions/{name}/repo`

Change working directory.

**Body:**
```json
{
  "working_dir": "/home/user/projects/other-repo"
}
```

---

## Chat

### `POST /sessions/{name}/chat`

Send message (synchronous).

**Body:**
```json
{
  "message": "create a hello.py",
  "model": "claude-sonnet-4-20250514",
  "system": "You are a Python expert",
  "effort": "high",
  "permission_mode": "auto",
  "output_format": {"type": "json"}
}
```

Only `message` is required.

**Headers:**
- `Idempotency-Key: <uuid>` — prevent duplicate execution

**Response:**
```json
{
  "data": {
    "session_id": "...",
    "content": "...",
    "cost": 0.003,
    "duration_ms": 4521,
    "num_turns": 2,
    "tools_used": [{"name": "Write", "input": {...}}]
  },
  "meta": {"request_id": "...", "timestamp": "...", "version": "v1"}
}
```

### `POST /sessions/{name}/chat/stream`

Send message (SSE stream). Same body as sync chat.

**Events:**

| Event | Data |
|-------|------|
| `assistant` | `{"content": "...", "tool_name": null}` |
| `tool` | `{"content": null, "tool_name": "Read"}` |
| `done` | Full response with cost, duration, tools |
| `error` | `{"error": "..."}` |

---

## History

### `GET /sessions/{name}/history`

Get chat history. Query params: `limit` (default 50).

---

## Jobs

### `POST /sessions/{name}/jobs`

Create async job. Returns `202 Accepted`.

**Body:**
```json
{
  "message": "run tests and fix failures",
  "webhook_url": "https://your-server.com/hooks/claude",
  "model": "claude-sonnet-4-20250514",
  "system": "You are a test engineer",
  "effort": "max",
  "permission_mode": "auto",
  "output_format": {"type": "json"}
}
```

Only `message` is required.

### `GET /sessions/{name}/jobs`

List jobs for a session.

### `GET /sessions/{name}/jobs/{id}`

Get job status and result.

### `POST /sessions/{name}/jobs/{id}/cancel`

Cancel a queued or running job.

---

## Files

### `POST /sessions/{name}/files`

Upload file (multipart form).

**Form fields:**
- `file` — the file (required)
- `path` — destination path within workspace (optional)

Max size: 10 MB.

### `GET /sessions/{name}/files`

List files in workspace.

### `GET /sessions/{name}/files/{path}`

Download a file.

---

## Templates

### `GET /templates`

List all available templates.

### `GET /templates/{name}`

Get template details.

### `POST /templates/reload`

Hot-reload templates from `templates.yml`.

---

## Utilities

### `POST /tokens/count`

Estimate token count.

**Body:**
```json
{
  "text": "Your text here..."
}
```

**Response:**
```json
{
  "data": {
    "characters": 100,
    "words": 20,
    "estimated_tokens": 25
  }
}
```

### `GET /usage`

Usage statistics. Query params: `user_id` (optional, defaults to API key).

### `GET /audit`

Audit trail. Query params: `user_id`, `limit` (default 50, max 200).
