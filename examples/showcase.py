#!/usr/bin/env python3
"""
Claude Code API — Showcase Demo
================================
Demonstrates all API features in sequence.

Usage:
  API_KEY=your-key python examples/showcase.py

Requires: pip install httpx
Server must be running: make dev
"""

import httpx
import json
import os
import sys
import time

BASE = "http://localhost:8000/api/v1"
KEY = os.environ.get("API_KEY", "dev-key-123")
HEADERS = {"X-API-Key": KEY, "Content-Type": "application/json"}

# Colors
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def log_body(body):
    """Show request body."""
    formatted = json.dumps(body, indent=2, ensure_ascii=False)
    for line in formatted.split("\n"):
        print(f"    {DIM}{line}{RESET}")


def api(method, path, **kwargs):
    """Make API call with full logging."""
    body = kwargs.get("json")
    is_slow = kwargs.pop("slow", False)

    # Show request
    print(f"  {DIM}→ {method} {BASE}{path}{RESET}")
    if body:
        log_body(body)

    # Show waiting indicator for slow requests
    if is_slow:
        print(f"  {YELLOW}⏳ Waiting for response...{RESET}", end="", flush=True)

    start = time.time()
    r = httpx.request(method, f"{BASE}{path}", headers=HEADERS, timeout=300, **kwargs)
    elapsed_ms = int((time.time() - start) * 1000)

    if is_slow:
        print(f"\r  {GREEN}✓ Response received ({elapsed_ms}ms){RESET}                    ")
    else:
        print(f"  {DIM}← {r.status_code} ({elapsed_ms}ms){RESET}")

    if r.status_code == 204:
        return None

    data = r.json()
    if r.status_code >= 400:
        print(f"  {RED}✗ ERROR {r.status_code}: {data.get('detail', data)}{RESET}")
        sys.exit(1)
    return data


def section(num, title, endpoint=""):
    print(f"\n{BOLD}{'─'*60}{RESET}")
    print(f"  {BOLD}{num}. {title}{RESET}")
    if endpoint:
        print(f"  {DIM}Endpoint: {endpoint}{RESET}")
    print(f"{BOLD}{'─'*60}{RESET}\n")


def show_response(label, content, max_lines=6):
    print(f"\n  {BOLD}{label}:{RESET}")
    lines = content.split("\n")
    for line in lines[:max_lines]:
        print(f"  {DIM}│{RESET} {line}")
    if len(lines) > max_lines:
        print(f"  {DIM}│ ... ({len(lines) - max_lines} more lines){RESET}")


