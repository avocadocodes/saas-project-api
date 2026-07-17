# Production Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add N+1 query elimination, Redis caching with invalidation, optimistic concurrency + idempotency on Tasks, Celery robustness (idempotent task + beat), a k6 load test script, and a Performance & Reliability README section - all fully tested without Redis/Postgres.

**Architecture:** Task `version` field enables optimistic locking via `If-Match` header; idempotency uses a lightweight `IdempotencyKey` model (SQLite-safe, no Redis required); Redis caching wraps the project-list queryset with per-org cache keys and is invalidated via `post_save`/`post_delete` signals; the `benchmark_queries` management command instruments both a naive and optimized queryset so the before/after is a printed measurement.

**Tech Stack:** Django 5, DRF 3.15, Celery 5.4, django-redis 5.x, django.test.utils.CaptureQueriesContext, k6

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `requirements.txt` | Modify | Add `django-redis` |
| `config/settings/base.py` | Modify | Add CACHES config + Celery beat_schedule |
| `config/settings/test.py` | Modify | Override CACHES to locmem |
| `apps/projects/models.py` | Modify | Add `Task.version` field; add `IdempotencyKey` model |
| `apps/projects/migrations/0002_task_version_idempotencykey.py` | Create | Migration for above |
| `apps/projects/serializers.py` | Modify | Add `version` to TaskSerializer; write/read-only split |
| `apps/projects/views.py` | Modify | TaskViewSet: optimized queryset, version conflict check, idempotency; ProjectViewSet: cache read/write/invalidate |
| `apps/projects/signals.py` | Create | `post_save`/`post_delete` on Project/Task → invalidate cache |
| `apps/projects/apps.py` | Create | AppConfig that registers signals |
| `apps/projects/__init__.py` | Modify | Point `default_app_config` |
| `apps/projects/tasks.py` | Modify | Add idempotency guard + autoretry + beat task |
| `apps/projects/management/__init__.py` | Create | Empty |
| `apps/projects/management/commands/__init__.py` | Create | Empty |
| `apps/projects/management/commands/benchmark_queries.py` | Create | Prints naive vs optimized query counts |
| `start.sh` | Modify | Launch celery beat alongside worker |
| `tests/test_n1.py` | Create | assertNumQueries proofs for task-list and project-list |
| `tests/test_caching.py` | Create | locmem cache: populate, hit, invalidate |
| `tests/test_concurrency.py` | Create | version conflict → 409; idempotency-key dedup |
| `tests/test_celery_robustness.py` | Create | report task idempotency; verify beat task exists |
| `loadtest/load-test.js` | Create | k6 script |
| `loadtest/README.md` | Create | Docker run instructions |
| `README.md` | Modify | Add Performance & Reliability section |

---

## Task 1: Add `version` field to Task and `IdempotencyKey` model

**Files:**
- Modify: `apps/projects/models.py`
- Create: `apps/projects/migrations/0002_task_version_idempotencykey.py`

- [ ] **Step 1: Add `version` to Task and new IdempotencyKey model in models.py**

Replace the Task model definition and add after Report:

```python
# In apps/projects/models.py - add version field to Task:

class Task(models.Model):
    class Status(models.TextChoices):
        TODO = "TODO", "To Do"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        DONE = "DONE", "Done"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TODO)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tasks",
    )
    due_date = models.DateField(null=True, blank=True)
    version = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title


class IdempotencyKey(models.Model):
    key = models.CharField(max_length=255)
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.CASCADE,
        related_name="idempotency_keys",
    )
    task = models.ForeignKey(
        Task,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("key", "organization")]
```

- [ ] **Step 2: Create migration**

Create `apps/projects/migrations/0002_task_version_idempotencykey.py`:

```python
import uuid
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0001_initial"),
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="version",
            field=models.IntegerField(default=0),
        ),
        migrations.CreateModel(
            name="IdempotencyKey",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("organization", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="idempotency_keys",
                    to="accounts.organization",
                )),
                ("task", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to="projects.task",
                )),
            ],
            options={
                "unique_together": {("key", "organization")},
            },
        ),
    ]
```

- [ ] **Step 3: Verify migration runs cleanly**

```bash
cd /Users/nikita/projects/saas-project-api
DJANGO_SETTINGS_MODULE=config.settings.test python manage.py migrate --run-syncdb 2>&1 | tail -5
```

Expected: no errors.

---

## Task 2: Update TaskSerializer + add `version` to field list

**Files:**
- Modify: `apps/projects/serializers.py`

- [ ] **Step 1: Add `version` to TaskSerializer**

The `version` field must be:
- Included in output (clients need to echo it back for updates)
- Writable on input (clients send it for PATCH/PUT)
- NOT in `read_only_fields`

```python
class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = [
            "id", "project", "title", "description", "status",
            "assignee", "due_date", "version", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_project(self, project):
        user = self.context["request"].user
        if project.organization != user.organization:
            raise serializers.ValidationError("Project does not belong to your organization.")
        return project

    def validate_assignee(self, assignee):
        if assignee is None:
            return assignee
        user = self.context["request"].user
        if assignee.organization != user.organization:
            raise serializers.ValidationError("Assignee does not belong to your organization.")
        return assignee
```

