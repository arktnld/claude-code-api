# Files

Upload, download, and list files in session workspaces.

## Upload a File

```bash
curl -s -X POST http://localhost:8000/api/v1/sessions/my-project/files \
  -H "X-API-Key: my-key" \
  -F "file=@local-file.py" \
  -F "path=src/main.py" | python -m json.tool
```

| Field | Description |
|-------|-------------|
| `file` | File to upload (multipart) |
| `path` | Destination path within workspace (optional, defaults to filename) |

- Max file size: **10 MB**
- Path must be within the session's workspace directory
- Subdirectories are created automatically

## List Files

```bash
curl -s http://localhost:8000/api/v1/sessions/my-project/files \
  -H "X-API-Key: my-key" | python -m json.tool
```

```json
{
  "data": {
    "files": [
      {"name": "main.py", "size": 1234, "type": "file"},
      {"name": "src", "type": "directory"}
    ],
    "working_dir": "/home/user/projects/my-project"
  }
}
```

Hidden files (starting with `.`) are excluded from listing.

## Download a File

```bash
curl -s http://localhost:8000/api/v1/sessions/my-project/files/src/main.py \
  -H "X-API-Key: my-key" -o downloaded.py
```

Returns the file with appropriate `Content-Type` header. Path traversal attempts (e.g., `../../etc/passwd`) are blocked.
