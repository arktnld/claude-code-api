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


def log_request(method, path):
    print(f"  {DIM}→ {method} {BASE}{path}{RESET}")


def log_waiting(msg="Waiting for Claude response"):
    print(f"  {YELLOW}⏳ {msg}...{RESET}", end="", flush=True)


def log_done(elapsed_ms=None):
    suffix = f" ({elapsed_ms}ms)" if elapsed_ms else ""
    print(f"\r  {GREEN}✓ Done{suffix}{RESET}                              ")


def log_info(msg):
    print(f"  {CYAN}ℹ {msg}{RESET}")


def api(method, path, wait_msg=None, **kwargs):
    """Make API call with logging."""
    log_request(method, path)
    if wait_msg:
        log_waiting(wait_msg)

    start = time.time()
    r = httpx.request(method, f"{BASE}{path}", headers=HEADERS, timeout=300, **kwargs)
    elapsed = int((time.time() - start) * 1000)

    if wait_msg:
        log_done(elapsed)

    if r.status_code == 204:
        log_info("204 No Content")
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
        print(f"  {DIM}{endpoint}{RESET}")
    print(f"{BOLD}{'─'*60}{RESET}\n")


def show(data, indent=2):
    print(json.dumps(data, indent=indent, ensure_ascii=False))