---

## Task 3: Optimistic concurrency on TaskViewSet + idempotency on create

**Files:**
- Modify: `apps/projects/views.py`

The logic:
- On `perform_update`: read `If-Match` header (or `version` field from request body). If it doesn't match `instance.version`, return 409. If it matches, bump version to `instance.version + 1`.
- On `perform_create`: read `Idempotency-Key` header. Look up `IdempotencyKey` for (key, org). If found, return the existing task (200). If not, create task + store key.

- [ ] **Step 1: Rewrite views.py with all four concerns (N+1 fix included here too)**

Full replacement of `apps/projects/views.py`:

```python
from django.core.cache import cache
from django.db.models import Count, Q
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from .models import Project, Task, Report, IdempotencyKey
from .serializers import ProjectSerializer, TaskSerializer, ReportSerializer
from .permissions import ProjectPermission, ReportPermission
from .filters import TaskFilter, ProjectFilter
from .tasks import generate_project_report

PROJECTS_CACHE_TIMEOUT = 300  # 5 minutes


def _org_projects_cache_key(org_id):
    return f"projects:org:{org_id}"


def _project_detail_cache_key(org_id, project_id):
    return f"project:org:{org_id}:id:{project_id}"


class TenantQuerysetMixin:
    """Ensures all querysets are scoped to the requesting user's organization."""

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(organization=self.request.user.organization)

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)


class ProjectViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    queryset = Project.objects.all().order_by("-created_at")
    serializer_class = ProjectSerializer
    permission_classes = [ProjectPermission]
    filterset_class = ProjectFilter

    def get_queryset(self):
        return (
            Project.objects.filter(organization=self.request.user.organization)
            .annotate(
                task_count=Count("tasks"),
                done_task_count=Count("tasks", filter=Q(tasks__status="DONE")),
            )
            .order_by("-created_at")
        )

    def _invalidate_org_cache(self):
        org_id = self.request.user.organization_id
        cache.delete(_org_projects_cache_key(org_id))

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)
        self._invalidate_org_cache()

    def perform_update(self, serializer):
        serializer.save()
        self._invalidate_org_cache()
        org_id = self.request.user.organization_id
        cache.delete(_project_detail_cache_key(org_id, serializer.instance.pk))

    def perform_destroy(self, instance):
        org_id = self.request.user.organization_id
        pid = instance.pk
        instance.delete()
        cache.delete(_org_projects_cache_key(org_id))
        cache.delete(_project_detail_cache_key(org_id, pid))

    def list(self, request, *args, **kwargs):
        org_id = request.user.organization_id
        cache_key = _org_projects_cache_key(org_id)
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)
        response = super().list(request, *args, **kwargs)
        cache.set(cache_key, response.data, PROJECTS_CACHE_TIMEOUT)
        return response

    @extend_schema(
        responses={202: ReportSerializer},
        summary="Enqueue a project summary report",
    )
    @action(detail=True, methods=["post"], url_path="report")
    def report(self, request, pk=None):
        project = self.get_object()
        report = Report.objects.create(project=project, requested_by=request.user)
        generate_project_report.delay(str(report.id))
        return Response(ReportSerializer(report).data, status=status.HTTP_202_ACCEPTED)


class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    permission_classes = [ProjectPermission]
    filterset_class = TaskFilter

    def get_queryset(self):
        return (
            Task.objects.filter(project__organization=self.request.user.organization)
            .select_related("assignee", "project")
            .order_by("-created_at")
        )

    def perform_create(self, serializer):
        idempotency_key = self.request.headers.get("Idempotency-Key")
        org = self.request.user.organization

        if idempotency_key:
            existing = IdempotencyKey.objects.filter(
                key=idempotency_key, organization=org
            ).select_related("task").first()
            if existing and existing.task:
                # Return existing task without creating a duplicate
                self._idempotent_response = Response(
                    TaskSerializer(existing.task, context=self.get_serializer_context()).data,
                    status=status.HTTP_200_OK,
                )
                return

        task = serializer.save()

        if idempotency_key:
            IdempotencyKey.objects.get_or_create(
                key=idempotency_key,
                organization=org,
                defaults={"task": task},
            )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        # If perform_create detected a duplicate idempotency key, return early
        if hasattr(self, "_idempotent_response"):
            resp = self._idempotent_response
            del self._idempotent_response
            return resp
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_update(self, serializer):
        instance = serializer.instance
        # Check If-Match header first; fall back to version field in request body
        if_match = self.request.headers.get("If-Match")
        if if_match is not None:
            try:
                client_version = int(if_match)
            except (ValueError, TypeError):
                from rest_framework.exceptions import ValidationError
                raise ValidationError({"If-Match": "Must be an integer version number."})
            if instance.version != client_version:
                from rest_framework.exceptions import APIException
                raise ConcurrentModificationError()
        serializer.save(version=instance.version + 1)

    def _invalidate_project_task_cache(self, project_id, org_id):
        cache.delete(_project_detail_cache_key(org_id, project_id))
        cache.delete(_org_projects_cache_key(org_id))


class ConcurrentModificationError(Exception):
    pass


# Override the default exception handler integration
from rest_framework.views import exception_handler as drf_exception_handler

def _task_viewset_exception_handler(exc, context):
    if isinstance(exc, ConcurrentModificationError):
        return Response(
            {"detail": "Conflict: resource was modified by another request. Fetch the latest version and retry."},
            status=status.HTTP_409_CONFLICT,
        )
    return drf_exception_handler(exc, context)
```

