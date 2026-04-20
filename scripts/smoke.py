"""End-to-end smoke client for the mock Vertex stack.

Submits a handful of day-queue tasks to the running API, polls until each
reaches a terminal state, and prints a per-task summary. No external deps.

Usage:
    python scripts/smoke.py                 # hits http://localhost:8000
    BASE_URL=... python scripts/smoke.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
NUM_TASKS = int(os.environ.get("NUM_TASKS", "5"))
POLL_TIMEOUT_S = float(os.environ.get("POLL_TIMEOUT_S", "30"))
TERMINAL = {"complete", "failed", "cancelled"}


def _request(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        method=method,
        headers={"content-type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def wait_for_ready(deadline: float) -> dict:
    while time.monotonic() < deadline:
        try:
            status, body = _request("GET", "/health")
            if status == 200:
                return body
        except urllib.error.URLError:
            pass
        time.sleep(1)
    raise SystemExit(f"API not ready at {BASE_URL} within deadline")


def submit_task(i: int) -> dict:
    payload = {
        "queue": "day",
        "model": "gemini-2.5-flash",
        "messages": [{"role": "user", "content": f"smoke test {i}"}],
        "estimated_tokens": 500,
        "parameters": {"temperature": 0.1 + 0.1 * i, "max_tokens": 128},
    }
    status, body = _request("POST", "/tasks", payload)
    if status != 201:
        raise SystemExit(f"submit failed: {status} {body}")
    return body


def poll_until_terminal(task_id: str, deadline: float) -> dict:
    while time.monotonic() < deadline:
        status, body = _request("GET", f"/tasks/{task_id}")
        if status == 200 and body.get("status") in TERMINAL:
            return body
        time.sleep(0.5)
    return {"status": "timeout", "id": task_id}


def main() -> int:
    print(f"==> waiting for {BASE_URL}/health")
    health = wait_for_ready(time.monotonic() + 30)
    for name, gate in health["endpoints"].items():
        print(f"    {name}: total={gate['total_tps']} available={gate['available']}")

    print(f"==> submitting {NUM_TASKS} day tasks")
    submitted = [submit_task(i) for i in range(NUM_TASKS)]
    for t in submitted:
        print(f"    {t['id']}  status={t['status']}")

    deadline = time.monotonic() + POLL_TIMEOUT_S
    print(f"==> polling (timeout {POLL_TIMEOUT_S:.0f}s)")
    results: list[dict[str, Any]] = [poll_until_terminal(t["id"], deadline) for t in submitted]

    print("==> results")
    ok = 0
    for r in results:
        state = r.get("status")
        tokens = r.get("actual_tokens")
        err = r.get("error")
        print(f"    {r.get('id')}  {state}  tokens={tokens}  err={err or '-'}")
        if state == "complete":
            ok += 1

    print(f"==> summary: {ok}/{len(results)} complete")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
