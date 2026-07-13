# SaaS Project Management API

A production-quality multi-tenant REST API for project and task management. Organizations are isolated tenants; users belong to an organization with a role (Owner, Admin, Member); heavy operations run asynchronously via Celery.

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