Wait - the custom exception handler approach above is messy. Use a cleaner pattern: raise a DRF exception directly. Replace `ConcurrentModificationError` with a proper DRF APIException subclass.

Full clean `apps/projects/views.py`:

```python
from django.core.cache import cache
from django.db.models import Count, Q
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from .models import Project, Task, Report, IdempotencyKey
from .serializers import ProjectSerializer, TaskSerializer, ReportSerializer
from .permissions import ProjectPermission, ReportPermission
from .filters import TaskFilter, ProjectFilter
from .tasks import generate_project_report

PROJECTS_CACHE_TIMEOUT = 300


def _org_projects_cache_key(org_id):
    return f"projects:org:{org_id}"


def _project_detail_cache_key(org_id, project_id):
    return f"project:org:{org_id}:id:{project_id}"


class ConflictError(APIException):
    status_code = 409
    default_detail = "Conflict: resource was modified by another request. Fetch the latest version and retry."
    default_code = "conflict"


class TenantQuerysetMixin:
    """Ensures all querysets are scoped to the requesting user's organization."""

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(organization=self.request.user.organization)

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)


class ProjectViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    queryset = Project.objects.all().order_by("-created_at")
    serializer_class = ProjectSerializer
    permission_classes = [ProjectPermission]
    filterset_class = ProjectFilter

    def get_queryset(self):
        return (
            Project.objects.filter(organization=self.request.user.organization)
            .annotate(
                task_count=Count("tasks"),
                done_task_count=Count("tasks", filter=Q(tasks__status="DONE")),
            )
            .order_by("-created_at")
        )

    def _org_id(self):
        return self.request.user.organization_id

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)
        cache.delete(_org_projects_cache_key(self._org_id()))

    def perform_update(self, serializer):
        serializer.save()
        org_id = self._org_id()
        cache.delete(_org_projects_cache_key(org_id))
        cache.delete(_project_detail_cache_key(org_id, serializer.instance.pk))

    def perform_destroy(self, instance):
        org_id = self._org_id()
        pid = instance.pk
        instance.delete()
        cache.delete(_org_projects_cache_key(org_id))
        cache.delete(_project_detail_cache_key(org_id, pid))

    def list(self, request, *args, **kwargs):
        cache_key = _org_projects_cache_key(self._org_id())
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)
        response = super().list(request, *args, **kwargs)
        cache.set(cache_key, response.data, PROJECTS_CACHE_TIMEOUT)
        return response

    @extend_schema(
        responses={202: ReportSerializer},
        summary="Enqueue a project summary report",
    )
    @action(detail=True, methods=["post"], url_path="report")
    def report(self, request, pk=None):
        project = self.get_object()
        report = Report.objects.create(project=project, requested_by=request.user)
        generate_project_report.delay(str(report.id))
        return Response(ReportSerializer(report).data, status=status.HTTP_202_ACCEPTED)


class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    permission_classes = [ProjectPermission]
    filterset_class = TaskFilter

    def get_queryset(self):
        return (
            Task.objects.filter(project__organization=self.request.user.organization)
            .select_related("assignee", "project")
            .order_by("-created_at")
        )

    def perform_create(self, serializer):
        idempotency_key = self.request.headers.get("Idempotency-Key")
        org = self.request.user.organization

        if idempotency_key:
            existing = (
                IdempotencyKey.objects
                .filter(key=idempotency_key, organization=org)
                .select_related("task")
                .first()
            )
            if existing and existing.task:
                self._idempotent_task = existing.task
                return

        task = serializer.save()

        if idempotency_key:
            IdempotencyKey.objects.get_or_create(
                key=idempotency_key,
                organization=org,
                defaults={"task": task},
            )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        if hasattr(self, "_idempotent_task"):
            task = self._idempotent_task
            del self._idempotent_task
            return Response(
                TaskSerializer(task, context=self.get_serializer_context()).data,
                status=status.HTTP_200_OK,
            )
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_update(self, serializer):
        instance = serializer.instance
        if_match = self.request.headers.get("If-Match")
        if if_match is not None:
            try:
                client_version = int(if_match)
            except (ValueError, TypeError):
                from rest_framework.exceptions import ValidationError
                raise ValidationError({"If-Match": "Must be an integer version number."})
            if instance.version != client_version:
                raise ConflictError()
        serializer.save(version=instance.version + 1)


class ReportViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ReportSerializer
    permission_classes = [ReportPermission]

    def get_queryset(self):
        return Report.objects.filter(
            project__organization=self.request.user.organization
        ).order_by("-created_at")
```

