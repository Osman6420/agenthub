from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from django.contrib.auth.models import User

from apps.documents import storage
from apps.identity.models import (
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
)
from apps.tenancy.models import Organization, OrganizationMembership


@pytest.fixture(autouse=True)
def _object_store(settings: Any) -> Iterator[None]:
    """Force the hermetic in-memory blob store and isolate it between tests.

    This holds under both ``config.settings.test`` and the ``config.settings.local``
    PostgreSQL gate, so document-plane tests never open a socket to a real object store.
    """
    settings.DOCUMENTS_OBJECT_STORE_BACKEND = "memory"
    storage.reset_in_memory_store()
    yield
    storage.reset_in_memory_store()


@dataclass
class DocFixture:
    org: Organization
    other_org: Organization
    admin: User  # organization_admin in ``org`` (author + purge)
    author: User  # scenario_editor in ``org`` (author, not purge)
    viewer: User  # auditor in ``org`` (read scope only)
    outsider: User  # scenario_editor in ``other_org`` only


@pytest.fixture
def df(db: object) -> DocFixture:
    org = Organization.objects.create(slug="d-org", name="Docs Org")
    other = Organization.objects.create(slug="d-other", name="Other Org")

    admin = User.objects.create_user("d-admin", password="x")  # noqa: S106
    admin_membership = OrganizationMembership.objects.create(organization=org, user=admin)
    OrganizationResponsibilityAssignment.objects.create(
        organization=org,
        membership=admin_membership,
        responsibility=OrganizationResponsibility.ADMINISTRATOR,
        assigned_by=admin,
    )
    author = User.objects.create_user("d-author", password="x")  # noqa: S106
    OrganizationMembership.objects.create(organization=org, user=author)
    viewer = User.objects.create_user("d-viewer", password="x")  # noqa: S106
    OrganizationMembership.objects.create(organization=org, user=viewer)
    outsider = User.objects.create_user("d-outsider", password="x")  # noqa: S106
    OrganizationMembership.objects.create(organization=other, user=outsider)
    return DocFixture(org, other, admin, author, viewer, outsider)
