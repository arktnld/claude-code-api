# Async Jobs

Fire-and-forget execution with status polling and webhook callbacks.

## Create a Job

```bash
curl -s -X POST http://localhost:8000/api/v1/sessions/my-project/jobs \
  -H "X-API-Key: my-key" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "run the full test suite and fix any failures",
    "webhook_url": "https://your-server.com/hooks/claude"
  }' | python -m json.tool
```

Returns `202 Accepted` immediately:

```json
{
  "data": {
    "id": "a1b2c3d4e5f67890",
    "status": "queued",
    "message": "run the full test suite...",
    "webhook_url": "https://your-server.com/hooks/claude",
    "created_at": "2026-05-20T12:00:00+00:00"
  },
  "meta": {"request_id": "...", "timestamp": "...", "version": "v1"}
}
```

## Job Lifecycle

```
queued → running → done | failed | cancelled
```

- **queued** — waiting (1 job runs per session at a time)
- **running** — Claude is executing
- **done** — completed successfully
- **failed** — error occurred
- **cancelled** — cancelled by user

## Poll Job Status

```bash
curl -s http://localhost:8000/api/v1/sessions/my-project/jobs/a1b2c3d4e5f67890 \
  -H "X-API-Key: my-key" | python -m json.tool
```

When done:
```json
{
  "data": {
    "id": "a1b2c3d4e5f67890",
    "status": "done",
    "result": {
      "session_id": "...",
      "content": "Fixed 3 test failures...",
      "cost": 0.05,
      "duration_ms": 15000,
      "num_turns": 8,
      "tools_used": [...]
    },
    "cost": 0.05,
    "duration_ms": 15000,
    "created_at": "...",
    "started_at": "...",
    "completed_at": "..."
  }
}
```

## Webhook Callbacks

When a job completes, the API POSTs to your `webhook_url`:

```json
{
  "event": "job.completed",
  "job": {
    "id": "a1b2c3d4e5f67890",
    "status": "done",
    "result": {...},
    "cost": 0.05,
    "duration_ms": 15000
  }
}
```

Webhook timeout is 10 seconds. Failures are logged but don't affect the job.

## List Jobs

```bash
curl -s http://localhost:8000/api/v1/sessions/my-project/jobs \
  -H "X-API-Key: my-key" | python -m json.tool
```

## Cancel a Job

```bash
curl -s -X POST http://localhost:8000/api/v1/sessions/my-project/jobs/a1b2c3d4e5f67890/cancel \
  -H "X-API-Key: my-key" | python -m json.tool
```

Only cancels `queued` or `running` jobs.

## Job Options

Jobs accept the same overrides as chat:

```json
{
  "message": "...",
  "webhook_url": "https://...",
  "model": "claude-sonnet-4-20250514",
  "system": "You are a test engineer",
  "effort": "max",
  "permission_mode": "auto",
  "output_format": {"type": "json"}
}
```

## Queue Behavior

Each session has a lock — only 1 job runs at a time per session. Additional jobs queue and execute in order. Different sessions run jobs concurrently.
