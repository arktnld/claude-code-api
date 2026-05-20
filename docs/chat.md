# Chat

Send messages to Claude and receive responses — synchronously or via SSE streaming.

## Sync Chat

```bash
curl -s -X POST http://localhost:8000/api/v1/sessions/my-project/chat \
  -H "X-API-Key: my-key" \
  -H "Content-Type: application/json" \
  -d '{"message": "create a REST API with FastAPI"}' | python -m json.tool
```

### Response

```json
{
  "data": {
    "session_id": "555a982f-...",
    "content": "I've created the FastAPI application...",
    "cost": 0.012,
    "duration_ms": 8500,
    "num_turns": 4,
    "tools_used": [
      {"name": "Write", "input": {"file_path": "main.py", "content": "..."}},
      {"name": "Write", "input": {"file_path": "requirements.txt", "content": "..."}}
    ]
  },
  "meta": {"request_id": "abc123", "timestamp": "...", "version": "v1"}
}
```

## Streaming Chat (SSE)

Real-time Server-Sent Events stream:

```bash
curl -N -X POST http://localhost:8000/api/v1/sessions/my-project/chat/stream \
  -H "X-API-Key: my-key" \
  -H "Content-Type: application/json" \
  -d '{"message": "read and explain main.py"}'
```

### Event Types

```
id: 1
event: tool
data: {"content": null, "tool_name": "Read"}

id: 2
event: assistant
data: {"content": "Here's what main.py does...", "tool_name": null}

id: 3
event: done
data: {"session_id": "...", "content": "...", "cost": 0.02, "duration_ms": 3200, ...}
```

| Event | Description |
|-------|-------------|
| `assistant` | Text content from Claude |
| `tool` | Tool being executed (Read, Write, Bash, etc.) |
| `done` | Final summary with cost, duration, tools used |
| `error` | Error occurred during execution |

### Features

- **Event IDs** — sequential `id` field enables reconnect via `Last-Event-ID`
- **UTF-8** — no escaped unicode, native encoding
- **Heartbeat** — ping every 15s keeps connection alive

## Per-Request Overrides

Override session defaults on any chat request:

```bash
curl -s -X POST http://localhost:8000/api/v1/sessions/my-project/chat \
  -H "X-API-Key: my-key" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "optimize this query",
    "model": "claude-sonnet-4-20250514",
    "system": "You are a PostgreSQL expert",
    "effort": "max",
    "permission_mode": "auto"
  }' | python -m json.tool
```

| Field | Description |
|-------|-------------|
| `message` | **(required)** The prompt |
| `model` | Override Claude model |
| `system` | Override system prompt |
| `effort` | `low`, `medium`, `high`, `max` |
| `permission_mode` | `auto`, `default`, etc. |
| `output_format` | Structured output format |

Priority: **per-request override > session config > env global config**

## Idempotency

Prevent duplicate execution with `Idempotency-Key` header:

```bash
curl -s -X POST http://localhost:8000/api/v1/sessions/my-project/chat \
  -H "X-API-Key: my-key" \
  -H "Idempotency-Key: unique-uuid-here" \
  -H "Content-Type: application/json" \
  -d '{"message": "deploy to production"}'
```

Same key within TTL returns cached response. Useful for retry-safe integrations.

## Chat History

Retrieve all messages for a session:

```bash
curl -s "http://localhost:8000/api/v1/sessions/my-project/history?limit=50" \
  -H "X-API-Key: my-key" | python -m json.tool
```

Returns both user messages and assistant responses in chronological order.
