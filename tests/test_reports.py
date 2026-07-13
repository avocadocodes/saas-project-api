import pytest
from tests.conftest import get_tokens_for_user
from apps.projects.models import Task, Report


@pytest.mark.django_db
def test_request_report_enqueues_and_completes(client, owner_a, project_a):
    Task.objects.create(project=project_a, title="T1", status=Task.Status.DONE)
    Task.objects.create(project=project_a, title="T2", status=Task.Status.DONE)
    Task.objects.create(project=project_a, title="T3", status=Task.Status.IN_PROGRESS)
    Task.objects.create(project=project_a, title="T4", status=Task.Status.TODO)

    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")
    response = client.post(
        f"/api/v1/projects/{project_a.id}/report/",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 202
    report_id = response.json()["id"]

    poll = client.get(
        f"/api/v1/reports/{report_id}/",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert poll.status_code == 200
    data = poll.json()
    assert data["status"] == "READY"
    assert data["data"]["total_tasks"] == 4
    assert data["data"]["done"] == 2
    assert data["data"]["in_progress"] == 1
    assert data["data"]["todo"] == 1
    assert data["data"]["completion_percentage"] == 50.0


@pytest.mark.django_db
def test_report_aggregate_empty_project(client, owner_a, project_a):
    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")
    response = client.post(
        f"/api/v1/projects/{project_a.id}/report/",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 202
    report_id = response.json()["id"]

    poll = client.get(
        f"/api/v1/reports/{report_id}/",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    data = poll.json()
    assert data["data"]["total_tasks"] == 0
    assert data["data"]["completion_percentage"] == 0.0


@pytest.mark.django_db
def test_cross_tenant_report_not_visible(client, owner_a, owner_b, project_b):
    report = Report.objects.create(project=project_b, requested_by=owner_b, status=Report.Status.READY)

    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")
    response = client.get(
        f"/api/v1/reports/{report.id}/",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 404
