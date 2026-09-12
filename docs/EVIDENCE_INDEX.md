# Evidence Index

Maps every requirement to the commit and evidence that satisfies it.

| Requirement | Evidence Location | Commit |
|---|---|---|
| Fix NGINX port mismatch | docker-compose.yml, troubleshooting.md Entry 1 | 36df0cd |
| Fix NGINX upstream port | nginx/nginx.conf, troubleshooting.md Entry 2 | 321e5f5 |
| Fix Flask bind address (0.0.0.0) | docker-compose.yml, troubleshooting.md Entry 3 | 36df0cd |
| Fix healthcheck endpoint (/healthz → /health) | docker-compose.yml, troubleshooting.md Entry 4 | 36df0cd |
| Fix duplicate INSTANCE_ID | docker-compose.yml, troubleshooting.md Entry 5 | 36df0cd |
| Fix DB/Redis credentials and ports | config/app.env, troubleshooting.md Entry 6 | 1d21d0e |
| Fix PostgreSQL persistence (tmpfs) | docker-compose.yml, troubleshooting.md Entry 7 | 36df0cd |
| Log analysis (10 questions) | log_analysis.md | [add commit hash after pushing] |
| Environment validation script | validate.py — 6/6 checks PASS | [add commit hash] |
| Failure/recovery test | failure_test.py — 6/6 checks PASS | [add commit hash] |
| Backup/restore scripts | backup.sh, restore.sh | [add commit hash] |
| CI/CD pipeline | .github/workflows/ci.yml | [add commit hash] |
| Technical decisions | decisions.md | [add commit hash] |
| Security review (9 items) | security_review.md | [add commit hash] |
| AI usage disclosure | AI_USAGE.md | [add commit hash] |
| Architecture diagram | architecture.md | [add commit hash] |
| Video walkthrough | [add video URL after recording] | n/a |
