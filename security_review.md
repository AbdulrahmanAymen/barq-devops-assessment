# Security Review

Review of the current stack configuration (docker-compose.yml, nginx.conf, config/app.env)
as delivered after the fixes in troubleshooting.md. Each item below is a real risk or
improvement opportunity observed directly in this project's configuration.

## 1. Database credentials are stored in plaintext
`config/app.env` and `docker-compose.yml` both contain the PostgreSQL password as a plain
string, and this file is tracked in the repository. **Risk:** anyone with repo access has
production-equivalent credentials. **Recommendation:** use Docker secrets, a `.env` file
excluded via `.gitignore`, or a secrets manager (Vault, AWS Secrets Manager) instead of
committing credentials to version control.

## 2. No TLS/HTTPS anywhere in the stack
NGINX listens on plain HTTP (port 80/8080) with no TLS termination. **Risk:** all traffic,
including any credentials or data in request bodies, travels unencrypted. **Recommendation:**
terminate TLS at NGINX (or an upstream load balancer) using a certificate, even a self-signed
one for internal environments, and redirect HTTP → HTTPS.

## 3. Postgres and Redis ports are published to the host
`docker-compose.yml` maps `127.0.0.1:15432 → postgres:5432` and `127.0.0.1:16379 → redis:6379`.
While bound to loopback (not `0.0.0.0`), this still exposes both services outside the Docker
network to anything running on the host. **Recommendation:** remove these port mappings
entirely for the app and DB services; only NGINX needs a published port. Use `docker exec`
or the internal network for any debugging access.

## 4. No rate limiting on the public-facing endpoint
NGINX has no `limit_req` or similar directive. **Risk:** the API is open to trivial
denial-of-service via request flooding. **Recommendation:** add a rate-limiting zone in
`nginx.conf` scoped per client IP.

## 5. No authentication/authorization on write endpoints
`POST /records` accepts writes from any client with no API key, token, or auth check.
**Risk:** any party that can reach the service can write arbitrary data. **Recommendation:**
add at minimum an API key check at the NGINX or application layer for mutating endpoints.

## 6. Health/readiness endpoints leak internal implementation details
`GET /ready` returns the specific dependency name and error type (e.g. `"redis":
"TimeoutError"`) to any caller. **Risk:** this is useful reconnaissance information for an
attacker probing the system's internals. **Recommendation:** return a generic `"not ready"`
to external callers and log the detailed error type only server-side.

## 7. No image pinning verification / vulnerability scanning in CI
The CI pipeline builds and runs the images but does not scan them for known CVEs.
**Recommendation:** add a step using `docker scout` or `trivy` to scan built images before
deployment, and fail the pipeline on critical findings.

## 8. Backups are stored unencrypted on the host filesystem
`backup.sh` produces a plaintext `.sql` dump with no encryption at rest. **Risk:** anyone
with filesystem access to the backups directory can read all data, including any credentials
stored in application tables. **Recommendation:** encrypt backup files (e.g. with `gpg` or
`age`) before they leave the container, and control access to the backup storage location.

## 9. `internal: true` is only set on the backend network, not consistently enforced
The `backend` network is correctly marked `internal: true`, isolating Postgres/Redis from
the internet — this is a good existing practice. However, this protection is undermined by
finding #3 above (published host ports bypass the network isolation). **Recommendation:**
treat network isolation and port publishing as one control, not two independent ones — fixing
#3 restores the full benefit of this isolation.

## Positive practices already in place
- Application containers run as a non-root user (`groupadd`/`useradd app` in the Dockerfile).
- The `backend` Docker network is marked `internal: true`, isolating the database tier from
  direct internet access.
- Health checks exist on every service, enabling orchestrators to detect and react to failure.