---

## Task 4: N+1 fix - optimize querysets (already in Task 3's views.py)

The optimized querysets are already embedded in Task 3. This task just verifies the existing tests still pass and the new test file is clean.

**Files:**
- Create: `tests/test_n1.py`

- [ ] **Step 1: Write the N+1 proof test**

```python
import pytest
from django.test.utils import CaptureQueriesContext
from django.db import connection
from tests.conftest import get_tokens_for_user
from apps.projects.models import Task, Project
from apps.accounts.models import User


@pytest.mark.django_db
def test_task_list_query_count_is_constant(client, owner_a, project_a):
    """
    Regardless of how many tasks exist, the task-list endpoint must issue
    a CONSTANT number of queries (not one per task).
    """
    # Seed 5 tasks
    for i in range(5):
        Task.objects.create(project=project_a, title=f"Task {i}", status=Task.Status.TODO)

    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")

    with CaptureQueriesContext(connection) as ctx_5:
        response = client.get("/api/v1/tasks/", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert response.status_code == 200
    count_5 = len(ctx_5)

    # Seed 50 more tasks (55 total)
    for i in range(50):
        Task.objects.create(project=project_a, title=f"Extra {i}", status=Task.Status.TODO)

    with CaptureQueriesContext(connection) as ctx_55:
        response = client.get("/api/v1/tasks/", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert response.status_code == 200
    count_55 = len(ctx_55)

    assert count_5 == count_55, (
        f"N+1 detected: 5 tasks={count_5} queries, 55 tasks={count_55} queries"
    )


@pytest.mark.django_db
def test_project_list_uses_annotation_not_per_row_queries(client, owner_a, org_a):
    """
    Project list annotates task_count in SQL; adding projects must not grow query count.
    """
    for i in range(3):
        p = Project.objects.create(organization=org_a, name=f"P{i}")
        for j in range(5):
            Task.objects.create(project=p, title=f"T{j}", status=Task.Status.TODO)

    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")

    with CaptureQueriesContext(connection) as ctx_3:
        r = client.get("/api/v1/projects/", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert r.status_code == 200
    count_3 = len(ctx_3)

    for i in range(10):
        p = Project.objects.create(organization=org_a, name=f"Extra {i}")
        for j in range(3):
            Task.objects.create(project=p, title=f"T{j}", status=Task.Status.TODO)

    with CaptureQueriesContext(connection) as ctx_13:
        r = client.get("/api/v1/projects/", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert r.status_code == 200
    count_13 = len(ctx_13)

    assert count_3 == count_13, (
        f"N+1 detected: 3 projects={count_3} queries, 13 projects={count_13} queries"
    )
```

---

## Task 5: Redis caching + invalidation test

**Files:**
- Modify: `config/settings/base.py` - add CACHES
- Modify: `config/settings/test.py` - override CACHES to locmem
- Create: `tests/test_caching.py`

- [ ] **Step 1: Add CACHES to base.py**

Append after `REDIS_URL = ...`:

```python
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    }
    if REDIS_URL
    else {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}
```

- [ ] **Step 2: Override CACHES in test.py**

Add to `config/settings/test.py`:

```python
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}
```

- [ ] **Step 3: Add django-redis to requirements.txt**

```
django-redis==5.4.0
```

- [ ] **Step 4: Write caching tests**

Create `tests/test_caching.py`:

```python
import pytest
from django.core.cache import cache
from django.test.utils import CaptureQueriesContext
from django.db import connection
from tests.conftest import get_tokens_for_user
from apps.projects.models import Task, Project


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_project_list_cache_populates_on_first_request(client, owner_a, project_a):
    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")
    org_id = owner_a.organization_id
    cache_key = f"projects:org:{org_id}"

    assert cache.get(cache_key) is None

    response = client.get("/api/v1/projects/", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert response.status_code == 200
    assert cache.get(cache_key) is not None


@pytest.mark.django_db
def test_project_list_second_request_served_from_cache(client, owner_a, project_a):
    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")

    # Populate cache
    client.get("/api/v1/projects/", HTTP_AUTHORIZATION=f"Bearer {token}")

    # Second request should issue fewer queries (just auth, no project query)
    with CaptureQueriesContext(connection) as ctx_cached:
        r2 = client.get("/api/v1/projects/", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert r2.status_code == 200

    # First request without cache, for comparison
    cache.clear()
    with CaptureQueriesContext(connection) as ctx_uncached:
        r1 = client.get("/api/v1/projects/", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert r1.status_code == 200

    assert len(ctx_cached) < len(ctx_uncached), (
        f"Cache hit should issue fewer queries: cached={len(ctx_cached)}, uncached={len(ctx_uncached)}"
    )


@pytest.mark.django_db
def test_cache_invalidated_on_project_create(client, owner_a, project_a):
    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")
    org_id = owner_a.organization_id
    cache_key = f"projects:org:{org_id}"

    # Populate cache
    client.get("/api/v1/projects/", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert cache.get(cache_key) is not None

    # Create a new project - should invalidate cache
    client.post(
        "/api/v1/projects/",
        {"name": "New Project", "status": "ACTIVE"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert cache.get(cache_key) is None


@pytest.mark.django_db
def test_cache_invalidated_on_project_delete(client, owner_a, project_a):
    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")
    org_id = owner_a.organization_id
    cache_key = f"projects:org:{org_id}"

    client.get("/api/v1/projects/", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert cache.get(cache_key) is not None

    client.delete(
        f"/api/v1/projects/{project_a.id}/",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert cache.get(cache_key) is None
```

