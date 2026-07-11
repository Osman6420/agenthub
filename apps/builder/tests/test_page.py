"""The console builder page: login required, tenant-scoped mount config, CSRF cookie."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from apps.builder.tests.conftest import BuilderFixture

pytestmark = pytest.mark.django_db


def test_builder_page_requires_login(client: Client) -> None:
    response = client.get(reverse("console:builder"))
    assert response.status_code == 302
    assert "/console/login/" in response["Location"]


def test_builder_page_renders_scoped_orgs_and_sets_csrf_cookie(
    client: Client, bf: BuilderFixture
) -> None:
    client.force_login(bf.author)
    response = client.get(reverse("console:builder"))
    assert response.status_code == 200
    html = response.content.decode()
    assert "agenthub-builder-root" in html
    assert "b-org" in html  # the author's org appears in the mount config
    assert "b-other" not in html  # an org outside scope does not
    assert "csrftoken" in response.cookies  # SPA can obtain a CSRF token for writes


def test_builder_page_hosts_mount_point_for_outsider_scope(
    client: Client, bf: BuilderFixture
) -> None:
    client.force_login(bf.outsider)
    html = client.get(reverse("console:builder")).content.decode()
    assert "b-other" in html
    assert "b-org" not in html
