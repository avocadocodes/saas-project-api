import pytest


@pytest.mark.django_db
def test_register_creates_org_and_owner(client):
    response = client.post(
        "/api/v1/auth/register",
        {
            "organization_name": "Acme Corp",
            "email": "admin@acme.com",
            "password": "securepass123",
            "first_name": "Jane",
            "last_name": "Doe",
        },
        content_type="application/json",
    )
    assert response.status_code == 201
    data = response.json()
    assert data["user"]["role"] == "OWNER"
    assert data["user"]["organization_name"] == "Acme Corp"
    assert "access" in data
    assert "refresh" in data


@pytest.mark.django_db
def test_register_duplicate_email_returns_400(client):
    payload = {
        "organization_name": "Acme Corp",
        "email": "admin@acme.com",
        "password": "securepass123",
    }
    client.post("/api/v1/auth/register", payload, content_type="application/json")
    response = client.post("/api/v1/auth/register", payload, content_type="application/json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_login_returns_tokens(client, owner_a):
    response = client.post(
        "/api/v1/auth/login",
        {"email": "owner@alpha.com", "password": "testpass123"},
        content_type="application/json",
    )
    assert response.status_code == 200
    assert "access" in response.json()
    assert "refresh" in response.json()


@pytest.mark.django_db
def test_login_wrong_password_returns_401(client, owner_a):
    response = client.post(
        "/api/v1/auth/login",
        {"email": "owner@alpha.com", "password": "wrongpassword"},
        content_type="application/json",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_token_refresh(client, owner_a):
    login = client.post(
        "/api/v1/auth/login",
        {"email": "owner@alpha.com", "password": "testpass123"},
        content_type="application/json",
    )
    refresh_token = login.json()["refresh"]
    response = client.post(
        "/api/v1/auth/refresh",
        {"refresh": refresh_token},
        content_type="application/json",
    )
    assert response.status_code == 200
    assert "access" in response.json()