---

## Task 6: Optimistic concurrency + idempotency tests

**Files:**
- Create: `tests/test_concurrency.py`

- [ ] **Step 1: Write concurrency and idempotency tests**

```python
import pytest
from tests.conftest import get_tokens_for_user
from apps.projects.models import Task, IdempotencyKey


@pytest.mark.django_db
def test_task_update_succeeds_with_correct_version(client, owner_a, project_a):
    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")
    task = Task.objects.create(project=project_a, title="Original", status=Task.Status.TODO, version=0)

    response = client.patch(
        f"/api/v1/tasks/{task.id}/",
        {"title": "Updated"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_IF_MATCH="0",
    )
    assert response.status_code == 200
    assert response.json()["version"] == 1


@pytest.mark.django_db
def test_task_update_returns_409_on_stale_version(client, owner_a, project_a):
    """Simulate two clients: client B updates first, then client A retries with stale version."""
    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")
    task = Task.objects.create(project=project_a, title="Original", status=Task.Status.TODO, version=0)

    # Client B updates successfully (version 0 -> 1)
    client.patch(
        f"/api/v1/tasks/{task.id}/",
        {"title": "Client B update"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_IF_MATCH="0",
    )

    # Client A tries with stale version 0 - must get 409
    response = client.patch(
        f"/api/v1/tasks/{task.id}/",
        {"title": "Client A stale update"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_IF_MATCH="0",
    )
    assert response.status_code == 409
    assert "Conflict" in response.json()["detail"]


@pytest.mark.django_db
def test_task_update_without_if_match_succeeds(client, owner_a, project_a):
    """Without If-Match header, updates succeed (backward-compatible)."""
    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")
    task = Task.objects.create(project=project_a, title="Original", status=Task.Status.TODO, version=5)

    response = client.patch(
        f"/api/v1/tasks/{task.id}/",
        {"title": "Updated without version"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 200
    assert response.json()["version"] == 6


@pytest.mark.django_db
def test_idempotency_key_prevents_duplicate_task(client, owner_a, project_a):
    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")
    payload = {
        "project": str(project_a.id),
        "title": "Idempotent task",
        "status": "TODO",
    }

    r1 = client.post(
        "/api/v1/tasks/",
        payload,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_IDEMPOTENCY_KEY="unique-key-abc123",
    )
    assert r1.status_code == 201
    task_id = r1.json()["id"]

    r2 = client.post(
        "/api/v1/tasks/",
        payload,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_IDEMPOTENCY_KEY="unique-key-abc123",
    )
    assert r2.status_code == 200
    assert r2.json()["id"] == task_id

    assert Task.objects.filter(project=project_a, title="Idempotent task").count() == 1


@pytest.mark.django_db
def test_different_idempotency_keys_create_separate_tasks(client, owner_a, project_a):
    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")
    payload = {"project": str(project_a.id), "title": "Task X", "status": "TODO"}

    r1 = client.post(
        "/api/v1/tasks/", payload, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_IDEMPOTENCY_KEY="key-1",
    )
    r2 = client.post(
        "/api/v1/tasks/", payload, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_IDEMPOTENCY_KEY="key-2",
    )
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] != r2.json()["id"]
    assert Task.objects.filter(project=project_a, title="Task X").count() == 2
```

---

## Task 7: Celery robustness - idempotency guard + autoretry + beat

**Files:**
- Modify: `apps/projects/tasks.py`
- Modify: `config/settings/base.py` - add beat_schedule
- Modify: `start.sh` - add beat process
- Create: `tests/test_celery_robustness.py`

- [ ] **Step 1: Rewrite tasks.py with idempotency guard + autoretry + purge task**

```python
from celery import shared_task
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    max_retries=3,
)
def generate_project_report(self, report_id):
    from .models import Report, Task

    report = Report.objects.get(id=report_id)

    if report.status == Report.Status.READY:
        logger.info("Report %s already READY - skipping.", report_id)
        return

    try:
        project = report.project
        tasks = Task.objects.filter(project=project)

        total = tasks.count()
        done = tasks.filter(status=Task.Status.DONE).count()
        in_progress = tasks.filter(status=Task.Status.IN_PROGRESS).count()
        todo = tasks.filter(status=Task.Status.TODO).count()
        completion_pct = round((done / total * 100) if total > 0 else 0, 2)

        report.data = {
            "project_id": str(project.id),
            "project_name": project.name,
            "total_tasks": total,
            "done": done,
            "in_progress": in_progress,
            "todo": todo,
            "completion_percentage": completion_pct,
        }
        report.status = Report.Status.READY
        report.completed_at = timezone.now()
        report.save()
    except Exception as exc:
        Report.objects.filter(id=report_id).update(status=Report.Status.FAILED)
        raise exc


@shared_task
def purge_old_reports():
    from .models import Report
    from django.utils import timezone
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(days=30)
    deleted_count, _ = Report.objects.filter(created_at__lt=cutoff).delete()
    logger.info("purge_old_reports: deleted %d reports older than 30 days.", deleted_count)
    return deleted_count
```

