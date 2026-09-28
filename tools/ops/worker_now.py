"""Run the production worker now instead of waiting for its cron.

    python -m tools.ops.worker_now status
    python -m tools.ops.worker_now run --force research        # due now; the next cron tick runs it
    python -m tools.ops.worker_now run --force research --now  # ...and start a run immediately
    python -m tools.ops.worker_now run --now --wait            # start now, wait for it to exit

--force back-dates the named worker_cadence rows through the API's
POST /admin/worker/force (ADMIN_TOKEN; taken from the environment or read
from the API service's Railway variables, never printed).

By default nothing is started: the next scheduled tick (every 15 min) runs
whatever is due, and Railway never interrupts a scheduled run (an
overlapping tick is skipped). --now starts one immediately via Railway's
"run now" (deploymentInstanceExecutionCreate) -- but a manually started run
is REPLACED when the next scheduled tick starts (seen 2026-09-28: forced
runs ended exactly at :00 and :30), so --now suits short concerns only. A
run is refused while another execution is still active. Needs an
authenticated `railway` CLI.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from typing import Any

API_BASE = "https://projectprometheus-production.up.railway.app"
API_SERVICE = "Project_Prometheus"
WORKER_SERVICE_ID = "360d127b-fde1-4705-b90e-3698e3b597dd"
ENVIRONMENT_ID = "cb8fcc4b-10da-4d19-8bbf-0eb1fc9d63c8"
WORKER_SERVICE_INSTANCE_ID = "b2c5f013-de8f-4edd-b3e3-36f84e3fc0ec"
ACTIVE_STATUSES = frozenset({"CREATED", "INITIALIZING", "RUNNING", "RESTARTING"})

_EXECUTIONS = f"""
query {{
  deploymentInstanceExecutions(
    input: {{serviceId: "{WORKER_SERVICE_ID}", environmentId: "{ENVIRONMENT_ID}"}}
    first: 5
  ) {{ edges {{ node {{ status createdAt completedAt }} }} }}
}}
"""
_RUN_NOW = f"""
mutation {{
  deploymentInstanceExecutionCreate(input: {{serviceInstanceId: "{WORKER_SERVICE_INSTANCE_ID}"}})
}}
"""


def _railway() -> str:
    """Full path to the CLI -- on Windows, subprocess does not resolve
    `railway` to railway.exe/.cmd by itself."""
    path = shutil.which("railway")
    if path is None:
        raise RuntimeError("railway CLI not found on PATH")
    return path


def railway_graphql(document: str) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile("w", suffix=".graphql", delete=False) as f:
        f.write(document)
        path = f.name
    try:
        out = subprocess.run(
            [_railway(), "api", "-f", path], check=True, capture_output=True, text=True
        ).stdout
    finally:
        os.unlink(path)
    body: dict[str, Any] = json.loads(out)
    if body.get("errors"):
        raise RuntimeError(f"Railway API error: {body['errors']}")
    return body


def recent_executions() -> list[dict[str, Any]]:
    edges = railway_graphql(_EXECUTIONS)["data"]["deploymentInstanceExecutions"]["edges"]
    return [edge["node"] for edge in edges]


def active_execution(executions: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((e for e in executions if e["status"] in ACTIVE_STATUSES), None)


def admin_token() -> str:
    token = os.environ.get("ADMIN_TOKEN")
    if token:
        return token
    out = subprocess.run(
        [_railway(), "variables", "--service", API_SERVICE, "--kv"],
        check=True, capture_output=True, text=True,
    ).stdout
    for line in out.splitlines():
        if line.startswith("ADMIN_TOKEN="):
            return line.split("=", 1)[1]
    raise RuntimeError(f"ADMIN_TOKEN is not set on the {API_SERVICE} service")


def force_due(concerns: list[str]) -> list[str]:
    request = urllib.request.Request(
        f"{API_BASE}/admin/worker/force",
        data=json.dumps({"concerns": concerns}).encode(),
        headers={"Content-Type": "application/json", "X-Admin-Token": admin_token()},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        due: list[str] = json.load(response)["due_now"]
    return due


def pipeline_concerns() -> list[dict[str, Any]]:
    with urllib.request.urlopen(f"{API_BASE}/pipeline/", timeout=60) as response:
        concerns: list[dict[str, Any]] = json.load(response)["concerns"]
    return concerns


def print_status() -> None:
    for e in recent_executions():
        print(f"  {e['createdAt']}  {e['status']:<12} completed={e['completedAt']}")
    for c in pipeline_concerns():
        print(f"  {c['concern']:<14} last={c['last_run_at']} due={c['is_due']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="worker_now")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    run = sub.add_parser("run")
    run.add_argument("--force", nargs="*", default=[], metavar="CONCERN")
    run.add_argument("--now", action="store_true")
    run.add_argument("--wait", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "status":
        print_status()
        return 0

    active = active_execution(recent_executions())
    if active is not None:
        print(f"refusing: an execution is still {active['status']} (since {active['createdAt']})")
        return 1
    if args.force:
        print(f"due now: {force_due(args.force)}")
    if not args.now:
        now = time.gmtime()
        minutes = 15 - now.tm_min % 15
        print(f"nothing started: the next scheduled tick (in ~{minutes} min) runs what is due")
        return 0
    print("warning: a manual run is replaced when the next scheduled tick starts")
    railway_graphql(_RUN_NOW)
    print("worker run started")
    if args.wait:
        while True:
            time.sleep(20)
            latest = recent_executions()[0]
            if latest["status"] not in ACTIVE_STATUSES:
                print(f"worker run {latest['status']} at {latest['completedAt']}")
                break
        print_status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
