# Authentication

Claude Code API has two layers of authentication: **API authentication** (who can access the API) and **Claude authentication** (how Claude Code CLI authenticates with Anthropic).

## API Authentication

Control who can call your API endpoints.

### API Keys

Set `API_KEYS` in `.env` with comma-separated keys:

```env
API_KEYS=key-production-abc123,key-staging-xyz789
```

Pass the key in every request:
```bash
curl -H "X-API-Key: key-production-abc123" http://localhost:8000/api/v1/sessions
```

### No Auth Mode

Leave `API_KEYS` empty to disable authentication (development only):

```env
API_KEYS=
```

> **Warning:** Never run without auth in production.

### Session Ownership

Each session is scoped to the API key that created it. Key `A` cannot access sessions created by key `B`.

## Claude Authentication

How the underlying Claude Code CLI authenticates with Anthropic.

### Option 1: CLI Login (Recommended)

If you've already logged in via Claude Code CLI:

```bash
claude auth login
```

Leave `ANTHROPIC_API_KEY` empty in `.env`. The API uses your existing Max/Pro plan — no additional API charges.

### Option 2: API Key

Set the Anthropic API key directly:

```env
ANTHROPIC_API_KEY=sk-ant-...
```

This charges against your Anthropic API billing. Useful for server environments where CLI login isn't practical.

| Mode | Billing | Setup |
|------|---------|-------|
| CLI login | Your Max/Pro plan | `claude auth login` on the server |
| API key | Anthropic API billing | Set `ANTHROPIC_API_KEY` in `.env` |

## Rate Limiting

Built-in rate limiter protects against abuse:

```env
RATE_LIMIT_REQUESTS=30    # requests per window
RATE_LIMIT_WINDOW=60      # window in seconds
```

Every response includes rate limit headers:
```
X-RateLimit-Limit: 30
X-RateLimit-Remaining: 28
X-RateLimit-Reset: 1716220800
```

When exceeded, returns `429 Too Many Requests` with `Retry-After` header.

## Budget Limits

Per-request and per-user cost caps prevent runaway spending:

```env
CLAUDE_MAX_COST_PER_REQUEST=5.0    # max USD per single request
CLAUDE_MAX_COST_PER_USER=50.0      # max USD total per API key
```

When budget is exceeded, returns `429` with explanation.
