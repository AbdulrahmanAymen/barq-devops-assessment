import json
def parse_access_log(path):
    valid_lines = []
    malformed_count = 0

    with open(path) as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                valid_lines.append(record)
            except json.JSONDecodeError:
                malformed_count += 1
                print(f"Malformed line #{line_number}: {line[:80]}")

    return valid_lines, malformed_count

access_records, access_malformed = parse_access_log("logs/access.log")

print(f"\nTotal valid JSON lines: {len(access_records)}")
print(f"Total malformed lines: {access_malformed}")

from collections import Counter
request_ids = [record["request_id"] for record in access_records]
id_counts = Counter(request_ids)
duplicates = {rid: count for rid, count in id_counts.items() if count > 1}
print(f"\nUnique request_ids: {len(id_counts)}")
print(f"Duplicated request_ids: {len(duplicates)}")
if duplicates:
    print("Examples of duplicates:")
    for rid, count in list(duplicates.items())[:5]:
        print(f"  {rid}: appears {count} times")
def parse_application_log(path):
    valid_lines = []
    malformed_count = 0
    with open(path) as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                valid_lines.append(record)
            except json.JSONDecodeError:
                malformed_count += 1
                print(f"Malformed line #{line_number} in application.log: {line[:80]}")
    return valid_lines, malformed_count
app_records, app_malformed = parse_application_log("logs/application.log")
print(f"\n=== application.log ===")
print(f"Total valid JSON lines: {len(app_records)}")
print(f"Total malformed lines: {app_malformed}")
app_request_ids = [r["request_id"] for r in app_records]
app_id_counts = Counter(app_request_ids)
app_duplicates = {rid: count for rid, count in app_id_counts.items() if count > 1}
print(f"Unique request_ids: {len(app_id_counts)}")
print(f"Duplicated request_ids: {len(app_duplicates)}")
app_dup_ids = {rid: count for rid, count in app_id_counts.items() if count > 1}
print("\n=== Sample application.log duplicates ===")
for rid in list(app_dup_ids.keys())[:3]:
    print(f"\n--- {rid} (appears {app_dup_ids[rid]} times) ---")
    matches = [r for r in app_records if r["request_id"] == rid]
    for m in matches:
        print(m)

literal_duplicates = 0
multi_event_requests = 0

for rid, count in app_dup_ids.items():
    matches = [r for r in app_records if r["request_id"] == rid]
    events = [m.get("event") for m in matches]
    if matches[0] == matches[1] if count == 2 else all(m == matches[0] for m in matches):
        literal_duplicates += 1
    else:
        multi_event_requests += 1
print(f"\n=== Classification of application.log duplicates ===")
print(f"Literal duplicate log lines: {literal_duplicates}")
print(f"Multi-event requests (e.g. dependency_error + http_request): {multi_event_requests}")


dependency_errors = [r for r in app_records if r.get("event") == "dependency_error"]
print(f"\n=== Dependency errors breakdown ===")
print(f"Total dependency_error events: {len(dependency_errors)}")

dep_types = Counter((r.get("dependency"), r.get("error_type")) for r in dependency_errors)
for (dep, err_type), count in dep_types.items():
    print(f"  {dep} / {err_type}: {count} times")


if dependency_errors:
    timestamps = sorted(r["timestamp"] for r in dependency_errors)
    print(f"\nFirst dependency error: {timestamps[0]}")
    print(f"Last dependency error: {timestamps[-1]}")

redis_errors = [r for r in dependency_errors if r.get("dependency") == "redis"]
postgres_errors = [r for r in dependency_errors if r.get("dependency") == "postgres"]

redis_times = sorted(r["timestamp"] for r in redis_errors)
postgres_times = sorted(r["timestamp"] for r in postgres_errors)

print(f"\n=== Redis TimeoutError window ===")
print(f"First: {redis_times[0]}")
print(f"Last:  {redis_times[-1]}")

print(f"\n=== Postgres InvalidPassword window ===")
print(f"First: {postgres_times[0]}")
print(f"Last:  {postgres_times[-1]}")


import re

def parse_error_log(path):
    entries = []
    malformed_count = 0
    with open(path) as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            match = re.search(r'(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}).*request_id=(\S+),', line)
            if match:
                entries.append({"timestamp": match.group(1), "request_id": match.group(2), "raw": line})
            else:
                malformed_count += 1
                print(f"Unparseable error.log line #{line_number}: {line[:80]}")
    return entries, malformed_count

error_entries, error_malformed = parse_error_log("logs/error.log")
print(f"\n=== error.log ===")
print(f"Total parsed entries: {len(error_entries)}")
print(f"Unparseable lines: {error_malformed}")

if error_entries:
    times = sorted(e["timestamp"] for e in error_entries)
    print(f"First error: {times[0]}")
    print(f"Last error:  {times[-1]}")


from collections import defaultdict

errors_per_minute = defaultdict(int)
for e in error_entries:
    minute_key = e["timestamp"][:16]
    errors_per_minute[minute_key] += 1

print(f"\n=== error.log timeline (errors per minute) ===")
for minute in sorted(errors_per_minute.keys()):
    print(f"  {minute}: {errors_per_minute[minute]} errors")
seen_ids = set()
clean_access_records = []
for r in access_records:
    if r["request_id"] not in seen_ids:
        seen_ids.add(r["request_id"])
        clean_access_records.append(r)

print(f"\n=== Q3: Status counts (deduplicated access.log) ===")
print(f"Denominator (distinct client requests): {len(clean_access_records)}")

status_counts = Counter(r["status"] for r in clean_access_records)
for status, count in sorted(status_counts.items()):
    print(f"  {status}: {count}")

error_count = sum(count for status, count in status_counts.items() if status >= 400)
error_rate = (error_count / len(clean_access_records)) * 100
print(f"\nTotal errors (status >= 400): {error_count}")
print(f"Error rate: {error_rate:.2f}%")


import statistics

latencies_ms = sorted(r["request_time"] * 1000 for r in clean_access_records)

def percentile(data, p):
    if not data:
        return None
    k = (len(data) - 1) * (p / 100)
    f = int(k)
    c = min(f + 1, len(data) - 1)
    if f == c:
        return data[f]
    return data[f] + (data[c] - data[f]) * (k - f)

median_latency = statistics.median(latencies_ms)
p95_latency = percentile(latencies_ms, 95)

print(f"\n=== Q5: Latency (all {len(latencies_ms)} distinct requests, in milliseconds) ===")
print(f"Median (p50): {median_latency:.2f} ms")
print(f"P95:          {p95_latency:.2f} ms")
print(f"Min:          {min(latencies_ms):.2f} ms")
print(f"Max:          {max(latencies_ms):.2f} ms")



retried_requests = [r for r in clean_access_records if "," in r.get("upstream", "")]

print(f"\n=== Q6: Retry analysis ===")
print(f"Total requests that retried upstream: {len(retried_requests)}")

if retried_requests:
    succeeded_after_retry = [r for r in retried_requests if r["status"] < 400]
    print(f"Succeeded after retry: {len(succeeded_after_retry)}")
    print(f"\nSample retried requests:")
    for r in retried_requests[:5]:
        print(f"  {r['request_id']}: upstream={r['upstream']}, status={r['status']}")
else:
    print("No requests found with comma-separated upstream values.")


