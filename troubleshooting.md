

## Entry 1 — NGINX port mismatch (host mapping vs listen directive)
- Symptom: `curl -v http://127.0.0.1:8080/` failed immediately with `Connection refused`. No request reached NGINX at all.
- Hypothesis: The Compose file maps the host port to a container port that NGINX is not actually listening on.
- Command or test:
  ```
  curl -v http://127.0.0.1:8080/
  ```
- Actual output:
  ```
  * connect to 127.0.0.1 port 8080 failed: Connection refused
  curl: (7) Failed to connect to 127.0.0.1 port 8080 after 0 ms: Couldn't connect to server
  ```
- Failed attempt and what changed your thinking: None needed here — reading `docker-compose.yml` and `nginx/nginx.conf` side by side immediately showed the mismatch before any blind fix was attempted.
- Root cause: `docker-compose.yml` mapped `127.0.0.1:${PUBLIC_PORT:-8080}:81` (host:8080 → container:81), but `nginx/nginx.conf` had `listen 80;`. NGINX was listening on port 80 inside the container, not 81, so Docker's port forward pointed at a port nothing was bound to.
- Fix: Changed the Compose port mapping to `127.0.0.1:${PUBLIC_PORT:-8080}:80` so the host port forwards to the port NGINX actually listens on.
- Retest evidence:
  ```
  curl -v http://127.0.0.1:8080
  < HTTP/1.1 502 Bad Gateway
  ```
  Connection refused was gone — NGINX was now reachable. The 502 pointed to the next issue (upstream), confirming this specific fix worked.
- Related commit: `36df0cd` (fix: resolve NGINX port mapping, Flask bind address, healthcheck path, instance IDs, and postgres volume mount)
- Remaining uncertainty: None on this specific issue — fully confirmed by the retest.

---

## Entry 2 — NGINX upstream pointing to wrong app-01 port
- Symptom: After fixing Entry 1, requests reached NGINX but returned `502 Bad Gateway`.
- Hypothesis: NGINX's upstream block for `app-01` points to a port the Flask app is not actually running on.
- Command or test:
  ```
  docker compose -p barq-assessment logs nginx --no-color --tail=10
  ```
- Actual output:
  ```
  2026/09/10 09:48:46 [error] connect() failed (111: Connection refused) while connecting to upstream,
  upstream: "http://172.20.0.3:8081/"
  ```
- Failed attempt and what changed your thinking: None — the nginx.conf upstream block clearly showed `server app-01:8081` while `app-02:8080` was correct, and both apps share the same `APP_PORT: "8080"` environment value from the shared `x-app` anchor.
- Root cause: `nginx.conf` had a typo/mismatch — `app-01` was pointed to port `8081`, but the Flask app inside both `app-01` and `app-02` listens on `8080` (from `APP_PORT` env var).
- Fix: Changed `server app-01:8081` to `server app-01:8080` in the upstream block.
- Retest evidence: 502 persisted after this fix alone — this was expected, because Entry 3 (APP_HOST) was still broken and blocking all upstream connections regardless of port correctness. Fix was only confirmed correct after Entry 3 was also resolved (see Entry 3 retest).
- Related commit: `36df0cd`
- Remaining uncertainty: None — later combined retest in Entry 3 confirmed both fixes together resolved the 502.

---

## Entry 3 — Flask app bound to 127.0.0.1 instead of 0.0.0.0 (root cause of persistent 502)
- Symptom: Even after fixing Entries 1 and 2, `curl http://127.0.0.1:8080/` still returned `502 Bad Gateway`. Docker showed both `app-01` and `app-02` as `Up ... (unhealthy)`.
- Hypothesis: The Flask process itself might not be accepting connections from outside its own container, even though the port number was now correct.
- Command or test:
  ```
  docker network inspect barq-assessment_backend
  docker compose -p barq-assessment logs nginx --no-color --tail=10
  ```
- Actual output:
  ```
  connect() failed (111: Connection refused) while connecting to upstream,
  upstream: "http://172.19.0.2:8080/"
  ```
  The IP address matched a container on the correct subnet, ruling out a stale-network theory. The port (8080) was already correct at this point, yet the connection was still refused.
