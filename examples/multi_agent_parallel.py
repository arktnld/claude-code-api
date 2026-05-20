#!/usr/bin/env python3
"""
Claude Code API — Parallel Multi-Agent Demo (Jobs)
=====================================================
Three agents work in PARALLEL via async jobs:

  Agent 1 (Developer)    →  writes the code
  Agent 2 (Test Writer)  →  writes tests for the code
  Agent 3 (Reviewer)     →  reviews code + tests

All three start simultaneously. Results collected when done.

Pattern: Parallelization + Orchestrator (from Anthropic's agentic patterns)

Run with: python examples/multi_agent_parallel.py
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


def api(method, path, **kwargs):
    r = httpx.request(method, f"{BASE}{path}", headers=HEADERS, timeout=180, **kwargs)
    if r.status_code == 204:
        return None
    return r.json()


def banner(text, char="="):
    width = 60
    print(f"\n{char*width}")
    print(f"  {text}")
    print(f"{char*width}\n")


def wait_for_job(session_name, job_id, label=""):
    """Poll job until done."""
    while True:
        job = api("GET", f"/sessions/{session_name}/jobs/{job_id}")
        status = job["data"]["status"]
        if status in ("done", "failed", "cancelled"):
            return job["data"]
        print(f"  [{label}] status={status}...")
        time.sleep(3)


def main():
    start = time.time()
    banner("PARALLEL MULTI-AGENT DEMO")

    # ── Setup: create 3 specialized agents ──
    agents = {
        "agent-refactorer": {
            "template": "refactor",
        },
        "agent-tester": {
            "template": "test-writer",
        },
        "agent-security": {
            "template": "security",
        },
    }

    print("[setup] Creating 3 parallel agents...")
    for name, config in agents.items():
        api("POST", "/sessions", json={"name": name, **config})
        print(f"  Created: {name} (template: {config['template']})")

    # ── Fire all 3 jobs simultaneously ──
    banner("LAUNCHING PARALLEL JOBS", char="-")

    jobs = {}

    # Job 1: Refactor
    j1 = api("POST", "/sessions/agent-refactorer/jobs", json={
        "message": f"Refactor this code for production quality. Add type hints, docstrings, error handling, and improve the logic:\n\n```python\n{CODE_TO_ANALYZE}\n```\n\nWrite the improved code to improved_utils.py",
    })
    jobs["Refactorer"] = ("agent-refactorer", j1["data"]["id"])
    print(f"  Refactorer job: {j1['data']['id']} (status: {j1['data']['status']})")

    # Job 2: Tests
    j2 = api("POST", "/sessions/agent-tester/jobs", json={
        "message": f"Write comprehensive pytest tests for this code. Cover edge cases, error paths, happy paths:\n\n```python\n{CODE_TO_ANALYZE}\n```\n\nWrite tests to test_utils.py",
    })
    jobs["Tester"] = ("agent-tester", j2["data"]["id"])
    print(f"  Tester job:     {j2['data']['id']} (status: {j2['data']['status']})")

    # Job 3: Security review
    j3 = api("POST", "/sessions/agent-security/jobs", json={
        "message": f"Security audit this code. Check for path traversal, injection, resource leaks, unsafe defaults:\n\n```python\n{CODE_TO_ANALYZE}\n```\n\nProvide a detailed security report.",
    })
    jobs["Security"] = ("agent-security", j3["data"]["id"])
    print(f"  Security job:   {j3['data']['id']} (status: {j3['data']['status']})")

    # ── Wait for all jobs ──
    banner("WAITING FOR RESULTS", char="-")

    results = {}
    total_cost = 0.0

    for label, (session_name, job_id) in jobs.items():
        result = wait_for_job(session_name, job_id, label)
        results[label] = result

        if result["status"] == "done":
            cost = result.get("cost", 0)
            total_cost += cost
            duration = result.get("duration_ms", 0)

            parsed = json.loads(result["result"]) if isinstance(result["result"], str) else result["result"]
            content = parsed.get("content", "")[:300] if parsed else ""
            tools = parsed.get("tools_used", []) if parsed else []
            tool_names = [t["name"] for t in tools] if tools else []

            print(f"\n  [{label}] DONE")
            print(f"    Cost: ${cost:.4f} | Duration: {duration}ms | Tools: {tool_names}")
            print(f"    Output: {content}...")
        else:
            print(f"\n  [{label}] {result['status'].upper()}: {result.get('error', '?')}")

    # ── Summary ──
    elapsed = time.time() - start
    banner("SUMMARY")
    print(f"  Agents:       3 (parallel)")
    print(f"  Total cost:   ${total_cost:.4f}")
    print(f"  Wall time:    {elapsed:.1f}s")
    print(f"  Speedup:      ~3x vs sequential")
    print()

    for label, result in results.items():
        status = "DONE" if result["status"] == "done" else result["status"].upper()
        cost = result.get("cost", 0)
        print(f"  [{label:12s}] {status} — ${cost:.4f}")

    # ── Cleanup ──
    banner("CLEANUP")
    for name in agents:
        api("DELETE", f"/sessions/{name}")
    print("  All agents deleted.")
    print()


if __name__ == "__main__":
    main()
