# Technical Decisions

## 1. Fixed the Compose port mapping rather than changing NGINX's listen directive
**Context:** `docker-compose.yml` mapped `host:8080 → container:81`, but `nginx.conf` had `listen 80;`.
**Decision:** Changed the Compose mapping to `host:8080 → container:80` instead of changing NGINX to `listen 81;`.
**Why:** Port 80 is the standard convention for NGINX; changing the mapping to match it keeps the NGINX config idiomatic and leaves fewer non-standard values to explain later.

## 2. Aligned app-01's upstream port with the shared environment pattern instead of hardcoding
**Context:** `nginx.conf` pointed `app-01` to port `8081`, but both apps share `APP_PORT: "8080"` from a common Compose anchor (`x-app`).
**Decision:** Corrected the upstream entry to `8080` rather than adding a per-instance override.
**Why:** Both instances are meant to be interchangeable; a shared port keeps the config symmetric and avoids a special case that could silently drift out of sync again.

## 3. Changed `APP_HOST` to `0.0.0.0` instead of adding networking workarounds
**Context:** Flask was bound to `127.0.0.1` inside its container, so NGINX (a separate container) could not reach it, even after the port mismatch was fixed.
**Decision:** Changed the bind address directly rather than trying custom Docker network aliases or `host` networking mode.
**Why:** `0.0.0.0` is the standard, minimal fix for "accept connections from other containers on the same network" — anything more elaborate would have added complexity without solving a problem that didn't exist.

## 4. Removed `tmpfs` entirely rather than keeping both mount paths
**Context:** PostgreSQL's data directory (`/var/lib/postgresql/data`) was mounted on `tmpfs` (RAM), while the named volume was mounted to the wrong path (`/backup`), so data never persisted.
**Decision:** Pointed the named volume directly at `/var/lib/postgresql/data` and deleted the `tmpfs` entry, rather than keeping both and trying to sync them.
**Why:** Two mounts on the data directory is inherently ambiguous about which one is authoritative. A single named volume at the correct path is the simplest configuration that guarantees durability.

## 5. Used `stop` → `rm` → `up` instead of `restart` to test persistence
**Context:** Needed to prove PostgreSQL data survives container recreation, not just a process restart.
**Decision:** Tested with a full container removal and recreation cycle, not just `docker compose restart`.
**Why:** A `restart` keeps the same container (and its writable layer) alive, which is a weaker test. Removing and recreating the container proves the data is durable independent of any container-level state — which is the actual guarantee `docker compose down/up` provides operators in production.

## 6. Used Python's standard library (`urllib`) instead of `requests` for validate.py and failure_test.py
**Context:** Both scripts needed to make HTTP calls against the running stack.
**Decision:** Used `urllib.request` from the standard library rather than adding `requests` as a dependency.
**Why:** Keeps the scripts runnable with zero extra `pip install` steps — important for portability in CI and for anyone reviewing the submission without a pre-configured environment.

## 7. Chose `app-01` (not `postgres`) as the failure target in failure_test.py
**Context:** The task required testing failure and recovery of "one backend."
**Decision:** Stopped an application container rather than a database container.
**Why:** Stopping an app instance directly exercises NGINX's load-balancing and upstream-failure behavior (which is the load-balancer's actual job), producing a clean, predictable, and explainable 50/50 split in traffic given `proxy_next_upstream off;`. Stopping Postgres would test a different failure mode (dependency failure) already covered by the historical log analysis.

## 8. Guaranteed cleanup with `try/finally` in failure_test.py
**Context:** The script stops a real container as part of the test.
**Decision:** Wrapped the failure-inducing steps in `try/finally` so the target container is always restarted, even if a later assertion raises an exception.
**Why:** A test that leaves the environment broken after a failed assertion is worse than not running the test — cleanup must be unconditional, not just the "happy path."