- Failed attempt and what changed your thinking: Initially suspected Docker network/DNS caching from repeated `up`/`down` cycles and tried `docker compose down && docker network prune -f && up --build` to force a clean network. This did NOT fix the issue — the exact same "Connection refused" on the correct port persisted, which ruled out networking/DNS cache as the cause and pointed instead to the Flask process's own bind address.
- Root cause: In `docker-compose.yml`, the shared `x-app` environment block set `APP_HOST: "127.0.0.1"`. This tells Flask to only accept connections originating from inside its own container (loopback). NGINX, running in a separate container, connects over the Docker network — which Flask was rejecting because it wasn't listening on `0.0.0.0` (all interfaces).
- Fix: Changed `APP_HOST` from `"127.0.0.1"` to `"0.0.0.0"` in `docker-compose.yml`.
- Retest evidence:
  ```
  curl -v http://127.0.0.1:8080
  < HTTP/1.1 200 OK
  {"instance_id":"app-01","message":"Welcome to BARQ Systems","service":"barq-api","version":"2.0.0"}
  ```
  First successful end-to-end response from the whole stack.
- Related commit: `36df0cd`
- Remaining uncertainty: None — confirmed by direct successful HTTP response.

---

## Entry 4 — Health check endpoint mismatch (/healthz vs /health)
- Symptom: Docker reported both app containers as `unhealthy` even while the Flask process was logging active requests. Logs showed repeated `404` responses to the health check probe.
- Hypothesis: The health check is probing a path that doesn't exist in the Flask app's route table.
- Command or test:
  ```
  docker compose -p barq-assessment logs app-01 --no-color
  cat app/server.py
  ```
- Actual output:
  ```
  "GET /healthz HTTP/1.1" 404 -
  ```
  `app/server.py` showed the actual route defined as `@app.get("/health")` — no `/healthz` route exists anywhere in the code.
- Failed attempt and what changed your thinking: None needed — comparing the healthcheck command in `docker-compose.yml` (`.../healthz`) against the Flask route decorators in `server.py` (`/health`) made the one-character mismatch immediately obvious.
- Root cause: `docker-compose.yml` healthcheck command targeted `http://127.0.0.1:8080/healthz`, but the Flask route is registered as `/health` (no trailing `z`).
- Fix: Removed the `z` from the healthcheck URL in `docker-compose.yml`.
- Retest evidence:
  ```
  docker compose -p barq-assessment ps -a
  app-01   Up 51 seconds (healthy)
  app-02   Up 52 seconds (healthy)
  ```
- Related commit: `36df0cd`
- Remaining uncertainty: None.

---

## Entry 5 — Duplicate INSTANCE_ID between app-01 and app-02
- Symptom: The task requires proving two distinct backend instances are serving traffic through `/instance`, but both containers reported the same identity.
- Hypothesis: `app-02`'s environment override is not actually overriding the shared `INSTANCE_ID` value.
- Command or test:
  ```
  grep -A3 "app-02:" docker-compose.yml
  ```
- Actual output:
  ```yaml
  app-02:
    environment:
      <<: *app-env
      INSTANCE_ID: "app-01"
  ```
- Failed attempt and what changed your thinking: None — direct code inspection found the copy-paste error immediately (the override value itself was wrong, not the override mechanism).
- Root cause: `app-02`'s `INSTANCE_ID` override was hardcoded to `"app-01"` instead of `"app-02"` — a copy-paste error in the starter Compose file.
- Fix: Changed the value to `"app-02"`.
- Retest evidence:
  ```
  for i in 1 2 3 4; do curl -s http://127.0.0.1:8080/instance; echo; done
  {"instance_id":"app-01", ...}
  {"instance_id":"app-01", ...}
  {"instance_id":"app-02", ...}
  {"instance_id":"app-01", ...}
  ```
  Both distinct instance IDs now appear across repeated requests, confirming NGINX load-balances across two genuinely different backend identities.
- Related commit: `36df0cd`
- Remaining uncertainty: None.

---

