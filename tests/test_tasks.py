import pytest
from tests.conftest import get_tokens_for_user
from apps.projects.models import Task


@pytest.mark.django_db
def test_create_task(client, owner_a, project_a):
    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")
    response = client.post(
        "/api/v1/tasks/",
        {
            "project": str(project_a.id),
            "title": "Implement feature X",
            "description": "Details here",
            "status": "TODO",
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 201
    assert response.json()["title"] == "Implement feature X"


@pytest.mark.django_db
def test_list_tasks_scoped_to_org(client, owner_a, owner_b, project_a, project_b):
    Task.objects.create(project=project_a, title="Task A", status=Task.Status.TODO)
    Task.objects.create(project=project_b, title="Task B", status=Task.Status.TODO)

    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")
    response = client.get(
        "/api/v1/tasks/",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 200
    titles = [t["title"] for t in response.json()["results"]]
    assert "Task A" in titles
    assert "Task B" not in titles


@pytest.mark.django_db
def test_filter_tasks_by_status(client, owner_a, project_a):
    Task.objects.create(project=project_a, title="Todo Task", status=Task.Status.TODO)
    Task.objects.create(project=project_a, title="Done Task", status=Task.Status.DONE)

    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")
    response = client.get(
        "/api/v1/tasks/?status=DONE",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 200
    titles = [t["title"] for t in response.json()["results"]]
    assert "Done Task" in titles
    assert "Todo Task" not in titles


@pytest.mark.django_db
def test_cross_tenant_task_not_visible(client, owner_a, project_b):
    Task.objects.create(project=project_b, title="Org B Task", status=Task.Status.TODO)

    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")
    response = client.get(
        "/api/v1/tasks/",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 200
    titles = [t["title"] for t in response.json()["results"]]
    assert "Org B Task" not in titles
