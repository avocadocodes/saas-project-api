# Load Test

Uses [k6](https://k6.io) to exercise the projects and tasks endpoints under sustained load.

## Prerequisites

1. A running API instance (Docker Compose or local).
2. A valid JWT token for a seeded user (see below).

## Get a token

```bash
export TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"jane@acme.com","password":"securepass123"}' | jq -r .access)
```

Or use the register endpoint to create an account first:

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"organization_name":"Loadtest Org","email":"loadtest@example.com","password":"securepass123"}'
```

## Run with Docker (no local k6 install needed)

```bash
docker run --rm -i \
  -e BASE_URL=http://host.docker.internal:8000 \
  -e TOKEN=$TOKEN \
  grafana/k6 run - < loadtest/load-test.js
```

On Linux, replace `host.docker.internal` with your host IP or use `--network host`.

## Run locally (k6 installed)

```bash
BASE_URL=http://localhost:8000 TOKEN=$TOKEN k6 run loadtest/load-test.js
```

## Load profile

| Stage | Duration | Target VUs |
|-------|----------|------------|
| Ramp up | 30 s | 10 |
| Sustained | 1 min | 25 |
| Ramp down | 30 s | 0 |

## What it tests

- `GET /api/v1/projects/` - every iteration
- `GET /api/v1/tasks/` - every iteration
- `POST /api/v1/tasks/` - ~10% of iterations

## Pass/fail thresholds

- p95 response time < 500 ms
- HTTP error rate < 1%