def main():
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"  {BOLD}Claude Code API — Showcase Demo{RESET}")
    print(f"  {DIM}Server: {BASE}{RESET}")
    print(f"  {DIM}API Key: {KEY[:8]}...{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")

    total_start = time.time()

    # ──────────────────────────────────────────────────────────
    section(1, "Health Check", "GET /health")
    health = api("GET", "/health")
    db_status = health["checks"]["database"]
    cli_status = health["checks"]["claude_cli"]
    print(f"  Database: {GREEN if db_status == 'ok' else RED}{db_status}{RESET}")
    print(f"  Claude CLI: {GREEN if cli_status == 'ok' else RED}{cli_status}{RESET}")

    # ──────────────────────────────────────────────────────────
    section(2, "Available Templates", "GET /templates")
    templates = api("GET", "/templates")
    for name, t in templates["data"].items():
        print(f"  {CYAN}•{RESET} {BOLD}{name}{RESET} (effort: {t.get('effort', '-')})")
        print(f"    {DIM}{t['system_prompt'][:75]}...{RESET}")
    print(f"\n  {DIM}Total: {len(templates['data'])} templates{RESET}")

    # ──────────────────────────────────────────────────────────
    section(3, "Create Session", "POST /sessions")
    log_info('Creating session "demo-showcase" with default settings')
    session = api("POST", "/sessions", json={"name": "demo-showcase"})
    print(f"  Name:        {session['data']['name']}")
    print(f"  Working Dir: {session['data']['working_dir']}")
    print(f"  Status:      {YELLOW}{session['data']['status']}{RESET} (no chat yet)")
    print(f"  User:        {session['data']['user_id']}")

    # ──────────────────────────────────────────────────────────
    section(4, "Chat — Claude Creates Code", "POST /sessions/demo-showcase/chat")
    log_info('Asking Claude to create calculator.py')
    chat = api("POST", "/sessions/demo-showcase/chat",
        wait_msg="Claude is writing code",
        json={
            "message": "Create a Python function in calculator.py that handles add, subtract, multiply, divide with proper error handling for division by zero."
        })
    d = chat["data"]
    print(f"  Session ID:  {d['session_id'][:16]}...")
    print(f"  Cost:        ${d['cost']:.4f}")
    print(f"  Duration:    {d['duration_ms']}ms")
    print(f"  Turns:       {d['num_turns']}")
    print(f"  Tools Used:  {[t['name'] for t in (d['tools_used'] or [])]}")
    print(f"\n  {BOLD}Response:{RESET}")
    for line in d["content"][:400].split("\n"):
        print(f"  {DIM}│{RESET} {line}")

    # ──────────────────────────────────────────────────────────
    section(5, "Follow-up Chat (Context Maintained)", "POST /sessions/demo-showcase/chat")
    log_info("Session context is preserved — Claude remembers previous code")
    chat2 = api("POST", "/sessions/demo-showcase/chat",
        wait_msg="Claude is improving code",
        json={
            "message": "Now add type hints and a __main__ block with example usage"
        })
    d2 = chat2["data"]
    print(f"  Cost:        ${d2['cost']:.4f}")
    print(f"  Tools Used:  {[t['name'] for t in (d2['tools_used'] or [])]}")
    print(f"\n  {BOLD}Response:{RESET}")
    for line in d2["content"][:400].split("\n"):
        print(f"  {DIM}│{RESET} {line}")

    # ──────────────────────────────────────────────────────────
    section(6, "Chat History", "GET /sessions/demo-showcase/history")
    history = api("GET", "/sessions/demo-showcase/history?limit=10")
    print(f"  {DIM}Messages in session:{RESET}")
    for msg in history["data"]:
        role = msg["role"]
        icon = "👤" if role == "user" else "🤖"
        content = (msg["content"] or "")[:70]
        print(f"  {icon} [{role:9s}] {content}...")

    # ──────────────────────────────────────────────────────────
    section(7, "Session with Template", "POST /sessions")
    log_info('Creating session "demo-reviewer" with template: code-reviewer')
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
    section(8, "Chat with Per-Request Overrides", "POST /sessions/demo-reviewer/chat")
    log_info("Overriding effort to 'max' for this request only")
    chat3 = api("POST", "/sessions/demo-reviewer/chat",
        wait_msg="Code reviewer analyzing (effort: max)",
        json={
            "message": "Review this code:\n\ndef calc(a, b, op):\n  if op == '+':\n    return a+b\n  if op == '/':\n    return a/b",
            "effort": "max",
        })
    d3 = chat3["data"]
    print(f"  Cost:        ${d3['cost']:.4f}")
    print(f"  Duration:    {d3['duration_ms']}ms")
    print(f"\n  {BOLD}Code Review:{RESET}")
    for line in d3["content"][:500].split("\n"):
        print(f"  {DIM}│{RESET} {line}")

    # ──────────────────────────────────────────────────────────
    section(9, "List Sessions (Paginated)", "GET /sessions?page=1&limit=10")
    sessions = api("GET", "/sessions?page=1&limit=10")
    print(f"  {'Name':<20s} {'Status':<10s} {'Cost':>8s}")
    print(f"  {'─'*20} {'─'*10} {'─'*8}")
    for s in sessions["data"]:
        status_color = GREEN if s["status"] == "active" else YELLOW
        print(f"  {s['name']:<20s} {status_color}{s['status']:<10s}{RESET} ${s['total_cost']:>7.4f}")

    # ──────────────────────────────────────────────────────────
    section(10, "Token Estimation", "POST /tokens/count")
    tokens = api("POST", "/tokens/count", json={
        "text": "def hello():\n    print('Hello, World!')\n\nhello()"
    })
    td = tokens["data"]
    print(f"  Characters:       {td['characters']}")
    print(f"  Words:            {td['words']}")
    print(f"  Estimated Tokens: {td['estimated_tokens']}")

    # ──────────────────────────────────────────────────────────
    section(11, "Usage Statistics", "GET /usage")
    usage = api("GET", "/usage")
    ud = usage["data"]
    print(f"  Sessions:    {ud['sessions']}")
    print(f"  Messages:    {ud['messages']}")
    print(f"  Total Cost:  ${ud['cost']:.4f}")
    print(f"  Total Turns: {ud['turns']}")
    jobs = ud.get("jobs", {})
    print(f"  Jobs:        {jobs.get('total', 0)} total, {jobs.get('completed', 0) or 0} completed")

    # ──────────────────────────────────────────────────────────
    section(12, "Audit Trail", "GET /audit?limit=5")
    audit = api("GET", "/audit?limit=5")
    print(f"  {DIM}Last {len(audit['data'])} actions:{RESET}")
    for entry in audit["data"]:
        sname = entry.get("session_name", "?")
        role = entry["role"]
        content = (entry["content"] or "")[:55]
        print(f"  [{sname:<15s}] {role:>9s}: {content}...")

    # ──────────────────────────────────────────────────────────
    section(13, "Cleanup", "DELETE /sessions/{name}")
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
