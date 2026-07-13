"""P9.5 Turkish-first and baseline accessibility rendering checks."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.catalog.models import AIProject
from apps.identity.roles import Role
from apps.tenancy.models import Organization, OrganizationMembership

User = get_user_model()


def _operator() -> Any:
    organization = Organization.objects.create(slug="org-a", name="A")
    user = User.objects.create_user("operator", password="x")  # noqa: S106
    OrganizationMembership.objects.create(
        organization=organization,
        user=user,
        role=Role.ORGANIZATION_ADMIN,
    )
    return user


@pytest.mark.django_db
def test_authenticated_shell_has_keyboard_and_semantic_landmarks(client: Client) -> None:
    user = _operator()
    client.force_login(user)

    body = client.get(reverse("console:dashboard")).content.decode()

    assert '<html lang="tr">' in body
    assert 'class="skip-link" href="#main-content"' in body
    assert '<main id="main-content" tabindex="-1">' in body
    assert ":focus-visible" in body
    assert "prefers-reduced-motion" in body
    assert "Genel bakış" in body
    assert "Sprint 1" not in body

    organization = OrganizationMembership.objects.get(user=user).organization
    AIProject.objects.create(organization=organization, slug="alpha", name="Alpha")
    table_body = client.get(reverse("console:projects")).content.decode()
    assert 'class="table-scroll"' in table_body
    assert '<caption class="sr-only">AI projeleri tablosu</caption>' in table_body


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("route", "heading", "empty_state", "caption"),
    [
        ("console:projects", "AI projeleri", "Yetki kapsamınızda kayıt yok", "tablosu"),
        (
            "console:releases",
            "Release&#x27;ler",
            "Yetki kapsamınızda release yok",
            "release'ler",
        ),
        (
            "console:agent_runs",
            "Agent çalıştırmaları",
            "Yetki kapsamınızda agent çalıştırması yok",
            "Agent çalıştırmaları",
        ),
        (
            "console:tool_approvals",
            "Tool onayları",
            "Yetki kapsamınızda bekleyen tool onayı yok",
            "Bekleyen tool onayları",
        ),
    ],
)
def test_primary_empty_surfaces_are_turkish_and_named(
    client: Client, route: str, heading: str, empty_state: str, caption: str
) -> None:
    client.force_login(_operator())

    body = client.get(reverse(route)).content.decode()

    assert heading in body
    assert empty_state in body
    if "<table" in body:
        assert '<caption class="sr-only">' in body
        assert caption in body


@pytest.mark.django_db
def test_create_form_uses_turkish_action_and_accessible_login_labels(client: Client) -> None:
    root = User.objects.create_superuser("root", "root@example.com", "x")  # noqa: S106
    client.force_login(root)
    create_body = client.get(reverse("console:organization_create")).content.decode()
    assert "Yeni organizasyon" in create_body
    assert ">Oluştur</button>" in create_body

    client.logout()
    login_body = client.get(reverse("console:login")).content.decode()
    assert '<label for="id_username">' in login_body
    assert '<label for="id_password">' in login_body
    assert 'class="skip-link"' in login_body