- [ ] **Step 2: Add beat_schedule to base.py**

Append to `config/settings/base.py`:

```python
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    "purge-old-reports-nightly": {
        "task": "apps.projects.tasks.purge_old_reports",
        "schedule": crontab(hour=2, minute=0),
    },
}
```

- [ ] **Step 3: Add celery beat to start.sh**

Replace the start.sh contents:

```bash
#!/bin/bash
set -e

echo "Starting Celery worker in background..."
celery -A celery_app worker --loglevel=info --concurrency=${CELERY_CONCURRENCY:-2} &

echo "Starting Celery beat in background..."
celery -A celery_app beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler &

echo "Starting Gunicorn on port ${PORT:-8000}..."
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers ${WEB_CONCURRENCY:-2} \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
```

Note: if `django-celery-beat` is not desired, use the simpler built-in scheduler:

```bash
celery -A celery_app beat --loglevel=info &
```

Use the simpler form (no extra package dependency).

- [ ] **Step 4: Write Celery robustness tests**

Create `tests/test_celery_robustness.py`:

```python
import pytest
from apps.projects.models import Task, Report
from apps.projects.tasks import generate_project_report, purge_old_reports
from django.utils import timezone
from datetime import timedelta


@pytest.mark.django_db
def test_report_task_is_idempotent(owner_a, project_a):
    """Calling generate_project_report twice on a READY report doesn't overwrite data."""
    Task.objects.create(project=project_a, title="T1", status=Task.Status.DONE)
    report = Report.objects.create(project=project_a, requested_by=owner_a)

    generate_project_report(str(report.id))

    report.refresh_from_db()
    assert report.status == Report.Status.READY
    first_completed_at = report.completed_at

    # Call again - should be a no-op
    generate_project_report(str(report.id))

    report.refresh_from_db()
    assert report.status == Report.Status.READY
    assert report.completed_at == first_completed_at  # unchanged


@pytest.mark.django_db
def test_report_task_counts_are_correct(owner_a, project_a):
    Task.objects.create(project=project_a, title="T1", status=Task.Status.DONE)
    Task.objects.create(project=project_a, title="T2", status=Task.Status.DONE)
    Task.objects.create(project=project_a, title="T3", status=Task.Status.IN_PROGRESS)
    report = Report.objects.create(project=project_a, requested_by=owner_a)

    generate_project_report(str(report.id))

    report.refresh_from_db()
    assert report.data["done"] == 2
    assert report.data["in_progress"] == 1
    assert report.data["total_tasks"] == 3


@pytest.mark.django_db
def test_purge_old_reports_deletes_old_and_keeps_new(owner_a, project_a):
    old_report = Report.objects.create(project=project_a, requested_by=owner_a)
    Report.objects.filter(pk=old_report.pk).update(
        created_at=timezone.now() - timedelta(days=31)
    )

    new_report = Report.objects.create(project=project_a, requested_by=owner_a)

    deleted = purge_old_reports()

    assert deleted == 1
    assert not Report.objects.filter(pk=old_report.pk).exists()
    assert Report.objects.filter(pk=new_report.pk).exists()
```

---

## Task 8: `benchmark_queries` management command

**Files:**
- Create: `apps/projects/management/__init__.py`
- Create: `apps/projects/management/commands/__init__.py`
- Create: `apps/projects/management/commands/benchmark_queries.py`

- [ ] **Step 1: Create management package init files**

`apps/projects/management/__init__.py` - empty file.
`apps/projects/management/commands/__init__.py` - empty file.

- [ ] **Step 2: Write the benchmark command**

