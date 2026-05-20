#!/usr/bin/env python3
"""
Claude Code API — Showcase Demo
================================
Demonstrates all API features in sequence.
Run with: python examples/showcase.py

Requires: pip install httpx rich
Server must be running: make dev
"""

import httpx
import time
import json
import sys

BASE = "http://localhost:8000/api/v1"
KEY = "dev-key-123"  # match your .env API_KEYS
HEADERS = {"X-API-Key": KEY, "Content-Type": "application/json"}


def api(method, path, **kwargs):
    """Make API call and return JSON."""
    r = httpx.request(method, f"{BASE}{path}", headers=HEADERS, timeout=120, **kwargs)
    if r.status_code == 204:
        return None
    return r.json()


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def show(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))


def main():
    # --------------------------------------------------
    # 1. Health Check
    # --------------------------------------------------
    section("1. Health Check")
    show(api("GET", "/health"))

    # --------------------------------------------------
    # 2. Templates
    # --------------------------------------------------
    section("2. Available Templates")
    templates = api("GET", "/templates")
    for name in templates["data"]:
        t = templates["data"][name]
        print(f"  [{name}] effort={t.get('effort', '-')}")
        print(f"    {t['system_prompt'][:80]}...")

    # --------------------------------------------------
    # 3. Create Session (plain)
    # --------------------------------------------------
    section("3. Create Session")
    session = api("POST", "/sessions", json={"name": "demo-showcase"})
    show(session["data"])
    print(f"\n  Status: {session['data']['status']}")

    # --------------------------------------------------
    # 4. Chat — Claude creates a file
    # --------------------------------------------------
    section("4. Chat — Ask Claude to create code")
    chat = api("POST", "/sessions/demo-showcase/chat", json={
        "message": "Create a Python function in calculator.py that handles add, subtract, multiply, divide with proper error handling for division by zero."
    })
    print(f"  Cost: ${chat['data']['cost']:.4f}")
    print(f"  Duration: {chat['data']['duration_ms']}ms")
    print(f"  Turns: {chat['data']['num_turns']}")
    print(f"  Tools: {[t['name'] for t in (chat['data']['tools_used'] or [])]}")
    print(f"\n  Response:\n  {chat['data']['content'][:300]}...")

    # --------------------------------------------------
    # 5. Chat — Follow-up (session context maintained)
    # --------------------------------------------------
    section("5. Follow-up Chat (context maintained)")
    chat2 = api("POST", "/sessions/demo-showcase/chat", json={
        "message": "Now add type hints and a __main__ block with example usage"
    })
    print(f"  Cost: ${chat2['data']['cost']:.4f}")
    print(f"  Tools: {[t['name'] for t in (chat2['data']['tools_used'] or [])]}")
    print(f"\n  Response:\n  {chat2['data']['content'][:300]}...")

    # --------------------------------------------------
    # 6. Chat History
    # --------------------------------------------------
    section("6. Chat History")
    history = api("GET", "/sessions/demo-showcase/history?limit=5")
    for msg in history["data"]:
        role = msg["role"]
        content = (msg["content"] or "")[:80]
        print(f"  [{role}] {content}...")

    # --------------------------------------------------
    # 7. Session with Template
    # --------------------------------------------------
    section("7. Session with Template")
    review_session = api("POST", "/sessions", json={
        "name": "demo-reviewer",
        "template": "code-reviewer"
    })
    print(f"  Template applied: code-reviewer")
    show(review_session["data"])

    # --------------------------------------------------
    # 8. Per-request overrides
    # --------------------------------------------------
    section("8. Chat with Overrides")
    chat3 = api("POST", "/sessions/demo-reviewer/chat", json={
        "message": "Review this code:\n\ndef calc(a, b, op):\n  if op == '+':\n    return a+b\n  if op == '/':\n    return a/b",
        "effort": "max",
    })
    print(f"  Effort: max (override)")
    print(f"  Cost: ${chat3['data']['cost']:.4f}")
    print(f"\n  Review:\n  {chat3['data']['content'][:400]}...")

    # --------------------------------------------------
    # 9. List Sessions
    # --------------------------------------------------
    section("9. List Sessions")
    sessions = api("GET", "/sessions?page=1&limit=10")
    for s in sessions["data"]:
        print(f"  [{s['name']}] status={s['status']} cost=${s['total_cost']:.4f}")

    # --------------------------------------------------
    # 10. Token Count
    # --------------------------------------------------
    section("10. Token Estimation")
    tokens = api("POST", "/tokens/count", json={
        "text": "def hello():\n    print('Hello, World!')\n\nhello()"
    })
    show(tokens["data"])

    # --------------------------------------------------
    # 11. Usage Stats
    # --------------------------------------------------
    section("11. Usage Stats")
    usage = api("GET", "/usage")
    show(usage["data"])

    # --------------------------------------------------
    # 12. Audit Trail
    # --------------------------------------------------
    section("12. Audit Trail (last 5)")
    audit = api("GET", "/audit?limit=5")
    for entry in audit["data"]:
        print(f"  [{entry.get('session_name', '?')}] {entry['role']}: {(entry['content'] or '')[:60]}...")

    # --------------------------------------------------
    # Cleanup
    # --------------------------------------------------
    section("Cleanup")
    api("DELETE", "/sessions/demo-showcase")
    api("DELETE", "/sessions/demo-reviewer")
    print("  Sessions deleted.")

    print(f"\n{'='*60}")
    print("  Showcase complete!")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
