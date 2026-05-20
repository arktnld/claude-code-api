#!/usr/bin/env python3
"""
Claude Code API — Parallel Multi-Agent Demo (Jobs)
=====================================================
Three agents work in PARALLEL via async jobs:

  Agent 1 (Refactorer)  →  improves code quality
  Agent 2 (Tester)      →  writes comprehensive tests
  Agent 3 (Security)    →  security audit

All three start simultaneously. Results collected when done.

Pattern: Parallelization + Orchestrator (from Anthropic's agentic patterns)

Usage:
  API_KEY=your-key python examples/multi_agent_parallel.py

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

CODE_TO_ANALYZE = '''
def parse_csv(filepath, delimiter=",", skip_header=False):
    results = []
    with open(filepath) as f:
        for i, line in enumerate(f):
            if skip_header and i == 0:
                continue
            row = line.strip().split(delimiter)
            results.append(row)
    return results

def merge_dicts(*dicts):
    result = {}
    for d in dicts:
        for key, value in d.items():
            if key in result and isinstance(result[key], list):
                result[key].extend(value if isinstance(value, list) else [value])
            else:
                result[key] = value
    return result
'''

# Colors
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

AGENTS = {
    "agent-refactorer": {
        "template": "refactor",
        "icon": f"{CYAN}🔧 Refactorer{RESET}",
        "color": CYAN,
    },
    "agent-tester": {
        "template": "test-writer",
        "icon": f"{GREEN}🧪 Tester{RESET}",
        "color": GREEN,
    },
    "agent-security": {
        "template": "security",
        "icon": f"{MAGENTA}🔒 Security{RESET}",
        "color": MAGENTA,
    },
}


def log_request(method, path):
    print(f"    {DIM}→ {method} {BASE}{path}{RESET}")


def api(method, path, **kwargs):
    """Make API call with logging."""
    log_request(method, path)
    r = httpx.request(method, f"{BASE}{path}", headers=HEADERS, timeout=300, **kwargs)
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


def wait_for_job(session_name, job_id, agent_info):
    """Poll job until done."""
    icon = agent_info["icon"]
    color = agent_info["color"]
    poll_count = 0
    while True:
        r = httpx.request("GET", f"{BASE}/sessions/{session_name}/jobs/{job_id}",
                          headers=HEADERS, timeout=30)
        job = r.json()
        status = job["data"]["status"]
        if status in ("done", "failed", "cancelled"):
            return job["data"]
        poll_count += 1
        dots = "." * (poll_count % 4)
        print(f"    {color}⏳ {icon} [{status}]{dots}{RESET}              ", end="\r", flush=True)
        time.sleep(3)


def main():
    start = time.time()

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"  {BOLD}Parallel Multi-Agent Demo (Async Jobs){RESET}")
    print(f"  {DIM}Pattern: Parallelization | 3 agents simultaneously{RESET}")
    print(f"  {DIM}Server: {BASE}{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")

    # ── Code to analyze ──
    section("CODE TO ANALYZE")
    for line in CODE_TO_ANALYZE.strip().split("\n"):
        print(f"    {DIM}│{RESET} {line}")

    # ── Setup ──
    section("SETUP — Creating 3 specialized agents")

    for name, info in AGENTS.items():
        print(f"  {info['icon']}")
        print(f"    {DIM}Template: {info['template']}{RESET}")
        api("POST", "/sessions", json={"name": name, "template": info["template"]})
        print()

    print(f"    {GREEN}✓ All 3 agents ready{RESET}")

    # ── Fire all jobs simultaneously ──
    section("LAUNCHING PARALLEL JOBS", char="═")
    print(f"    {DIM}All 3 jobs fire at once — each agent works independently{RESET}\n")

    jobs = {}

    # Job 1: Refactor
    print(f"  {AGENTS['agent-refactorer']['icon']}")
    j1 = api("POST", "/sessions/agent-refactorer/jobs", json={
        "message": f"Refactor this code for production quality. Add type hints, docstrings, error handling, and improve the logic:\n\n```python\n{CODE_TO_ANALYZE}\n```\n\nWrite the improved code to improved_utils.py",
    })
    print(f"    Job ID: {j1['data']['id']} | Status: {YELLOW}{j1['data']['status']}{RESET}\n")
    jobs["Refactorer"] = ("agent-refactorer", j1["data"]["id"], AGENTS["agent-refactorer"])

    # Job 2: Tests
    print(f"  {AGENTS['agent-tester']['icon']}")
    j2 = api("POST", "/sessions/agent-tester/jobs", json={
        "message": f"Write comprehensive pytest tests for this code. Cover edge cases, error paths, happy paths:\n\n```python\n{CODE_TO_ANALYZE}\n```\n\nWrite tests to test_utils.py",
    })
    print(f"    Job ID: {j2['data']['id']} | Status: {YELLOW}{j2['data']['status']}{RESET}\n")
    jobs["Tester"] = ("agent-tester", j2["data"]["id"], AGENTS["agent-tester"])

    # Job 3: Security
    print(f"  {AGENTS['agent-security']['icon']}")
    j3 = api("POST", "/sessions/agent-security/jobs", json={
        "message": f"Security audit this code. Check for path traversal, injection, resource leaks, unsafe defaults:\n\n```python\n{CODE_TO_ANALYZE}\n```\n\nProvide a detailed security report.",
    })
    print(f"    Job ID: {j3['data']['id']} | Status: {YELLOW}{j3['data']['status']}{RESET}\n")
    jobs["Security"] = ("agent-security", j3["data"]["id"], AGENTS["agent-security"])

    print(f"    {DIM}3 jobs running in parallel...{RESET}")

    # ── Wait for all jobs ──
    section("COLLECTING RESULTS", char="═")

    results = {}
    total_cost = 0.0

    for label, (session_name, job_id, agent_info) in jobs.items():
        print(f"  {agent_info['icon']} — Waiting for result...")
        result = wait_for_job(session_name, job_id, agent_info)
        results[label] = result

        if result["status"] == "done":
            cost = result.get("cost", 0) or 0
            total_cost += cost
            duration = result.get("duration_ms", 0)

            parsed = json.loads(result["result"]) if isinstance(result["result"], str) else result["result"]
            content = parsed.get("content", "")[:400] if parsed else ""
            tools = parsed.get("tools_used", []) if parsed else []
            tool_names = [t["name"] for t in tools] if tools else []

            print(f"    {GREEN}✓ DONE{RESET} | Cost: ${cost:.4f} | Duration: {duration}ms | Tools: {tool_names}")
            print(f"    {BOLD}Output:{RESET}")
            for line in content.split("\n")[:6]:
                print(f"    {DIM}│{RESET} {line}")
            if len(content.split("\n")) > 6:
                print(f"    {DIM}│ ...{RESET}")
        else:
            print(f"    {RED}✗ {result['status'].upper()}: {result.get('error', '?')}{RESET}")

        print()

    # ── Summary ──
    elapsed = time.time() - start

    print(f"{BOLD}{'='*60}{RESET}")
    print(f"  {BOLD}Summary{RESET}")
    print(f"{'='*60}")
    print(f"  Agents:       3 (parallel execution)")
    print(f"  Total Cost:   ${total_cost:.4f}")
    print(f"  Wall Time:    {elapsed:.1f}s")
    print(f"  Speedup:      ~3x vs sequential")
    print()
    print(f"  {'Agent':<15s} {'Status':<10s} {'Cost':>8s}")
    print(f"  {'─'*15} {'─'*10} {'─'*8}")
    for label, result in results.items():
        status = result["status"]
        color = GREEN if status == "done" else RED
        cost = result.get("cost", 0) or 0
        print(f"  {label:<15s} {color}{status:<10s}{RESET} ${cost:>7.4f}")

    # ── Cleanup ──
    section("Cleanup")
    for name, info in AGENTS.items():
        api("DELETE", f"/sessions/{name}")
    print(f"    {GREEN}✓ All agents deleted{RESET}")

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"  {GREEN}{BOLD}Parallel multi-agent demo complete!{RESET}")
    print(f"  {DIM}3 agents, ${total_cost:.4f}, {elapsed:.1f}s wall time{RESET}")
    print(f"{BOLD}{'='*60}{RESET}\n")


if __name__ == "__main__":
    main()
