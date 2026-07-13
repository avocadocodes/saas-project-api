import pytest
from django.core.cache import cache
from django.test.utils import CaptureQueriesContext
from django.db import connection
from tests.conftest import get_tokens_for_user
from apps.projects.models import Project


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

    # Second request should issue fewer DB queries (cache hit skips project query)
    with CaptureQueriesContext(connection) as ctx_cached:
        r2 = client.get("/api/v1/projects/", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert r2.status_code == 200

    # Measure uncached for comparison
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

    client.get("/api/v1/projects/", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert cache.get(cache_key) is not None

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


@pytest.mark.django_db
def test_cache_invalidated_on_project_update(client, owner_a, project_a):
    token = get_tokens_for_user(client, "owner@alpha.com", "testpass123")
    org_id = owner_a.organization_id
    cache_key = f"projects:org:{org_id}"

    client.get("/api/v1/projects/", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert cache.get(cache_key) is not None

    client.patch(
        f"/api/v1/projects/{project_a.id}/",
        {"name": "Renamed"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert cache.get(cache_key) is None
