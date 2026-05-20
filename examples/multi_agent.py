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

Usage:
  API_KEY=your-key python examples/multi_agent.py

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

# Colors
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

DEV_ICON = f"{CYAN}🔧 Developer{RESET}"
REV_ICON = f"{MAGENTA}🔍 Reviewer{RESET}"


def log_body(body, indent=4):
    """Show request body."""
    formatted = json.dumps(body, indent=2, ensure_ascii=False)
    for line in formatted.split("\n"):
        # Truncate long lines (e.g. huge prompts)
        display = line if len(line) <= 100 else line[:100] + "..."
        print(f"{' '*indent}  {DIM}{display}{RESET}")


def api(method, path, slow=False, **kwargs):
    """Make API call with full logging."""
    body = kwargs.get("json")

    print(f"    {DIM}→ {method} {BASE}{path}{RESET}")
    if body:
        log_body(body)

    if slow:
        print(f"    {YELLOW}⏳ Waiting for response...{RESET}", end="", flush=True)

    start = time.time()
    r = httpx.request(method, f"{BASE}{path}", headers=HEADERS, timeout=300, **kwargs)
    elapsed = int((time.time() - start) * 1000)

    if slow:
        print(f"\r    {GREEN}✓ Response received ({elapsed}ms){RESET}                    ")
    else:
        print(f"    {DIM}← {r.status_code} ({elapsed}ms){RESET}")

    if r.status_code == 204:
        return None
    data = r.json()
    if r.status_code >= 400:
        print(f"    {RED}✗ ERROR {r.status_code}: {data.get('detail', data)}{RESET}")
        sys.exit(1)
    return data


def section(text, char="─"):
    print(f"\n  {BOLD}{char*56}{RESET}")
    print(f"  {BOLD}{text}{RESET}")
    print(f"  {BOLD}{char*56}{RESET}\n")


def show_content(label, content, max_lines=8):
    lines = content.split("\n")
    print(f"    {BOLD}{label}:{RESET}")
    for line in lines[:max_lines]:
        print(f"    {DIM}│{RESET} {line}")
    if len(lines) > max_lines:
        print(f"    {DIM}│ ... ({len(lines) - max_lines} more lines){RESET}")