## Entry 6 — DATABASE_URL and REDIS_URL mismatched with actual service credentials/ports
- Symptom: `GET /ready` returned `503` with `{"postgres":"unavailable","redis":"unavailable"}` even though both `postgres` and `redis` containers were healthy on their own.
- Hypothesis: The application's connection strings don't match the actual credentials/ports the database and cache containers are configured with.
- Command or test:
  ```
  cat config/app.env
  ```
  compared against the `postgres` and `redis` service blocks in `docker-compose.yml`.
- Actual output:
  ```
  config/app.env:
    DATABASE_URL=postgresql://barq_app:BarqLabOnly_7qN2vK8d@postgres:5433/barq_tasks
    REDIS_URL=redis://redis:6380/0

  docker-compose.yml:
    POSTGRES_PASSWORD: BarqLabOnly_7qN2vK8c   (ends in "c", not "d")
    postgres internal port: 5432 (default)     (not 5433)
    redis internal port: 6379 (default)        (not 6380)
  ```
- Failed attempt and what changed your thinking: First edit only corrected the PostgreSQL port (5433 → 5432) and Redis port, but left the password untouched by mistake (the single-character `d`/`c` difference was easy to miss). Retest still showed `"postgres":"unavailable"` while `"redis":"ready"` — this partial success proved the port fix was correct and isolated the password as the one remaining wrong value, rather than requiring a fresh guess.
- Root cause: `config/app.env` was seeded with an intentionally incorrect password (last character `d` instead of `c`) and incorrect ports for both services, not matching the ports/credentials Postgres and Redis were actually started with in `docker-compose.yml`.
- Fix: Corrected `DATABASE_URL` to use password ending in `c` and port `5432`; corrected `REDIS_URL` to use port `6379`.
- Retest evidence:
  ```
  curl http://127.0.0.1:8080/ready
  {"dependencies":{"postgres":"ready","redis":"ready"},"status":"ready"}
  ```
- Related commit: `1d21d0e` (fix: correct DATABASE_URL password and port, and REDIS_URL port)
- Remaining uncertainty: None.

---

## Entry 7 — PostgreSQL data stored on tmpfs, causing data loss on container recreation
- Symptom: A record created via `POST /records` disappeared after restarting or recreating the `postgres` container, while only the seed data from `init.sql` remained.
- Hypothesis: The PostgreSQL data directory is not mounted on the persistent named volume — it may be on ephemeral storage.
- Command or test:
  ```
  # Before fix — reproduce the data loss:
  curl -X POST http://127.0.0.1:8080/records -d '{"title":"test record"}'
  curl http://127.0.0.1:8080/records          # record present (id:3)
  docker compose -p barq-assessment restart postgres
  curl http://127.0.0.1:8080/records          # record gone
  ```
- Actual output:
  ```
  Before restart: [{"id":1,...},{"id":2,...},{"id":3,"title":"test record"}]
  After restart:  [{"id":1,...},{"id":2,...}]   <- id:3 lost
  ```
- Failed attempt and what changed your thinking: None — `docker-compose.yml` inspection directly showed the misconfiguration (volume mounted to `/backup`, actual data directory on `tmpfs`), so no blind trial was needed before identifying the fix.
- Root cause: The `postgres` service mounted the named volume to `/var/lib/postgresql/backup` (wrong path — not where Postgres stores live data) while simultaneously mounting `/var/lib/postgresql/data` (the real data directory) on `tmpfs`, i.e. RAM. Any data written was never persisted to disk; it was only ever in memory and vanished on container restart/recreation.
- Fix: Changed the named volume mount target to `/var/lib/postgresql/data` and removed the `tmpfs` entry entirely.
- Retest evidence:
  ```
  curl -X POST http://127.0.0.1:8080/records -d '{"title":"persistence test"}'   # id:4 created
  docker compose -p barq-assessment stop postgres
  docker compose -p barq-assessment rm -f postgres
  docker compose -p barq-assessment up -d postgres
  curl http://127.0.0.1:8080/records
  {"records":[{"id":1,...},{"id":2,...},{"id":3,...},{"id":4,"title":"persistence test"}]}
  ```
  Record survived a full container removal and recreation (stop → rm → up), a stronger test than a simple restart, confirming true persistence via the named volume.