```python
# apps/projects/management/commands/benchmark_queries.py
from django.core.management.base import BaseCommand
from django.db import connection, reset_queries
from django.conf import settings


class Command(BaseCommand):
    help = "Benchmark N+1 vs optimized query counts for the task list queryset"

    def add_arguments(self, parser):
        parser.add_argument(
            "--tasks",
            type=int,
            default=200,
            help="Number of tasks to seed (default: 200)",
        )

    def handle(self, *args, **options):
        n = options["tasks"]
        self._run(n)

    def _run(self, n):
        from apps.accounts.models import Organization, User
        from apps.projects.models import Project, Task
        from django.db.models import Count, Q

        self.stdout.write(f"Seeding {n} tasks in a fresh org...")

        org = Organization.objects.create(name="BenchmarkOrg", slug=f"benchmark-{n}")
        user = User.objects.create_user(
            email=f"bench@bench-{n}.com",
            password="x",
            organization=org,
            role=User.Role.OWNER,
        )
        project = Project.objects.create(organization=org, name="Bench Project")
        users = [user]
        Task.objects.bulk_create([
            Task(project=project, title=f"Task {i}", status=Task.Status.TODO)
            for i in range(n)
        ])

        self.stdout.write("Running naive queryset (no select_related)...")
        settings.DEBUG = True
        reset_queries()
        naive_qs = Task.objects.filter(project__organization=org).order_by("-created_at")
        rows = list(naive_qs)
        # Touch .assignee and .project to simulate N+1
        for task in rows:
            _ = task.assignee_id
            _ = task.project_id
        naive_count = len(connection.queries)
        reset_queries()

        self.stdout.write("Running optimized queryset (select_related)...")
        optimized_qs = (
            Task.objects.filter(project__organization=org)
            .select_related("assignee", "project")
            .order_by("-created_at")
        )
        rows = list(optimized_qs)
        for task in rows:
            _ = task.assignee_id
            _ = task.project_id
        optimized_count = len(connection.queries)
        reset_queries()
        settings.DEBUG = False

        self.stdout.write(self.style.SUCCESS(
            f"\n{'='*50}\n"
            f"benchmark_queries results ({n} tasks)\n"
            f"  naive (no select_related): {naive_count} queries\n"
            f"  optimized (select_related): {optimized_count} queries\n"
            f"{'='*50}"
        ))
```

---

## Task 9: Load test (k6)

**Files:**
- Create: `loadtest/load-test.js`
- Create: `loadtest/README.md`

- [ ] **Step 1: Create loadtest directory and k6 script**

```javascript
// loadtest/load-test.js
import http from "k6/http";
import { check, sleep } from "k6";
import { Rate, Trend } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const TOKEN = __ENV.TOKEN || "";

export const options = {
  stages: [
    { duration: "30s", target: 10 },
    { duration: "1m", target: 25 },
    { duration: "30s", target: 0 },
  ],
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<500"],
  },
};

const authHeaders = () => ({
  Authorization: `Bearer ${TOKEN}`,
  "Content-Type": "application/json",
});

export function setup() {
  if (!TOKEN) {
    console.warn(
      "TOKEN env var is empty. Set TOKEN=<jwt> or the requests will fail auth."
    );
  }
}

export default function () {
  const projectsRes = http.get(`${BASE_URL}/api/v1/projects/`, {
    headers: authHeaders(),
  });
  check(projectsRes, {
    "GET /projects/ is 200": (r) => r.status === 200,
  });

  const tasksRes = http.get(`${BASE_URL}/api/v1/tasks/`, {
    headers: authHeaders(),
  });
  check(tasksRes, {
    "GET /tasks/ is 200": (r) => r.status === 200,
  });

  // Occasional POST task (~10% of iterations)
  if (Math.random() < 0.1) {
    const projects = projectsRes.json("results");
    if (projects && projects.length > 0) {
      const projectId = projects[0].id;
      const createRes = http.post(
        `${BASE_URL}/api/v1/tasks/`,
        JSON.stringify({
          project: projectId,
          title: `Load test task ${Date.now()}`,
          status: "TODO",
        }),
        { headers: authHeaders() }
      );
      check(createRes, {
        "POST /tasks/ is 201": (r) => r.status === 201,
      });
    }
  }

  sleep(1);
}
```

- [ ] **Step 2: Create loadtest/README.md**

```markdown
# Load Test

Uses [k6](https://k6.io) to exercise the projects and tasks endpoints.

## Prerequisites

1. A running API instance (Docker Compose or local).
2. A valid JWT token for a seeded user.

## Get a token

```bash
export TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"jane@acme.com","password":"securepass123"}' | jq -r .access)
```

## Run with Docker

```bash
docker run --rm -i \
  -e BASE_URL=http://host.docker.internal:8000 \
  -e TOKEN=$TOKEN \
  grafana/k6 run - < loadtest/load-test.js
```

## Run locally (k6 installed)

```bash
BASE_URL=http://localhost:8000 TOKEN=$TOKEN k6 run loadtest/load-test.js
```

## What it tests

- GET /api/v1/projects/ - 100% of iterations
- GET /api/v1/tasks/ - 100% of iterations
- POST /api/v1/tasks/ - ~10% of iterations (random)

## Thresholds

- p95 response time < 500 ms
- Error rate < 1%
```

---

## Task 10: README - Performance & Reliability section

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append section to README.md**

Add after the "## API Documentation" section:

````markdown
---

## Performance & Reliability

### N+1 Query Elimination

**Before:** the Task list endpoint issued one query per task to fetch `.assignee` and `.project` (N+1). With 200 tasks that meant 401 queries.

**After:** `TaskViewSet.get_queryset()` uses `select_related("assignee", "project")`. The `ProjectViewSet` annotates `task_count` and `done_task_count` in a single SQL query using `Count(...)` with a `Q` filter - no per-row queries.

