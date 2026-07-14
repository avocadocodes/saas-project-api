# SaaS Project Management API

**In one sentence:** the backend for a team task-manager that many companies can use at once, where each company's data is completely walled off from every other's.

Users log in, create projects and tasks within their organization, and role-based permissions decide who can do what (Owner / Admin / Member). Slow jobs like report generation run in the background so requests stay fast. Built as a production-quality multi-tenant REST API with Django REST Framework, Celery, and Redis.

![Demo: register, create a project and task, and poll an async background report to completion](docs/demo.gif)

**Live demo:** https://saas-project-api-0772.onrender.com — free-tier hosting sleeps when idle, so the first request takes ~40s to wake.

---

## Problem Statement

Teams managing multiple projects need a reliable, secure backend that keeps each organization's data completely separate, enforces role-based write policies, and handles expensive operations (like reporting) without blocking API responses.

---

## Architecture

```
                    ┌─────────────────────────────────────────┐
                    │              Client (HTTP)                │
                    └───────────────────┬─────────────────────┘
                                        │ JWT Bearer Token
                    ┌───────────────────▼─────────────────────┐
                    │         Django REST Framework             │
                    │                                           │
                    │  ┌─────────────┐   ┌──────────────────┐ │
                    │  │ Auth Views  │   │ Project/Task     │ │
                    │  │ (JWT reg/  │   │ ViewSets         │ │
                    │  │  login)    │   │ (tenant-scoped)  │ │
                    │  └─────────────┘   └──────────────────┘ │
                    │                                           │
                    │  ┌─────────────────────────────────────┐ │
                    │  │  TenantQuerysetMixin                 │ │
                    │  │  filters every QS by                 │ │
                    │  │  request.user.organization           │ │
                    │  └─────────────────────────────────────┘ │
                    └───────────┬─────────────┬───────────────┘
                                │             │
               ┌────────────────▼──┐   ┌──────▼──────────────┐
               │    PostgreSQL 16   │   │  Celery Worker       │
               │                   │   │                       │
               │  organizations    │   │  generate_project_   │
               │  users            │◄──│  report task         │
               │  projects         │   │  (reads tasks,       │
               │  tasks            │   │   writes Report)     │
               │  reports          │   └──────────────────────┘
               └───────────────────┘          │
                                        ┌─────▼───────┐
                                        │  Redis 7    │
                                        │  (broker +  │
                                        │   results)  │
                                        └─────────────┘
```

---

## Multi-Tenancy Model

Every request is authenticated via JWT. The token payload carries the user's ID, from which `request.user.organization` is resolved. The `TenantQuerysetMixin` in `apps/projects/views.py` overrides `get_queryset()` to filter all results by `organization=request.user.organization`. `perform_create()` stamps the `organization` field automatically.

**Cross-tenant access is structurally impossible:**
- A user from Org A querying `/api/v1/projects/{org_b_project_id}/` gets a 404, not a 403 — the object doesn't exist in their queryset.
- Serializer-level validation on Task also checks that the `project` and `assignee` belong to the requesting user's organization.
- There are regression tests confirming both 404 behavior (`test_cross_tenant_project_access_returns_404`) and task list isolation (`test_cross_tenant_task_not_visible`).

---

## RBAC Matrix

| Action | OWNER | ADMIN | MEMBER |
|--------|-------|-------|--------|
| List/Read projects | ✓ | ✓ | ✓ |
| Create project | ✓ | ✓ | ✓ |
| Update project | ✓ | ✓ | ✓ |
| Delete project | ✓ | ✓ | ✗ |
| CRUD tasks | ✓ | ✓ | ✓ |
| Request report | ✓ | ✓ | ✓ |
| View reports | ✓ | ✓ | ✓ |

Implemented in `apps/projects/permissions.py` as a `ProjectPermission` class. Delete operations check `request.user.role in (OWNER, ADMIN)`.

---

## Async Report Flow

1. Client: `POST /api/v1/projects/{id}/report`
2. API creates a `Report` record with `status=PENDING`, returns `202 Accepted` with the report ID.
3. `generate_project_report.delay(report_id)` is enqueued to Celery via Redis.
4. Celery worker picks up the task, aggregates task counts (total, done, in_progress, todo, completion %), writes results to `Report.data`, sets `status=READY`.
5. Client: `GET /api/v1/reports/{id}/` — polls until `status` is `READY`.

In test mode (`CELERY_TASK_ALWAYS_EAGER=True`), tasks execute synchronously, so tests don't need a live Redis/Celery.

---

## Quick Start

### Docker Compose (recommended)

```bash
git clone <repo-url> saas-project-api
cd saas-project-api
docker compose up --build
```

The container runs both Gunicorn and a Celery worker via `start.sh`. The entrypoint waits for Postgres, then runs migrations automatically.

API available at: http://localhost:8000
Swagger UI: http://localhost:8000/api/docs/

### Local Development

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL=postgres://postgres:postgres@localhost:5432/saas_project
export REDIS_URL=redis://localhost:6379/0
export SECRET_KEY=dev-secret-key

python manage.py migrate
python manage.py runserver

# In a second terminal:
celery -A celery_app worker --loglevel=info
```

---

## curl Examples

### 1. Register (creates org + owner)

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"organization_name":"Acme Corp","email":"jane@acme.com","password":"securepass123","first_name":"Jane","last_name":"Doe"}' \
  | jq .
```

### 2. Login

```bash
export TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"jane@acme.com","password":"securepass123"}' \
  | jq -r .access)
```

### 3. Create a Project

```bash
curl -s -X POST http://localhost:8000/api/v1/projects/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Website Redesign","description":"Full site overhaul Q1","status":"ACTIVE"}' \
  | jq .
```

