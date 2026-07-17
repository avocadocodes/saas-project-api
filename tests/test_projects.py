import pytest
from tests.conftest import get_tokens_for_user


@pytest.mark.django_db
def test_list_projects_scoped_to_org(client, owner_a, project_a, project_b):
    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")
    response = client.get(
        "/api/v1/projects/",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 200
    ids = [p["id"] for p in response.json()["results"]]
    assert str(project_a.id) in ids
    assert str(project_b.id) not in ids


@pytest.mark.django_db
def test_cross_tenant_project_access_returns_404(client, owner_a, project_b):
    """A user from org A cannot access org B's project - returns 404."""
    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")
    response = client.get(
        f"/api/v1/projects/{project_b.id}/",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_owner_can_delete_project(client, owner_a, project_a):
    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")
    response = client.delete(
        f"/api/v1/projects/{project_a.id}/",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 204


@pytest.mark.django_db
def test_member_cannot_delete_project(client, member_a, project_a):
    token = get_tokens_for_user(client, "member@alpha.com", "testpass123")
    response = client.delete(
        f"/api/v1/projects/{project_a.id}/",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_member_can_create_project(client, member_a, org_a):
    token = get_tokens_for_user(client, "member@alpha.com", "testpass123")
    response = client.post(
        "/api/v1/projects/",
        {"name": "New Project", "description": "Created by member"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 201
    assert response.json()["name"] == "New Project"


@pytest.mark.django_db
def test_unauthenticated_access_denied(client):
    response = client.get("/api/v1/projects/")
    assert response.status_code == 401
