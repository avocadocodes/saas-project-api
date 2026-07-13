import pytest
from apps.accounts.models import Organization, User
from apps.projects.models import Project, Task


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org Alpha", slug="org-alpha")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org Beta", slug="org-beta")


@pytest.fixture
def owner_a(db, org_a):
    return User.objects.create_user(
        email="owner@alpha.com",
        password="testpass123",
        organization=org_a,
        role=User.Role.OWNER,
    )


@pytest.fixture
def member_a(db, org_a):
    return User.objects.create_user(
        email="member@alpha.com",
        password="testpass123",
        organization=org_a,
        role=User.Role.MEMBER,
    )


@pytest.fixture
def owner_b(db, org_b):
    return User.objects.create_user(
        email="owner@beta.com",
        password="testpass123",
        organization=org_b,
        role=User.Role.OWNER,
    )


@pytest.fixture
def project_a(db, org_a):
    return Project.objects.create(
        organization=org_a,
        name="Alpha Project",
        description="Test project for org A",
    )


@pytest.fixture
def project_b(db, org_b):
    return Project.objects.create(
        organization=org_b,
        name="Beta Project",
        description="Test project for org B",
    )


def get_tokens_for_user(client, email, password):
    response = client.post(
        "/api/v1/auth/login",
        {"email": email, "password": password},
        content_type="application/json",
    )
    return response.data["access"]