### 4. Create a Task

```bash
export PROJECT_ID=<id-from-step-3>

curl -s -X POST http://localhost:8000/api/v1/tasks/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"project\":\"$PROJECT_ID\",\"title\":\"Design homepage\",\"status\":\"TODO\",\"due_date\":\"2025-03-31\"}" \
  | jq .
```

### 5. Request a Report

```bash
export REPORT_ID=$(curl -s -X POST http://localhost:8000/api/v1/projects/$PROJECT_ID/report \
  -H "Authorization: Bearer $TOKEN" \
  | jq -r .id)
```

### 6. Poll Report

```bash
curl -s http://localhost:8000/api/v1/reports/$REPORT_ID/ \
  -H "Authorization: Bearer $TOKEN" \
  | jq .
```

### 7. Health Check

```bash
curl -s http://localhost:8000/healthz | jq .
```

---

## Running Tests

Tests use SQLite in-memory and Celery eager mode — no external services needed.

```bash
pip install -r requirements.txt
pytest -v
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `dev-secret-key-...` | Django secret key |
| `DEBUG` | `true` | Enable debug mode |
| `DATABASE_URL` | `postgres://postgres:postgres@localhost:5432/saas_project` | Full DB URL |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis URL for Celery |
| `ALLOWED_HOSTS` | `*` | Comma-separated allowed hosts |
| `PORT` | `8000` | Gunicorn bind port |

---

## API Documentation

- Swagger UI: [/api/docs/](/api/docs/)
- OpenAPI schema (JSON): [/api/schema/](/api/schema/)

---

## Performance & Reliability

### N+1 Query Elimination

**Before:** the Task list endpoint issued one query per task row to fetch `.assignee` and `.project` (N+1 pattern). With 200 tasks that meant ~401 queries.

**After:** `TaskViewSet.get_queryset()` uses `select_related("assignee", "project")`, resolving all related rows in a single JOIN. `ProjectViewSet` annotates `task_count` and `done_task_count` using `Count(...)` with a `Q` filter — no per-row queries.

**Measured result** (`python manage.py benchmark_queries --tasks 200`):

```
naive (no select_related):   201 queries
optimized (select_related):    1 query
```

Run the benchmark:

```bash
python manage.py benchmark_queries --tasks 200
```

The N+1 regression test is in `tests/test_n1.py` — it proves query count is **constant** whether there are 5 or 55 tasks.

### Caching Strategy

Project list responses are cached per-organization in Redis (key: `projects:org:<org_id>`, TTL 5 min). Cache is invalidated on any Project create, update, or delete via overridden `perform_create/update/destroy` methods. In test mode the `locmem` backend is used — no Redis required.

`tests/test_caching.py` proves: first request populates the cache, second request hits the cache (fewer DB queries), and any write (create/update/delete) invalidates the entry.

### Optimistic Concurrency (409 Conflict)

Tasks carry a `version` field (integer, default 0). Every successful update increments it.

To update a task safely:
1. Read the task — note the `version` value.
2. Send `PATCH /api/v1/tasks/{id}/` with the header `If-Match: <version>`.
3. If the server's version matches, the update succeeds and `version` increments.
4. If another client updated first, you receive **HTTP 409 Conflict** — fetch the latest and retry.

```bash
# Read task (note version field)
curl -s http://localhost:8000/api/v1/tasks/$TASK_ID/ \
  -H "Authorization: Bearer $TOKEN" | jq '{version, title}'

# Update with If-Match version check
curl -s -X PATCH http://localhost:8000/api/v1/tasks/$TASK_ID/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "If-Match: 0" \
  -d '{"title":"Updated title"}' | jq .
```

Omitting `If-Match` skips the version check (backward-compatible — version still increments).

### Idempotency Key

To prevent duplicate tasks when retrying a timed-out POST:

```bash
curl -s -X POST http://localhost:8000/api/v1/tasks/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: my-unique-request-id-v1" \
  -d "{\"project\":\"$PROJECT_ID\",\"title\":\"Design homepage\",\"status\":\"TODO\"}"
```

A retry with the same `Idempotency-Key` returns **HTTP 200** with the original task — no duplicate is created. Keys are scoped per organization and stored in the `IdempotencyKey` table.

### Celery Retry / Backoff

`generate_project_report` retries up to 3 times on any exception, with exponential backoff (max 60 s between retries). It is idempotent: calling it a second time on a `READY` report is a no-op.

### Celery Beat — Nightly Purge

A nightly Celery Beat job (`purge_old_reports`, runs at 02:00 UTC) deletes `Report` rows older than 30 days. `start.sh` launches beat automatically alongside the worker. To run beat manually:

```bash
celery -A celery_app beat --loglevel=info
```

### Load Test Results

Measured with k6 (ramp to 25 VUs) against the full stack (web + Postgres +
Redis) in Docker on a development laptop, over a mix of `GET /projects/`,
`GET /tasks/`, and `POST /tasks/`. Throttling was raised via `THROTTLE_USER`
for the capacity run (production defaults are `1000/hour` per user,
`60/hour` anon — see below).

| Metric | Value |
|--------|-------|
| Requests served | 3,236 |
| p95 latency | 19.6 ms |
| Median latency | 9.5 ms |
| Error rate | 0.00% |

Note: with the production throttle in place, a single user exceeding
1,000 requests/hour correctly receives `429 Too Many Requests` — the load
above was run with the throttle relaxed to measure raw request-handling
capacity, not the throttle ceiling.

```bash
BASE_URL=http://localhost:8000 TOKEN=$TOKEN k6 run loadtest/load-test.js
```
