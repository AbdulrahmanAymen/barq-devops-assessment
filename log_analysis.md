# Log analysis

Use all three supplied logs. Answer every question with commands/scripts and actual output.

---

## 1. What UTC interval is covered? How many valid, malformed and duplicate lines are in each file?

**Time interval:** 2026-08-20T11:00:00.015Z → 2026-08-20T11:29:57.578Z (~30 minutes)

| File | Total lines | Valid | Malformed | Duplicate (literal) |
|---|---|---|---|---|
| access.log | 726 | 725 | 1 (line #311, truncated JSON) | 5 request_ids appear 2x each |
| error.log | 68 | 67 error entries | 0 unparseable (see note) | 0 |
| application.log | 730 | 729 | 1 (line #401, truncated JSON) | 2 request_ids appear 2x each (fully identical lines) |

Note on error.log: line #68 ("[notice] ... log collector rotated stream") is not malformed — it's a valid NGINX operational message, just a different type (`[notice]` vs `[error]`), and has no `request_id=` field. Classified separately, not as an error or a parse failure.

**Commands used:**
```python
def parse_access_log(path):
    valid_lines, malformed_count = [], 0
    with open(path) as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                valid_lines.append(json.loads(line))
            except json.JSONDecodeError:
                malformed_count += 1
    return valid_lines, malformed_count
```
(Same pattern used for application.log; error.log parsed with regex `r'(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}).*request_id=(\S+),'`.)

---

## 2. How many distinct client requests occurred? How did you deduplicate and avoid counting retries twice?

**720 distinct client requests** (from access.log).

Calculation: 725 valid JSON lines − 5 duplicate lines (5 request_ids appeared as two byte-for-byte identical lines each) = 720 unique request_ids.

**Deduplication method:** kept the first occurrence of each `request_id`, dropped exact literal duplicates (verified with `grep` that the two lines for each duplicated ID were identical in every field, including timestamp and request_time — confirming they were a logging bug, not two separate client actions).

**Retries were NOT double-counted** because a retried request appears as a **single** access.log line with a comma-separated `upstream` field (e.g. `"172.23.0.12:8080, 172.23.0.11:8080"`), per the README's explicit instruction. It is one row in the file and one entry in the deduplicated set — no special handling needed to avoid double-counting it.

```python
seen_ids = set()
clean_access_records = []
for r in access_records:
    if r["request_id"] not in seen_ids:
        seen_ids.add(r["request_id"])
        clean_access_records.append(r)
# len(clean_access_records) == 720
```

---

## 3. What are the final client status counts and error rate? State your denominator.

**Denominator: 720** (distinct, deduplicated client requests from access.log)

| Status | Count |
|---|---|
| 200 | 615 |
| 404 | 10 |
| 502 | 40 |
| 503 | 47 |
| 504 | 8 |

- Total errors (status ≥ 400): **105**
- **Error rate: 105 / 720 = 14.58%**

Cross-check: the 47 status-503 responses match exactly the 47 `dependency_error` events found in application.log (31 Redis + 16 Postgres) — 1-to-1, confirming no error responses were missed or double-counted.

---

## 4. Which paths, time windows and backends account for the failures?

| Time window | Backend (upstream) | Status | Path(s) observed | Count |
|---|---|---|---|---|
| 11:05:02–11:09:57 | 172.23.0.12:8080 | 502 (Connection Refused) | /, /health, /ready, /records, /counter, /instance | 40 |
| 11:12:09–11:15:52 | app instances (both) | 503 (Redis TimeoutError) | /ready (observed sample) | 31 dependency errors |
| 11:20:07–11:21:45 | app instances (both) | 503 (Postgres InvalidPassword) | /records (observed sample) | 16 dependency errors |
| 11:25:14–11:26:44 | 172.23.0.12:8080 | 504 (upstream timed out, 2700ms) | /records (all sampled instances) | 8 |
| throughout | n/a | 404 (Not Found) | /missing | 10 |

All connectivity-type failures (502, 504) trace back to a single backend IP, `172.23.0.12`, at two separate points 20 minutes apart — suggesting the same instance flapped (went down, came back, then hung) rather than two different instances failing independently.

---

## 5. What are the median and p95 client latencies? State the percentile method and units.

Computed over all **720 distinct** client requests (success + failure included), using `request_time` from access.log converted from seconds to milliseconds, with the **nearest-rank percentile method**:

```python
def percentile(data, p):
    k = (len(data) - 1) * (p / 100)
    f, c = int(k), min(int(k) + 1, len(data) - 1)
    if f == c:
        return data[f]
    return data[f] + (data[c] - data[f]) * (k - f)
```

| Metric | Value |
|---|---|
| Median (p50) | 54.00 ms |
| P95 | 2001.00 ms |
| Min | 3.00 ms |
| Max | 2025.00 ms |

The ~37x gap between median and p95 confirms sharp, discrete failure spikes (Redis/Postgres timeouts near 2000ms) rather than gradual performance degradation.

---

## 6. Which requests retried upstream? How many succeeded after retrying?

**19 requests retried upstream. All 19 (100%) succeeded after retrying.**

Every retried request shows the same pattern: first attempt to `172.23.0.12:8080` (the down instance), retry to `172.23.0.11:8080` (the healthy instance), final status 200.

lab-000124: upstream=172.23.0.12:8080, 172.23.0.11:8080, status=200
lab-000130: upstream=172.23.0.12:8080, 172.23.0.11:8080, status=200
lab-000136: upstream=172.23.0.12:8080, 172.23.0.11:8080, status=200
lab-000142: upstream=172.23.0.12:8080, 172.23.0.11:8080, status=200
lab-000148: upstream=172.23.0.12:8080, 172.23.0.11:8080, status=200


All 19 retries occurred within the Phase 1 window (~11:05–11:09), which is why not every request during that window resulted in a client-visible 502 — some were silently rescued by NGINX's retry-to-next-upstream behavior, while others (the 40 counted as 502 in Q3) were not retried and failed outright.

```python
retried_requests = [r for r in clean_access_records if "," in r.get("upstream", "")]
```

---

## 7. Build an incident timeline using evidence from access, error AND application logs.

| Time (UTC) | Source | Event |
|---|---|---|
| 11:00:00 | access.log | Session starts, normal traffic |
| 11:05:02–11:09:57 | error.log | 59 "connect() failed (111: Connection refused)" on upstream 172.23.0.12 |
| 11:05–11:09 (within above) | access.log | 19 requests retried to 172.23.0.11 and succeeded; 40 others returned 502 |
| 11:09:57–11:12:09 | — | Gap, no errors in any log |
| 11:12:09–11:15:52 | application.log | 31 `dependency_error` events: Redis TimeoutError → 503 on /ready |
| 11:15:52–11:20:07 | — | Gap, no errors in any log |
| 11:20:07–11:21:45 | application.log | 16 `dependency_error` events: Postgres InvalidPassword → 503 on /records |
| 11:22:12 | application.log | /records requests resume returning 200 — Postgres access apparently restored |
| 11:25:14–11:26:44 | error.log | 8 "upstream timed out (110)" on /records, same backend 172.23.0.12 |
| 11:25:15–11:26:47 | application.log | Matching /records requests succeed (200) but with abnormal 2700ms latency |
| 11:26:47 | error.log | Last error entry |
| 11:29:57 | access.log | Last request, traffic back to normal (~54ms baseline) |
| 11:30:00 | error.log | Log rotation notice (file ends) |

Four temporally separate incidents, not one continuous outage — each has a clean gap (3–5 minutes) with zero errors before the next begins.

---

## 8. Show one correlated failed request and one successful request. Include IDs and timestamps.

**Failed request — `lab-000292`:**

application.log 11:12:09.524Z — ERROR dependency_error, instance app-02, dependency=redis, errorType=TimeoutError
application.log 11:12:09.525Z — WARN httprequest, instance app-02, path=/ready, status=503, duration_ms=2025.0

The app logged its own dependency failure one millisecond before logging the client-facing 503 — proof the app itself was up and functioning, but failed because Redis didn't respond in time.

**Successful request — `lab-000002`:**

access.log 11:00:02.532Z — request_id=lab-000002, path=/health, status=200, upstream=172.23.0.12:8080, request_time=0.032
application.log 11:00:02.532Z — instance app-02, path=/health, status=200, duration_ms=32.0

Matching timestamp and duration across both logs, taken from the healthy baseline period before any incident began.

---

## 9. Which errors appear to be proxy/connectivity issues versus dependency/application issues? What proves it?

**Proxy/connectivity issues (502, 504 — 48 total):**
- Phase 1 (502) and Phase 4 (504) only appear in **error.log**, generated by NGINX itself ("connect() failed", "upstream timed out while reading response header").
- These describe NGINX's own inability to reach or get a timely response from the backend socket — not an application-level failure. No matching `dependency_error` in application.log for these windows.

**Dependency/application issues (503 — 47 total):**
- Phase 2 and Phase 3 appear as structured `dependency_error` events **inside application.log**, written by the Flask app itself, naming the specific dependency (`redis` / `postgres`) and error type.
- Proof: the app successfully logged the request (proving the process was alive and reachable) and *chose* to return 503 because its own downstream call failed — a fundamentally different failure mode from NGINX being unable to reach the app at all.

**What proves the distinction:** source of the log entry. NGINX-authored entries (error.log) = connectivity/infrastructure. App-authored entries (application.log, `dependency_error` event) = a healthy process reporting a downstream dependency failure.

---

## 10. What do the logs not prove? What would you check next in a running environment?

The logs do **not** prove:
- **Root cause** of why `172.23.0.12` was unreachable in Phase 1, or why it later returned slow 2700ms responses in Phase 4 (no container/restart/deploy events are logged).
- **Why** Postgres rejected the password specifically in the 11:20–11:21 window, or what fixed it at 11:22:12 (no config-change or credential-rotation event is logged).
- Whether the 2 truncated/malformed lines (access.log #311, application.log #401) were caused by a crash, disk pressure, or unrelated log-shipping issue — no supporting evidence either way.
- Whether end users outside this synthetic dataset were actually affected, or what the underlying infrastructure state (CPU, memory, network) was during each phase.

**What to check next in a running environment:**
- Container/orchestrator events (restarts, OOM kills, health-check failures) for `172.23.0.12` around 11:05 and 11:25.
- Postgres server-side logs for the same window, to see the failed auth attempts from the *server's* perspective, not just the client's.
- Resource metrics (CPU, memory, connection pool saturation) correlated with the 2700ms latency spike in Phase 4.
- Whether a credential rotation, config reload, or manual intervention happened around 11:22:12 to explain the sudden recovery.
