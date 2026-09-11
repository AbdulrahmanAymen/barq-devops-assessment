#!/usr/bin/env python3
"""
Failure/recovery test for the BARQ DevOps assessment stack.

Stops one backend container (default: app-01), measures live traffic
during the outage, restores the container, waits for it to become
healthy again, and verifies traffic recovers across both instances.

Guarantees cleanup: the target container is always restarted, even if
the script fails partway through.

Usage:
    python3 failure_test.py [--target app-01] [--project barq-assessment]
                             [--base-url http://127.0.0.1:8080]
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
import urllib.error

PASS = "PASS"
FAIL = "FAIL"
results = []


def record(name, ok, detail=""):
    status = PASS if ok else FAIL
    results.append((name, status, detail))
    print(f"[{status}] {name}" + (f" - {detail}" if detail else ""))
    return ok


def http_get(url, timeout):
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8")


def run_traffic(base_url, count, timeout):
    """Send `count` requests to /instance. Return (success, fail, instances_seen)."""
    success, fail = 0, 0
    instances_seen = set()
    for _ in range(count):
        try:
            status, body = http_get(base_url + "/instance", timeout)
            if status == 200:
                success += 1
                data = json.loads(body)
                instances_seen.add(data.get("instance_id"))
            else:
                fail += 1
        except Exception:
            fail += 1
    return success, fail, instances_seen


def docker_compose(project, *args, timeout=30):
    """Run a docker compose command, bounded by timeout. Raises on failure."""
    cmd = ["docker", "compose", "-p", project] + list(args)
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
    return result.stdout.strip()


def stop_container(project, name):
    try:
        docker_compose(project, "stop", name)
        return record(f"Stop container '{name}'", True)
    except Exception as e:
        return record(f"Stop container '{name}'", False, str(e))


def start_container(project, name):
    try:
        docker_compose(project, "start", name)
        return record(f"Start container '{name}'", True)
    except Exception as e:
        return record(f"Start container '{name}'", False, str(e))


def wait_for_container_healthy(project, name, retries=10, delay=2):
    """Bounded poll of docker's own healthcheck status. Max wait = retries*delay seconds."""
    last_state = None
    for attempt in range(1, retries + 1):
        try:
            state = docker_compose(
                project, "ps", name, "--format", "{{.Health}}", timeout=10
            )
            last_state = state
            if state.strip().lower() == "healthy":
                return record(
                    f"Container '{name}' healthy after restart",
                    True,
                    f"attempt {attempt}/{retries}",
                )
        except Exception as e:
            last_state = str(e)
        time.sleep(delay)
    return record(
        f"Container '{name}' healthy after restart",
        False,
        f"last_state={last_state} after {retries} attempts",
    )


def main():
    parser = argparse.ArgumentParser(description="Failure/recovery test for the BARQ stack.")
    parser.add_argument("--target", default="app-01", help="Container/service name to stop")
    parser.add_argument("--project", default="barq-assessment", help="Docker Compose project name")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--samples", type=int, default=20, help="Requests per traffic phase")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")

    print(f"Failure test: stopping '{args.target}' in project '{args.project}'\n")

    try:
        # Phase 1: baseline traffic
        print("--- Phase 1: baseline traffic (before failure) ---")
        s, f, instances = run_traffic(base_url, args.samples, args.timeout)
        record(
            "Baseline traffic healthy",
            f == 0 and len(instances) >= 2,
            f"success={s} fail={f} instances={sorted(instances)}",
        )

        # Phase 2: induce failure
        print("\n--- Phase 2: stopping target container ---")
        if not stop_container(args.project, args.target):
            raise RuntimeError("Could not stop target container; aborting test.")

        # Give the proxy/health system a moment to notice the container is down
        time.sleep(3)

        # Phase 3: traffic during failure
        print("\n--- Phase 3: traffic during failure ---")
        s, f, instances = run_traffic(base_url, args.samples, args.timeout)
        degraded_but_alive = s > 0  # service is degraded, not fully dead
        record(
            "Service degrades but does not fully die during failure",
            degraded_but_alive,
            f"success={s} fail={f} instances={sorted(instances)} "
            f"(partial failure expected: proxy_next_upstream is off, "
            f"so only requests routed to the surviving instance succeed)",
        )

    finally:
        # Phase 4: restore — this ALWAYS runs, even if something above raised
        print("\n--- Phase 4: restoring target container (cleanup) ---")
        start_container(args.project, args.target)
        wait_for_container_healthy(args.project, args.target)

    # Phase 5: traffic after recovery
    print("\n--- Phase 5: traffic after recovery ---")
    s, f, instances = run_traffic(base_url, args.samples, args.timeout)
    record(
        "Traffic fully recovered across both instances",
        f == 0 and len(instances) >= 2,
        f"success={s} fail={f} instances={sorted(instances)}",
    )

    print("\n--- Summary ---")
    for name, status, detail in results:
        print(f"[{status}] {name}")

    failed = [r for r in results if r[1] == FAIL]
    if failed:
        print(f"\n{len(failed)}/{len(results)} checks FAILED.")
        sys.exit(1)
    else:
        print(f"\nAll {len(results)} checks PASSED.")
        sys.exit(0)


if __name__ == "__main__":
    main()
