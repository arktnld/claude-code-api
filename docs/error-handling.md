# Error Handling

All errors follow [RFC 9457 Problem Details](https://www.rfc-editor.org/rfc/rfc9457.html) format with `application/problem+json` content type.

## Error Format

```json
{
  "type": "about:blank",
  "title": "Not Found",
  "status": 404,
  "detail": "Session not found",
  "instance": "http://localhost:8000/api/v1/sessions/nonexistent",
  "request_id": "abc123"
}
```

| Field | Description |
|-------|-------------|
| `type` | Error type URI (or `about:blank`) |
| `title` | Short human-readable summary |
| `status` | HTTP status code |
| `detail` | Specific explanation |
| `instance` | URL that generated the error |
| `request_id` | Unique request ID for debugging |

## Validation Errors

```json
{
  "type": "about:blank",
  "title": "Validation Error",
  "status": 422,
  "detail": "2 validation error(s)",
  "errors": [
    {
      "field": "body -> message",
      "message": "String should have at least 1 character",
      "type": "string_too_short"
    },
    {
      "field": "body -> model",
      "message": "String should have at most 100 characters",
      "type": "string_too_long"
    }
  ],
  "request_id": "def456"
}
```

## Status Codes

| Status | Title | When |
|--------|-------|------|
| `400` | Bad Request | Malformed request |
| `401` | Unauthorized | Missing or invalid API key |
| `403` | Forbidden | Access denied |
| `404` | Not Found | Session or resource not found |
| `405` | Method Not Allowed | Wrong HTTP method |
| `409` | Conflict | Job already completed (can't cancel) |
| `413` | Payload Too Large | Request body > 2MB or file > 10MB |
| `422` | Validation Error | Invalid request body |
| `429` | Too Many Requests | Rate limit or budget exceeded |
| `502` | Bad Gateway | Claude SDK error |
| `504` | Gateway Timeout | Claude request timed out |

## Claude-Specific Errors

Claude errors include a typed `type` field:

```json
{
  "type": "claude:timeout",
  "title": "Gateway Timeout",
  "status": 504,
  "detail": "Claude did not respond within 300 seconds"
}
```

```json
{
  "type": "claude:ClaudeError",
  "title": "Bad Gateway",
  "status": 502,
  "detail": "Claude process exited with code 1"
}
```
