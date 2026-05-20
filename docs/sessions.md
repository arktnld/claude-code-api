# Sessions

Sessions are persistent workspaces that maintain conversation context with Claude.

## Lifecycle

```
Create → Pending → First Chat → Active → (Resume) → Delete
```

1. **Pending** — Session created, workspace directory ready, no chat yet
2. **Active** — After first chat, Claude has assigned a session ID. Conversations auto-resume
3. **Expired** — After `SESSION_TIMEOUT_HOURS`. Auto-retries as fresh session on next chat

## Create a Session

```bash
curl -s -X POST http://localhost:8000/api/v1/sessions \
  -H "X-API-Key: my-key" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-project"}' | python -m json.tool
```

A directory is created at `APPROVED_DIRECTORY/my-project`.

### With a Template

```bash
curl -s -X POST http://localhost:8000/api/v1/sessions \
  -H "X-API-Key: my-key" \
  -H "Content-Type: application/json" \
  -d '{"name": "review-auth", "template": "code-reviewer"}' | python -m json.tool
```

Templates pre-configure `system_prompt` and `effort`. Explicit values override template defaults.

### With Custom Config

```bash
curl -s -X POST http://localhost:8000/api/v1/sessions \
  -H "X-API-Key: my-key" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-agent",
    "system_prompt": "You are a Python asyncio expert",
    "model": "claude-sonnet-4-20250514",
    "effort": "high",
    "max_turns": 50,
    "permission_mode": "auto",
    "allowed_tools": "Read,Write,Edit,Bash",
    "disallowed_tools": "Glob"
  }' | python -m json.tool
```

## Templates

12 pre-configured agent profiles in `templates.yml`:

| Template | Focus |
|----------|-------|
| `code-reviewer` | Bugs, security, best practices |
| `devops` | Docker, CI/CD, infrastructure |
| `refactor` | Structure, duplication, naming |
| `test-writer` | Unit/integration tests (pytest) |
| `docs` | README, API docs, docstrings |
| `debug` | Error analysis, root cause finding |
| `architect` | System design, API design, tech stacks |
| `security` | OWASP, auth flows, hardening |
| `performance` | Profiling, query optimization, latency |
| `api-designer` | REST design, OpenAPI, pagination |
| `data-engineer` | ETL, schemas, SQL/NoSQL |
| `frontend` | Responsive UI, Core Web Vitals, a11y |

### List Templates

```bash
curl -s http://localhost:8000/api/v1/templates -H "X-API-Key: my-key" | python -m json.tool
```

### Customize Templates

Edit `templates.yml` at the project root:

```yaml
my-custom-agent:
  system_prompt: >
    You are a specialist in X. Do Y and Z.
  effort: high
```

Hot-reload without restart:
```bash
curl -s -X POST http://localhost:8000/api/v1/templates/reload -H "X-API-Key: my-key"
```

## List Sessions

```bash
curl -s "http://localhost:8000/api/v1/sessions?page=1&limit=10" \
  -H "X-API-Key: my-key" | python -m json.tool
```

Paginated. Only shows sessions owned by your API key.

## Get Session

```bash
curl -s http://localhost:8000/api/v1/sessions/my-project \
  -H "X-API-Key: my-key" | python -m json.tool
```

## Delete Session

```bash
curl -s -X DELETE http://localhost:8000/api/v1/sessions/my-project \
  -H "X-API-Key: my-key"
# Returns 204 No Content
```

## Change Working Directory

Point a session to a different directory:

```bash
curl -s -X POST http://localhost:8000/api/v1/sessions/my-project/repo \
  -H "X-API-Key: my-key" \
  -H "Content-Type: application/json" \
  -d '{"working_dir": "/home/user/projects/other-repo"}'
```

Must be within `APPROVED_DIRECTORY`.

## Session Limits

```env
MAX_SESSIONS_PER_USER=10     # oldest auto-evicted when exceeded
SESSION_TIMEOUT_HOURS=24     # sessions expire after this
```

## Auto-Resume

When you chat with an active session, the API automatically resumes the Claude conversation. If the underlying Claude session has expired, it transparently retries as a fresh conversation.