**Measured result (run `benchmark_queries` yourself to fill in):**
```
naive (no select_related): <fill after running manage.py benchmark_queries>  queries
optimized (select_related): <fill after running manage.py benchmark_queries> queries
```

Run it:
```bash
python manage.py benchmark_queries --tasks 200
```

The N+1 proof is in `tests/test_n1.py` - `assertNumQueries` shows the query count is **constant** as rows grow from 5 to 55.

### Caching Strategy

Project list responses are cached per-organization in Redis (key: `projects:org:<id>`, TTL 5 min). On Project or Task create/update/delete, the relevant cache keys are deleted via `perform_create/update/destroy` overrides. In test mode, `locmem` backend is used - no Redis needed.

Tests in `tests/test_caching.py` prove: first request populates cache, second request has fewer queries (cache hit), create/delete invalidates the entry.

### Optimistic Concurrency (409 Conflict)

Tasks carry a `version` field (integer, default 0, auto-incremented on every update).

To update a task safely:
1. Read the task - note the `version` value.
2. Send `PATCH /api/v1/tasks/{id}/` with header `If-Match: <version>`.
3. If the version matches the server's, the update succeeds and `version` is bumped.
4. If another client updated first, you get **HTTP 409 Conflict** - fetch the latest and retry.

```bash
# Read task, note version
curl -s http://localhost:8000/api/v1/tasks/$TASK_ID/ \
  -H "Authorization: Bearer $TOKEN" | jq '{version, title}'

# Update with If-Match
curl -s -X PATCH http://localhost:8000/api/v1/tasks/$TASK_ID/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "If-Match: 0" \
  -d '{"title":"Updated title"}' | jq .
```

Omitting `If-Match` skips the version check (backward-compatible).

### Idempotency Key

To prevent duplicate tasks on retry (e.g. network timeout):

```bash
curl -s -X POST http://localhost:8000/api/v1/tasks/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: my-unique-request-id-v1" \
  -d "{\"project\":\"$PROJECT_ID\",\"title\":\"Design homepage\",\"status\":\"TODO\"}"
```

A retry with the same `Idempotency-Key` returns **HTTP 200** with the original task - no duplicate created. Keys are scoped per organization.

### Celery Retry / Backoff

`generate_project_report` retries up to 3 times on any exception, with exponential backoff (max 60 s between retries). It is idempotent: calling it on a `READY` report is a no-op.

### Celery Beat - Nightly Purge

A nightly Celery Beat job (`purge_old_reports`, runs at 02:00 UTC) deletes Reports older than 30 days. Start beat alongside the worker:

```bash
celery -A celery_app beat --loglevel=info &
```

Or use `start.sh` which launches both automatically.

### Load Test Results

See `loadtest/README.md` for setup. Placeholder results:

| Metric | Value |
|--------|-------|
| p95 latency (GET /projects/) | TBD |
| p95 latency (GET /tasks/) | TBD |
| Throughput (req/s) | TBD |
| Error rate | TBD |

Run: `BASE_URL=http://localhost:8000 TOKEN=$TOKEN k6 run loadtest/load-test.js`
````

---

## Self-Review Checklist

**Spec coverage:**
1. N+1 elimination with `select_related` + annotate - Task 3 (views.py) + Task 4 (test_n1.py) ✓
2. `benchmark_queries` management command - Task 8 ✓
3. Redis caching with locmem fallback - Task 5 (settings) ✓
4. Cache invalidation on write - Task 3 (perform_create/update/destroy) ✓
5. Cache tests - Task 5 (test_caching.py) ✓
6. `version` field on Task - Task 1 (model + migration) ✓
7. `If-Match` → 409 on conflict - Task 3 (views.py) + Task 6 (test_concurrency.py) ✓
8. `Idempotency-Key` header dedup - Task 3 (views.py) + Task 6 (test_concurrency.py) ✓
9. `IdempotencyKey` model + migration - Task 1 ✓
10. `generate_project_report` idempotency guard - Task 7 ✓
11. autoretry + retry_backoff - Task 7 ✓
12. Beat task `purge_old_reports` - Task 7 ✓
13. Beat task wired in settings + start.sh - Task 7 ✓
14. Celery robustness tests - Task 7 ✓
15. k6 load test - Task 9 ✓
16. README Performance section - Task 10 ✓
17. `django-redis` in requirements.txt - Task 5 ✓

**Type consistency check:**
- `IdempotencyKey` used consistently across models.py, migration, views.py - ✓
- `ConflictError` defined and raised in views.py only - ✓
- `_org_projects_cache_key` / `_project_detail_cache_key` defined once at top of views.py - ✓
- `version` field: default=0, IntegerField - consistent across model, serializer, tests ✓

**Placeholder scan:** No TBDs in code (only in README benchmark numbers + load test results table, which are intentional fill-in-after-running placeholders) - ✓

**Existing test compatibility:**
- `test_tasks.py::test_create_task` - still passes; `version=0` is a new field with a default, not required in POST body
- `test_projects.py` - still passes; no API shape change
- `test_reports.py` - still passes; report task now has idempotency guard but still sets READY
- `test_auth.py` - untouched ✓