- Related commit: `36df0cd`
- Remaining uncertainty: The `postgres-data` volume from earlier broken runs was not explicitly pruned before this final retest, so seed IDs 1–3 in the evidence above include leftover data from prior manual testing rather than a completely fresh volume. The persistence mechanism itself is confirmed correct regardless.
---

---

## Entry 8 — Task requirements violated: published DB/cache ports and NGINX on both networks

- Symptom: No runtime error — the stack was fully healthy and all endpoints worked. The gap
  was discovered by re-reading `assessment/TASK.md` in full after assuming the technical
  fixes were complete, rather than from any failure or log output.
- Hypothesis: The starter `docker-compose.yml` might not fully match the explicit Part 2
  requirements in TASK.md, since earlier work had focused only on making the stack functional,
  not on auditing it against every listed constraint.
- Command or test:

cat docker-compose.yml

  compared line by line against TASK.md's explicit requirements:
  - "Publish only NGINX on host port 8080. Do not publish app, PostgreSQL or Redis ports."
  - "Connect NGINX + apps to frontend; apps + PostgreSQL + Redis to backend."
  - "Set correct environment variables, health/readiness checks, restart policies and resource limits."
- Actual output: Three violations found in the current `docker-compose.yml`:
  1. `postgres` had `ports: ["127.0.0.1:15432:5432"]` — a published host port, not permitted.
  2. `redis` had `ports: ["127.0.0.1:16379:6379"]` — a published host port, not permitted.
  3. `nginx` was connected to `networks: [frontend, backend]` — TASK.md requires NGINX on
     `frontend` only, since it should never reach PostgreSQL/Redis directly.
  4. All services had `restart: "no"` (app anchor) or no restart policy at all (postgres, redis,
     nginx) — TASK.md requires "correct... restart policies."
- Failed attempt and what changed your thinking: None — this was found by direct comparison
  of the config file against the written requirements, not by trial and error.
- Root cause: The starter project's `docker-compose.yml` was functionally correct (all
  endpoints worked, health checks passed) but did not fully comply with the task's explicit
  network-isolation and port-publishing constraints. A working stack is not the same as a
  compliant one — this was missed initially because attention was on making things run, not
  on auditing every written constraint after the fact.
- Fix:
  - Removed the `ports:` mapping entirely from both `postgres` and `redis` services.
  - Changed `nginx`'s `networks:` from `[frontend, backend]` to `[frontend]` only.
  - Added `restart: unless-stopped` to the shared app anchor, `postgres`, `redis`, and `nginx`.
  - Changed Redis's `--save ""` (persistence fully disabled) to `--save 60 1` (snapshot if at
    least 1 key changed in 60 seconds), to satisfy "Configure Redis persistence where appropriate."
- Retest evidence:

docker compose -p barq-assessment down
docker compose -p barq-assessment up -d --build
docker port postgres # no output — port no longer published
docker port redis # no output — port no longer published
curl -v http://127.0.0.1:8080/ready

HTTP/1.1 200 OK
{"dependencies":{"postgres":"ready","redis":"ready"},"status":"ready",...}
  All five containers remained healthy after the change, and public connectivity through
  NGINX was unaffected, confirming the network/port changes did not break functionality
  while bringing the stack into compliance with TASK.md.
- Related commit: [4a00846]
- Remaining uncertainty: Resource limits (CPU/memory) from TASK.md's Part 2 requirements are
  still not set on any service; this is a known remaining gap tracked separately, not
  something this fix addresses.

---

## Summary of fixes and affected files

| # | Issue | File | Commit |
|---|---|---|---|
| 1 | NGINX host:container port mismatch (81 vs 80) | docker-compose.yml | 36df0cd |
| 2 | NGINX upstream wrong port for app-01 | nginx/nginx.conf | 321e5f5 |
| 3 | Flask APP_HOST bound to loopback only | docker-compose.yml | 36df0cd |
| 4 | Healthcheck probing non-existent /healthz | docker-compose.yml | 36df0cd |
| 5 | Duplicate INSTANCE_ID on app-02 | docker-compose.yml | 36df0cd |
| 6 | Wrong DB/Redis credentials and ports | config/app.env | 1d21d0e |
| 7 | PostgreSQL data on tmpfs (no persistence) | docker-compose.yml | 36df0cd |
