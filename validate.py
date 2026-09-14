#!/usr/bin/env python3
"""
Environment validation script for the BARQ DevOps assessment stack.
"""

import argparse
import json
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
        body = resp.read().decode("utf-8")
        return resp.status, body


def http_post(url, payload, timeout):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
        return resp.status, body


def check_reachable(base_url, timeout):
    try:
        status, body = http_get(base_url + "/", timeout)
        return record("NGINX reachable (GET /)", status == 200, f"status={status}")
    except Exception as e:
        return record("NGINX reachable (GET /)", False, f"{type(e).__name__}: {e}")


def check_health(base_url, timeout, retries=5, delay=2):
    """Bounded retry loop: up to retries*delay seconds total, never infinite."""
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            status, body = http_get(base_url + "/health", timeout)
            if status == 200:
                return record("Health endpoint (GET /health)", True, f"status={status} (attempt {attempt}/{retries})")
            last_error = f"status={status}"
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
        time.sleep(delay)
    return record("Health endpoint (GET /health)", False, f"{last_error} after {retries} attempts")


def check_ready(base_url, timeout, retries=5, delay=2):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            status, body = http_get(base_url + "/ready", timeout)
            data = json.loads(body)
            deps = data.get("dependencies", {})
            ok = (
                status == 200
                and data.get("status") == "ready"
                and deps.get("postgres") == "ready"
                and deps.get("redis") == "ready"
            )
            if ok:
                return record("Dependencies ready (GET /ready)", True, f"deps={deps}")
            last_error = f"status={status} deps={deps}"
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
        time.sleep(delay)
    return record("Dependencies ready (GET /ready)", False, f"{last_error} after {retries} attempts")


def check_load_balancing(base_url, timeout, samples=10):
    seen_instances = set()
    errors = 0
    for _ in range(samples):
        try:
            status, body = http_get(base_url + "/instance", timeout)
            data = json.loads(body)
            seen_instances.add(data.get("instance_id"))
        except Exception:
            errors += 1
    ok = len(seen_instances) >= 2
    return record(
        f"Load balancing across two instances (GET /instance x{samples})",
        ok,
        f"instances_seen={sorted(seen_instances)} errors={errors}",
    )


def check_records_roundtrip(base_url, timeout):
    try:
        status, body = http_get(base_url + "/records", timeout)
        if status != 200:
            return record("Records readable (GET /records)", False, f"status={status}")
        before = json.loads(body).get("records", [])
    except Exception as e:
        return record("Records readable (GET /records)", False, f"{type(e).__name__}: {e}")

    marker = f"validate-check-{int(time.time())}"
    try:
        status, body = http_post(base_url + "/records", {"title": marker}, timeout)
        if status not in (200, 201):
            return record("Records writable (POST /records)", False, f"status={status}")
    except Exception as e:
        return record("Records writable (POST /records)", False, f"{type(e).__name__}: {e}")

    try:
        status, body = http_get(base_url + "/records", timeout)
        after = json.loads(body).get("records", [])
        found = any(r.get("title") == marker for r in after)
        return record(
            "New record visible after write (GET /records)",
            found,
            f"before={len(before)} after={len(after)}",
        )
    except Exception as e:
        return record("New record visible after write (GET /records)", False, f"{type(e).__name__}: {e}")


def check_counter(base_url, timeout):
    try:
        status1, body1 = http_get(base_url + "/counter", timeout)
        v1 = json.loads(body1).get("counter")
        status2, body2 = http_get(base_url + "/counter", timeout)
        v2 = json.loads(body2).get("counter")
        ok = status1 == 200 and status2 == 200 and isinstance(v1, int) and v2 > v1
        return record("Counter increments (GET /counter x2)", ok, f"v1={v1} v2={v2}")
    except Exception as e:
        return record("Counter increments (GET /counter x2)", False, f"{type(e).__name__}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Validate the running BARQ assessment stack.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    timeout = args.timeout

    print(f"Validating {base_url} (per-request timeout={timeout}s)\n")

    check_reachable(base_url, timeout)
    check_health(base_url, timeout)
    check_ready(base_url, timeout)
    check_load_balancing(base_url, timeout)
    check_records_roundtrip(base_url, timeout)
    check_counter(base_url, timeout)

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