def main():
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"  {BOLD}Claude Code API — Showcase Demo{RESET}")
    print(f"  {DIM}Server: {BASE}{RESET}")
    print(f"  {DIM}API Key: {KEY[:8]}{'...' if len(KEY) > 8 else ''}{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")

    total_start = time.time()

    # ──────────────────────────────────────────────────────────
    section(1, "Health Check", "GET /api/v1/health")
    health = api("GET", "/health")
    db_ok = health["checks"]["database"] == "ok"
    cli_ok = health["checks"]["claude_cli"] == "ok"
    print(f"  Database:   {GREEN + 'ok' + RESET if db_ok else RED + 'error' + RESET}")
    print(f"  Claude CLI: {GREEN + 'ok' + RESET if cli_ok else RED + 'error' + RESET}")

    # ──────────────────────────────────────────────────────────
    section(2, "Available Templates", "GET /api/v1/templates")
    templates = api("GET", "/templates")
    for name, t in templates["data"].items():
        print(f"  {CYAN}•{RESET} {BOLD}{name}{RESET} (effort: {t.get('effort', '-')})")
        print(f"    {DIM}{t['system_prompt'][:75]}...{RESET}")
    print(f"\n  {DIM}Total: {len(templates['data'])} templates{RESET}")

    # ──────────────────────────────────────────────────────────
    section(3, "Create Session", "POST /api/v1/sessions")
    session = api("POST", "/sessions", json={"name": "demo-showcase"})
    sd = session["data"]
    print(f"  Name:        {sd['name']}")
    print(f"  Working Dir: {sd['working_dir']}")
    print(f"  Status:      {YELLOW}{sd['status']}{RESET} (no chat yet)")
    print(f"  User:        {sd['user_id']}")

    # ──────────────────────────────────────────────────────────
    section(4, "Chat — Claude Creates Code", "POST /api/v1/sessions/demo-showcase/chat")
    chat = api("POST", "/sessions/demo-showcase/chat", slow=True, json={
        "message": "Create a Python function in calculator.py that handles add, subtract, multiply, divide with proper error handling for division by zero."
    })
    d = chat["data"]
    print(f"  Session ID:  {d['session_id'][:16]}...")
    print(f"  Cost:        ${d['cost']:.4f}")
    print(f"  Duration:    {d['duration_ms']}ms")
    print(f"  Turns:       {d['num_turns']}")
    print(f"  Tools Used:  {[t['name'] for t in (d['tools_used'] or [])]}")
    show_response("Claude Response", d["content"])

    # ──────────────────────────────────────────────────────────
    section(5, "Follow-up Chat (Context Maintained)", "POST /api/v1/sessions/demo-showcase/chat")
    print(f"  {CYAN}ℹ Session context preserved — Claude remembers previous code{RESET}\n")
    chat2 = api("POST", "/sessions/demo-showcase/chat", slow=True, json={
        "message": "Now add type hints and a __main__ block with example usage"
    })
    d2 = chat2["data"]
    print(f"  Cost:        ${d2['cost']:.4f}")
    print(f"  Tools Used:  {[t['name'] for t in (d2['tools_used'] or [])]}")
    show_response("Claude Response", d2["content"])

    # ──────────────────────────────────────────────────────────
    section(6, "Chat History (Paginated)", "GET /api/v1/sessions/demo-showcase/history?page=1&limit=10")
    history = api("GET", "/sessions/demo-showcase/history?page=1&limit=10")
    for msg in history["data"]:
        icon = "👤" if msg["role"] == "user" else "🤖"
        content = (msg["content"] or "")[:70]
        print(f"  {icon} [{msg['role']:9s}] {content}...")
    pg = history.get("pagination", {})
    print(f"\n  {DIM}Pagination: page {pg.get('page')}/{pg.get('pages')} | total: {pg.get('total')} | limit: {pg.get('limit')}{RESET}")

    # ──────────────────────────────────────────────────────────
    section(7, "Session with Template", "POST /api/v1/sessions")
    review_session = api("POST", "/sessions", json={
        "name": "demo-reviewer",
        "template": "code-reviewer"
    })
    rd = review_session["data"]
    print(f"  Name:          {rd['name']}")
    print(f"  System Prompt: {(rd['system_prompt'] or '')[:60]}...")
    print(f"  Effort:        {rd['effort']} (from template)")
    print(f"  Status:        {YELLOW}{rd['status']}{RESET}")

    # ──────────────────────────────────────────────────────────
    section(8, "Chat with Per-Request Overrides", "POST /api/v1/sessions/demo-reviewer/chat")
    print(f"  {CYAN}ℹ Overriding effort to 'max' for this request only{RESET}\n")
    chat3 = api("POST", "/sessions/demo-reviewer/chat", slow=True, json={
        "message": "Review this code:\n\ndef calc(a, b, op):\n  if op == '+':\n    return a+b\n  if op == '/':\n    return a/b",
        "effort": "max",
    })
    d3 = chat3["data"]
    print(f"  Cost:        ${d3['cost']:.4f}")
    print(f"  Duration:    {d3['duration_ms']}ms")
    show_response("Code Review", d3["content"], max_lines=8)

    # ──────────────────────────────────────────────────────────
    section(9, "List Sessions (Paginated)", "GET /api/v1/sessions?page=1&limit=10")
    sessions = api("GET", "/sessions?page=1&limit=10")
    print(f"  {'Name':<20s} {'Status':<10s} {'Cost':>8s}")
    print(f"  {'─'*20} {'─'*10} {'─'*8}")
    for s in sessions["data"]:
        sc = GREEN if s["status"] == "active" else YELLOW
        print(f"  {s['name']:<20s} {sc}{s['status']:<10s}{RESET} ${s['total_cost']:>7.4f}")
    pg = sessions.get("pagination", {})
    print(f"\n  {DIM}Pagination: page {pg.get('page')}/{pg.get('pages')} | total: {pg.get('total')} | limit: {pg.get('limit')}{RESET}")

    # ──────────────────────────────────────────────────────────
    section(10, "Token Estimation", "POST /api/v1/tokens/count")
    tokens = api("POST", "/tokens/count", json={
        "text": "def hello():\n    print('Hello, World!')\n\nhello()"
    })
    td = tokens["data"]
    print(f"  Characters:       {td['characters']}")
    print(f"  Words:            {td['words']}")
    print(f"  Estimated Tokens: {td['estimated_tokens']}")

    # ──────────────────────────────────────────────────────────
    section(11, "Usage Statistics", "GET /api/v1/usage")
    usage = api("GET", "/usage")
    ud = usage["data"]
    print(f"  Sessions:    {ud['sessions']}")
    print(f"  Messages:    {ud['messages']}")
    print(f"  Total Cost:  ${ud['cost']:.4f}")
    print(f"  Total Turns: {ud['turns']}")
    jobs = ud.get("jobs", {})
    print(f"  Jobs:        {jobs.get('total', 0)} total, {jobs.get('completed', 0) or 0} completed")

    # ──────────────────────────────────────────────────────────
    section(12, "Audit Trail (Paginated)", "GET /api/v1/audit?page=1&limit=5")
    audit = api("GET", "/audit?page=1&limit=5")
    for entry in audit["data"]:
        sname = entry.get("session_name", "?")
        role = entry["role"]
        content = (entry["content"] or "")[:55]
        print(f"  [{sname:<15s}] {role:>9s}: {content}...")
    pg = audit.get("pagination", {})
    print(f"\n  {DIM}Pagination: page {pg.get('page')}/{pg.get('pages')} | total: {pg.get('total')} | limit: {pg.get('limit')}{RESET}")

    # ──────────────────────────────────────────────────────────
    section(13, "Cleanup", "DELETE /api/v1/sessions/{name}")
    api("DELETE", "/sessions/demo-showcase")
    api("DELETE", "/sessions/demo-reviewer")

    # ──────────────────────────────────────────────────────────
    total_elapsed = time.time() - total_start
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"  {GREEN}{BOLD}Showcase complete!{RESET}")
    print(f"  {DIM}Total time: {total_elapsed:.1f}s{RESET}")
    print(f"{BOLD}{'='*60}{RESET}\n")


if __name__ == "__main__":
    main()
