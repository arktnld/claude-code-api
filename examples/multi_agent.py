#!/usr/bin/env python3
"""
Claude Code API — Multi-Agent Demo
====================================
Two agents collaborate in an Evaluator-Optimizer loop:

  Agent A (Developer)  →  writes/improves code
  Agent B (Reviewer)   →  reviews and gives feedback
  Loop until approved or max rounds reached.

Pattern: Evaluator-Optimizer (from Anthropic's agentic patterns)
https://www.anthropic.com/engineering/building-effective-agents

Run with: python examples/multi_agent.py
Requires: pip install httpx rich
Server must be running: make dev
"""

import httpx
import json
import sys
import time

BASE = "http://localhost:8000/api/v1"
KEY = "dev-key-123"
HEADERS = {"X-API-Key": KEY, "Content-Type": "application/json"}

MAX_ROUNDS = 3
TASK = """
Create a Python module `auth.py` with:
1. A function to hash passwords using bcrypt
2. A function to verify passwords
3. A function to generate JWT tokens with expiry
4. A function to decode and validate JWT tokens
5. Proper error handling and type hints
Use only standard library + PyJWT + bcrypt.
"""


def api(method, path, **kwargs):
    r = httpx.request(method, f"{BASE}{path}", headers=HEADERS, timeout=180, **kwargs)
    if r.status_code == 204:
        return None
    data = r.json()
    if r.status_code >= 400:
        print(f"  ERROR: {data.get('detail', data)}")
        sys.exit(1)
    return data


def banner(text, char="="):
    width = 60
    print(f"\n{char*width}")
    print(f"  {text}")
    print(f"{char*width}\n")


def main():
    total_cost = 0.0
    start = time.time()

    banner("MULTI-AGENT DEMO: Developer + Reviewer")

    # ── Setup: create two agents ──
    print("[setup] Creating Developer agent (template: debug)...")
    api("POST", "/sessions", json={
        "name": "agent-developer",
        "system_prompt": (
            "You are a senior Python developer. Write clean, production-ready code. "
            "When you receive review feedback, improve the code addressing every point. "
            "Always write the complete updated file, never partial snippets."
        ),
        "effort": "high",
    })

    print("[setup] Creating Reviewer agent (template: code-reviewer)...")
    api("POST", "/sessions", json={
        "name": "agent-reviewer",
        "template": "code-reviewer",
    })

    print("[setup] Both agents ready.\n")

    # ── Round 1: Developer writes initial code ──
    developer_response = None
    reviewer_feedback = None

    for round_num in range(1, MAX_ROUNDS + 1):
        banner(f"ROUND {round_num}/{MAX_ROUNDS}", char="-")

        # ── Developer turn ──
        if round_num == 1:
            dev_prompt = f"Write this code:\n\n{TASK}"
        else:
            dev_prompt = (
                f"Here's the code review feedback from round {round_num - 1}. "
                f"Improve the code addressing ALL points:\n\n"
                f"--- REVIEWER FEEDBACK ---\n{reviewer_feedback}\n--- END FEEDBACK ---\n\n"
                f"Write the complete improved auth.py file."
            )

        print(f"[round {round_num}] Developer working...")
        dev_result = api("POST", "/sessions/agent-developer/chat", json={
            "message": dev_prompt,
        })

        developer_response = dev_result["data"]["content"]
        dev_cost = dev_result["data"]["cost"]
        total_cost += dev_cost
        dev_tools = [t["name"] for t in (dev_result["data"]["tools_used"] or [])]

        print(f"  Cost: ${dev_cost:.4f} | Tools: {dev_tools}")
        print(f"  Developer: {developer_response[:150]}...\n")

        # ── Reviewer turn ──
        review_prompt = (
            f"Review this code from round {round_num}. Be specific and actionable.\n\n"
            f"At the end, give a verdict: APPROVED or NEEDS_CHANGES.\n"
            f"Only say APPROVED if the code is production-ready with no issues.\n\n"
            f"--- DEVELOPER OUTPUT ---\n{developer_response}\n--- END OUTPUT ---"
        )

        print(f"[round {round_num}] Reviewer analyzing...")
        rev_result = api("POST", "/sessions/agent-reviewer/chat", json={
            "message": review_prompt,
        })

        reviewer_feedback = rev_result["data"]["content"]
        rev_cost = rev_result["data"]["cost"]
        total_cost += rev_cost

        print(f"  Cost: ${rev_cost:.4f}")
        print(f"  Reviewer: {reviewer_feedback[:200]}...\n")

        # ── Check verdict ──
        if "APPROVED" in reviewer_feedback.upper() and "NEEDS_CHANGES" not in reviewer_feedback.upper():
            banner(f"CODE APPROVED after {round_num} round(s)!")
            break
    else:
        banner(f"Max rounds ({MAX_ROUNDS}) reached")

    # ── Summary ──
    elapsed = time.time() - start

    banner("SUMMARY")
    print(f"  Rounds:      {round_num}")
    print(f"  Total cost:  ${total_cost:.4f}")
    print(f"  Total time:  {elapsed:.1f}s")
    print()

    # ── Show histories ──
    print("[history] Developer conversation:")
    dev_history = api("GET", "/sessions/agent-developer/history?limit=10")
    for msg in dev_history["data"]:
        role = msg["role"]
        content = (msg["content"] or "")[:80]
        print(f"  [{role}] {content}...")

    print("\n[history] Reviewer conversation:")
    rev_history = api("GET", "/sessions/agent-reviewer/history?limit=10")
    for msg in rev_history["data"]:
        role = msg["role"]
        content = (msg["content"] or "")[:80]
        print(f"  [{role}] {content}...")

    # ── Cleanup ──
    banner("CLEANUP")
    api("DELETE", "/sessions/agent-developer")
    api("DELETE", "/sessions/agent-reviewer")
    print("  Agents deleted.")
    print()


if __name__ == "__main__":
    main()
