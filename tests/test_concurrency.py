import pytest
from tests.conftest import get_tokens_for_user
from apps.projects.models import Task, IdempotencyKey


@pytest.mark.django_db
def test_task_update_succeeds_with_correct_version(client, owner_a, project_a):
    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")
    task = Task.objects.create(
        project=project_a, title="Original", status=Task.Status.TODO, version=0
    )

    response = client.patch(
        f"/api/v1/tasks/{task.id}/",
        {"title": "Updated"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_IF_MATCH="0",
    )
    assert response.status_code == 200
    assert response.json()["version"] == 1
    assert response.json()["title"] == "Updated"


@pytest.mark.django_db
def test_task_update_returns_409_on_stale_version(client, owner_a, project_a):
    """Client B updates first; client A retries with stale version and gets 409."""
    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")
    task = Task.objects.create(
        project=project_a, title="Original", status=Task.Status.TODO, version=0
    )

    # Client B updates successfully (version 0 -> 1)
    r_b = client.patch(
        f"/api/v1/tasks/{task.id}/",
        {"title": "Client B update"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_IF_MATCH="0",
    )
    assert r_b.status_code == 200

    # Client A tries with stale version 0 — must get 409
    r_a = client.patch(
        f"/api/v1/tasks/{task.id}/",
        {"title": "Client A stale update"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_IF_MATCH="0",
    )
    assert r_a.status_code == 409
    assert "Conflict" in r_a.json()["detail"]


@pytest.mark.django_db
def test_task_update_without_if_match_always_succeeds(client, owner_a, project_a):
    """Omitting If-Match header is backward-compatible — version still increments."""
    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")
    task = Task.objects.create(
        project=project_a, title="Original", status=Task.Status.TODO, version=5
    )

    response = client.patch(
        f"/api/v1/tasks/{task.id}/",
        {"title": "Updated without version check"},
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
        "/api/v1/tasks/",
        payload,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_IDEMPOTENCY_KEY="key-1",
    )
    r2 = client.post(
        "/api/v1/tasks/",
        payload,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_IDEMPOTENCY_KEY="key-2",
    )
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] != r2.json()["id"]
    assert Task.objects.filter(project=project_a, title="Task X").count() == 2


@pytest.mark.django_db
def test_no_idempotency_key_creates_normally(client, owner_a, project_a):
    """Without Idempotency-Key, each POST creates a new task."""
    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")
    payload = {"project": str(project_a.id), "title": "Repeated task", "status": "TODO"}

    r1 = client.post(
        "/api/v1/tasks/", payload, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    r2 = client.post(
        "/api/v1/tasks/", payload, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] != r2.json()["id"]
