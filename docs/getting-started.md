# Getting Started

## Prerequisites

- **Python 3.11+**
- **Claude Code CLI** installed and authenticated

### Install Claude Code CLI

```bash
npm install -g @anthropic-ai/claude-code
claude auth login
```

Verify it works:
```bash
claude --version
```

## Installation

```bash
git clone https://github.com/arktnld/claude-code-api.git
cd claude-code-api

python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Configuration

```bash
cp .env.example .env
```

Minimum config in `.env`:
```env
APPROVED_DIRECTORY=/home/user/projects
API_KEYS=my-secret-key
```

`APPROVED_DIRECTORY` is the root where all session workspaces are created. Claude can only access files within this directory.

## Start the Server

```bash
make dev
```

Server runs at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

## Your First Session

### 1. Create a session

```bash
curl -s -X POST http://localhost:8000/api/v1/sessions \
  -H "X-API-Key: my-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"name": "hello-world"}' | python -m json.tool
```

This creates a workspace directory at `APPROVED_DIRECTORY/hello-world`.

### 2. Send a message

```bash
curl -s -X POST http://localhost:8000/api/v1/sessions/hello-world/chat \
  -H "X-API-Key: my-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"message": "create a Python script that prints the fibonacci sequence up to 100"}' | python -m json.tool
```

Claude will use the Write tool to create the file and return the result.

### 3. Continue the conversation

```bash
curl -s -X POST http://localhost:8000/api/v1/sessions/hello-world/chat \
  -H "X-API-Key: my-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"message": "now add type hints and docstrings"}' | python -m json.tool
```

The session maintains full conversation context — Claude remembers everything from previous messages.

### 4. Check history

```bash
curl -s http://localhost:8000/api/v1/sessions/hello-world/history \
  -H "X-API-Key: my-secret-key" | python -m json.tool
```

### 5. Clean up

```bash
curl -s -X DELETE http://localhost:8000/api/v1/sessions/hello-world \
  -H "X-API-Key: my-secret-key" -w "\nHTTP %{http_code}\n"
```

## Next Steps

- [Authentication](authentication.md) — API keys and Claude auth modes
- [Sessions](sessions.md) — Templates, lifecycle, working directories
- [Chat](chat.md) — Streaming, idempotency, overrides
- [Configuration](configuration.md) — All environment variables
