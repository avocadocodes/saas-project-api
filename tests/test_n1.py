import pytest
from django.core.cache import cache
from django.test.utils import CaptureQueriesContext
from django.db import connection
from tests.conftest import get_tokens_for_user
from apps.projects.models import Task, Project


@pytest.fixture(autouse=True)
def clear_cache_for_n1():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_task_list_query_count_is_constant(client, owner_a, project_a):
    """
    Regardless of how many tasks exist, the task-list endpoint must issue
    a CONSTANT number of queries (not one per task row).
    TaskViewSet is not cached, so no cache clearing needed here.
    """
    for i in range(5):
        Task.objects.create(project=project_a, title=f"Task {i}", status=Task.Status.TODO)

    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")

    with CaptureQueriesContext(connection) as ctx_5:
        response = client.get("/api/v1/tasks/", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert response.status_code == 200
    count_5 = len(ctx_5)

    # Add 50 more tasks (55 total, but only 20 fit on page 1)
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
    Project list annotates task_count in SQL; adding more projects must not grow query count.
    Both measurements bypass the cache so we always hit the DB.
    """
    for i in range(3):
        p = Project.objects.create(organization=org_a, name=f"P{i}")
        for j in range(5):
            Task.objects.create(project=p, title=f"T{j}", status=Task.Status.TODO)

    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")

    cache.clear()
    with CaptureQueriesContext(connection) as ctx_3:
        r = client.get("/api/v1/projects/", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert r.status_code == 200
    count_3 = len(ctx_3)

    for i in range(10):
        p = Project.objects.create(organization=org_a, name=f"Extra {i}")
        for j in range(3):
            Task.objects.create(project=p, title=f"T{j}", status=Task.Status.TODO)

    # Clear cache so the second measurement also hits the DB
    cache.clear()
    with CaptureQueriesContext(connection) as ctx_13:
        r = client.get("/api/v1/projects/", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert r.status_code == 200
    count_13 = len(ctx_13)

    assert count_3 == count_13, (
        f"N+1 detected: 3 projects={count_3} queries, 13 projects={count_13} queries"
    )