def main():
    total_cost = 0.0
    start = time.time()

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"  {BOLD}Multi-Agent Demo: Developer + Reviewer{RESET}")
    print(f"  {DIM}Pattern: Evaluator-Optimizer | Max rounds: {MAX_ROUNDS}{RESET}")
    print(f"  {DIM}Server: {BASE}{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")

    # ── Setup ──
    section("SETUP — Creating agents")

    print(f"  {DEV_ICON}")
    print(f"    {DIM}Custom system prompt (senior Python developer){RESET}")
    api("POST", "/sessions", json={
        "name": "agent-developer",
        "system_prompt": (
            "You are a senior Python developer. Write clean, production-ready code. "
            "When you receive review feedback, improve the code addressing every point. "
            "Always write the complete updated file, never partial snippets."
        ),
        "effort": "high",
    })

    print(f"\n  {REV_ICON}")
    print(f"    {DIM}Using template: code-reviewer{RESET}")
    api("POST", "/sessions", json={
        "name": "agent-reviewer",
        "template": "code-reviewer",
    })

    print(f"\n    {GREEN}✓ Both agents ready{RESET}")

    # ── Task ──
    section("TASK")
    for line in TASK.strip().split("\n"):
        print(f"    {line}")

    # ── Rounds ──
    reviewer_feedback = None

    for round_num in range(1, MAX_ROUNDS + 1):
        section(f"ROUND {round_num}/{MAX_ROUNDS}", char="═")

        # ── Developer turn ──
        if round_num == 1:
            dev_prompt = f"Write this code:\n\n{TASK}"
            print(f"  {DEV_ICON} — Writing initial implementation")
        else:
            dev_prompt = (
                f"Here's the code review feedback from round {round_num - 1}. "
                f"Improve the code addressing ALL points:\n\n"
                f"--- REVIEWER FEEDBACK ---\n{reviewer_feedback}\n--- END FEEDBACK ---\n\n"
                f"Write the complete improved auth.py file."
            )
            print(f"  {DEV_ICON} — Improving code based on round {round_num - 1} feedback")

        dev_result = api("POST", "/sessions/agent-developer/chat",
            slow=True,
            json={"message": dev_prompt})

        developer_response = dev_result["data"]["content"]
        dev_cost = dev_result["data"]["cost"]
        dev_duration = dev_result["data"]["duration_ms"]
        total_cost += dev_cost
        dev_tools = [t["name"] for t in (dev_result["data"]["tools_used"] or [])]

        print(f"    Cost: ${dev_cost:.4f} | Duration: {dev_duration}ms | Tools: {dev_tools}")
        show_content("Developer output", developer_response, max_lines=6)

        # ── Reviewer turn ──
        print(f"\n  {REV_ICON} — Analyzing code from round {round_num}")

        review_prompt = (
            f"Review this code from round {round_num}. Be specific and actionable.\n\n"
            f"At the end, give a verdict: APPROVED or NEEDS_CHANGES.\n"
            f"Only say APPROVED if the code is production-ready with no issues.\n\n"
            f"--- DEVELOPER OUTPUT ---\n{developer_response}\n--- END OUTPUT ---"
        )

        rev_result = api("POST", "/sessions/agent-reviewer/chat",
            slow=True,
            json={"message": review_prompt})

        reviewer_feedback = rev_result["data"]["content"]
        rev_cost = rev_result["data"]["cost"]
        rev_duration = rev_result["data"]["duration_ms"]
        total_cost += rev_cost

        print(f"    Cost: ${rev_cost:.4f} | Duration: {rev_duration}ms")
        show_content("Review feedback", reviewer_feedback, max_lines=8)

        # ── Check verdict ──
        if "APPROVED" in reviewer_feedback.upper() and "NEEDS_CHANGES" not in reviewer_feedback.upper():
            print(f"\n    {GREEN}{BOLD}✓ VERDICT: APPROVED{RESET}")
            section(f"CODE APPROVED — Round {round_num}/{MAX_ROUNDS}", char="═")
            break
        else:
            print(f"\n    {YELLOW}→ VERDICT: NEEDS_CHANGES — continuing to round {round_num + 1}{RESET}")
    else:
        section(f"MAX ROUNDS REACHED ({MAX_ROUNDS})", char="═")

    # ── Summary ──
    elapsed = time.time() - start

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"  {BOLD}Summary{RESET}")
    print(f"{'='*60}")
    print(f"  Rounds:       {round_num}")
    print(f"  Total Cost:   ${total_cost:.4f}")
    print(f"  Total Time:   {elapsed:.1f}s")
    print()

    # ── Conversation histories ──
    section("Agent Histories")

    print(f"  {DEV_ICON} conversation:")
    dev_history = api("GET", "/sessions/agent-developer/history?limit=10")
    for msg in dev_history["data"]:
        icon = "👤" if msg["role"] == "user" else "🤖"
        content = (msg["content"] or "")[:65]
        print(f"    {icon} [{msg['role']:9s}] {content}...")

    print(f"\n  {REV_ICON} conversation:")
    rev_history = api("GET", "/sessions/agent-reviewer/history?limit=10")
    for msg in rev_history["data"]:
        icon = "👤" if msg["role"] == "user" else "🤖"
        content = (msg["content"] or "")[:65]
        print(f"    {icon} [{msg['role']:9s}] {content}...")

    # ── Cleanup ──
    section("Cleanup")
    api("DELETE", "/sessions/agent-developer")
    api("DELETE", "/sessions/agent-reviewer")
    print(f"    {GREEN}✓ Both agents deleted{RESET}")

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"  {GREEN}{BOLD}Multi-agent demo complete!{RESET}")
    print(f"  {DIM}Total: {round_num} rounds, ${total_cost:.4f}, {elapsed:.1f}s{RESET}")
    print(f"{BOLD}{'='*60}{RESET}\n")


if __name__ == "__main__":
    main()
