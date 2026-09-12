# Architecture Diagram

```mermaid
graph TD
    Client["Client (browser/curl)"] -->|HTTP :8080| NGINX["NGINX (reverse proxy / load balancer)"]
    NGINX -->|:8080| App1["app-01 (Flask)"]
    NGINX -->|:8080| App2["app-02 (Flask)"]
    App1 -->|:5432| PG[("PostgreSQL")]
    App2 -->|:5432| PG
    App1 -->|:6379| Redis[("Redis")]
    App2 -->|:6379| Redis

    subgraph frontend network
        NGINX
    end
    subgraph backend network - internal only
        App1
        App2
        PG
        Redis
    end
```

## Description
- **NGINX** is the single public entry point (port 8080 on the host), load-balancing
  requests round-robin across two identical Flask application instances.
- **app-01 / app-02** are stateless Flask instances — all durable state lives in PostgreSQL
  and Redis, not in the app containers themselves.
- **PostgreSQL** stores persistent records (`/records` endpoint), backed by a named Docker
  volume for durability across container recreation.
- **Redis** stores ephemeral counter state (`/counter` endpoint).
- The `backend` Docker network is marked `internal: true`, so PostgreSQL and Redis are not
  directly reachable from outside the Docker network — only through the app containers.
