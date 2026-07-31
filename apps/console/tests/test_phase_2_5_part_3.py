from __future__ import annotations

import re
from io import StringIO
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db.models import ProtectedError
from django.test import Client, override_settings
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.catalog.models import AIProject
from apps.catalog.services import create_console_project
from apps.identity import credentials
from apps.identity import tokens as token_module
from apps.identity.credentials import ConsumerSubjectAllocationError, create_console_consumer
from apps.identity.models import (
    Consumer,
    ConsumerProtocol,
    ConsumerStatus,
    ConsumerToken,
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
    ProjectResponsibility,
    ProjectResponsibilityAssignment,
    TokenStatus,
)
from apps.identity.roles import Role
from apps.identity.tokens import create_token, hash_token, resolve_consumer
from apps.tenancy.models import Organization, OrganizationMembership, OrganizationStatus

User = get_user_model()


def _member(
    username: str, organization: Organization, role: str = Role.ORGANIZATION_ADMIN
) -> tuple[Any, OrganizationMembership]:
    user = User.objects.create_user(username, password="x")  # noqa: S106
    membership = OrganizationMembership.objects.create(organization=organization, user=user)
    responsibility = {
        Role.ORGANIZATION_ADMIN: OrganizationResponsibility.ADMINISTRATOR,
        Role.AUDITOR: OrganizationResponsibility.AUDITOR,
    }.get(role)
    if responsibility is not None:
        OrganizationResponsibilityAssignment.objects.create(
            organization=organization,
            membership=membership,
            responsibility=responsibility,
            assigned_by=user,
        )
    return user, membership


def _consumer(organization: Organization, *, subject: str = "legacy-subject") -> Consumer:
    return Consumer.objects.create(
        organization=organization,
        subject=subject,
        name="İstemci",
        protocol=ConsumerProtocol.REST,
        status=ConsumerStatus.ACTIVE,
    )


@pytest.mark.django_db
def test_project_administration_is_an_explicit_protected_assignment() -> None:
    organization = Organization.objects.create(slug="org", name="Org")
    _admin, membership = _member("owner", organization, Role.PROJECT_OWNER)

    project = create_console_project(organization=organization, name="Proje")
    ProjectResponsibilityAssignment.objects.create(
        organization=organization,
        project=project,
        membership=membership,
        responsibility=ProjectResponsibility.ADMINISTRATOR,
        assigned_by=membership.user,
    )
    assert project.responsibility_assignments.get().membership == membership
    with pytest.raises(ProtectedError):
        membership.delete()


@pytest.mark.django_db
def test_project_service_rejects_removed_owner_field() -> None:
    organization = Organization.objects.create(slug="org", name="Org")
    other = Organization.objects.create(slug="other", name="Other")
    _foreign_user, foreign = _member("foreign", other, Role.PROJECT_OWNER)
    _auditor_user, auditor = _member("auditor", organization, Role.AUDITOR)

    with pytest.raises(TypeError):
        create_console_project(organization=organization, name="Yabancı", owner_membership=foreign)
    with pytest.raises(TypeError):
        create_console_project(organization=organization, name="Denetçi", owner_membership=auditor)
    assert not AIProject.objects.exists()


@pytest.mark.django_db
def test_consumer_console_generates_subject_and_ignores_forged_value(client: Client) -> None:
    organization = Organization.objects.create(slug="org", name="Org")
    admin, _membership = _member("admin", organization)
    client.force_login(admin)

    response = client.post(
        reverse("console:consumer_create"),
        {
            "organization": organization.pk,
            "subject": "attacker-chosen",
            "name": "Ödeme uygulaması",
            "protocol": ConsumerProtocol.REST,
            "status": ConsumerStatus.ACTIVE,
        },
    )

    assert response.status_code == 302
    consumer = Consumer.objects.get()
    assert consumer.subject != "attacker-chosen"
    assert re.fullmatch(r"consumer-[a-z2-7]{24}", consumer.subject)
    assert response["Location"] == reverse(
        "console:consumer_detail_public", args=[consumer.public_id]
    )


@pytest.mark.django_db
def test_consumer_subject_is_opaque_and_existing_subjects_are_unchanged() -> None:
    organization = Organization.objects.create(slug="org", name="Org")
    legacy = _consumer(organization)
    created = create_console_consumer(
        organization=organization,
        name="Sensitive Customer Name",
        protocol=ConsumerProtocol.REST,
        status=ConsumerStatus.ACTIVE,
    )

    legacy.refresh_from_db()
    assert legacy.subject == "legacy-subject"
    assert "sensitive" not in created.subject
    assert len(created.subject) == 33


@pytest.mark.django_db
def test_consumer_subject_collision_retry_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    organization = Organization.objects.create(slug="org", name="Org")
    _consumer(organization, subject="consumer-aaaaaaaaaaaaaaaaaaaaaaaa")
    monkeypatch.setattr(credentials, "_opaque_subject", lambda: "consumer-aaaaaaaaaaaaaaaaaaaaaaaa")

    with pytest.raises(ConsumerSubjectAllocationError):
        create_console_consumer(
            organization=organization,
            name="Collision",
            protocol=ConsumerProtocol.REST,
            status=ConsumerStatus.ACTIVE,
        )

    assert Consumer.objects.count() == 1


@pytest.mark.django_db
def test_management_command_remains_compatible_and_audited() -> None:
    organization = Organization.objects.create(slug="org", name="Org")
    consumer = _consumer(organization)
    stdout = StringIO()

    call_command(
        "create_consumer_token",
        organization=organization.slug,
        subject=consumer.subject,
        name="cli",
        actor="operator",
        stdout=stdout,
    )

    raw = stdout.getvalue().splitlines()[-1]
    assert resolve_consumer(raw) == consumer
    event = AuditEvent.objects.get(action="consumer_token.issue")
    assert event.actor_id == "operator"
    assert raw not in str(event.__dict__)


@pytest.mark.django_db
def test_admin_issues_token_once_with_no_store_and_redacted_audit(client: Client) -> None:
    organization = Organization.objects.create(slug="org", name="Org")
    admin, _membership = _member("admin", organization)
    consumer = _consumer(organization)
    client.force_login(admin)

    response = client.post(
        reverse("console:consumer_token_issue", args=[consumer.public_id]),
        {"name": "production"},
    )

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store, max-age=0"
    assert response["Pragma"] == "no-cache"
    match = re.search(r"<textarea[^>]*>([^<]+)</textarea>", response.content.decode())
    assert match is not None
    raw = match.group(1)
    token = ConsumerToken.objects.get()
    assert token.token_hash == hash_token(raw)
    assert raw not in token.token_hash
    event = AuditEvent.objects.get(action="consumer_token.issue")
    assert event.outcome == "success"
    assert raw not in str(event.__dict__)
    assert token.token_hash not in str(event.__dict__)
    assert (
        raw
        not in client.get(
            reverse("console:consumer_detail_public", args=[consumer.public_id])
        ).content.decode()
    )


@pytest.mark.django_db
def test_debug_failure_response_redacts_plaintext_and_rolls_back(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    organization = Organization.objects.create(slug="org", name="Org")
    admin, _membership = _member("admin", organization)
    consumer = _consumer(organization)
    raw = "debug-secret-" + "token-that-must-never-appear"

    monkeypatch.setattr(token_module.secrets, "token_urlsafe", lambda _size: raw)

    def fail_audit(**_kwargs: object) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(credentials, "record_event", fail_audit)
    client.force_login(admin)
    client.raise_request_exception = False
    with override_settings(DEBUG=True):
        response = client.post(
            reverse("console:consumer_token_issue", args=[consumer.public_id]),
            {"name": "production"},
        )

    assert response.status_code == 500
    assert raw not in response.content.decode()
    assert not ConsumerToken.objects.exists()


@pytest.mark.django_db
def test_rotation_revokes_old_token_and_reveals_only_replacement(client: Client) -> None:
    organization = Organization.objects.create(slug="org", name="Org")
    admin, _membership = _member("admin", organization)
    consumer = _consumer(organization)
    old_token, old_raw = create_token(consumer, "production")
    client.force_login(admin)

    response = client.post(
        reverse("console:consumer_token_rotate", args=[consumer.public_id, old_token.pk])
    )

    assert response.status_code == 200
    old_token.refresh_from_db()
    assert old_token.status == TokenStatus.REVOKED
    replacement = ConsumerToken.objects.exclude(pk=old_token.pk).get()
    match = re.search(r"<textarea[^>]*>([^<]+)</textarea>", response.content.decode())
    assert match is not None
    replacement_raw = match.group(1)
    assert replacement.token_hash == hash_token(replacement_raw)
    assert old_raw not in response.content.decode()
    assert resolve_consumer(old_raw) is None
    assert resolve_consumer(replacement_raw) == consumer
    assert AuditEvent.objects.filter(action="consumer_token.rotate").exists()


@pytest.mark.django_db
def test_revoke_is_idempotent_and_immediately_denies_token(client: Client) -> None:
    organization = Organization.objects.create(slug="org", name="Org")
    admin, _membership = _member("admin", organization)
    consumer = _consumer(organization)
    token, raw = create_token(consumer, "production")
    client.force_login(admin)
    url = reverse("console:consumer_token_revoke", args=[consumer.public_id, token.pk])

    assert client.post(url).status_code == 302
    assert client.post(url).status_code == 302

    token.refresh_from_db()
    assert token.status == TokenStatus.REVOKED
    assert resolve_consumer(raw) is None
    assert list(
        AuditEvent.objects.filter(action="consumer_token.revoke").values_list("reason", flat=True)
    ) == ["TOKEN_ALREADY_REVOKED", "TOKEN_REVOKED"]


@pytest.mark.django_db
def test_credential_routes_deny_readonly_disabled_and_foreign_targets(client: Client) -> None:
    organization = Organization.objects.create(slug="org", name="Org")
    other = Organization.objects.create(slug="other", name="Other")
    auditor, _membership = _member("auditor", organization, Role.AUDITOR)
    consumer = _consumer(organization)
    foreign = _consumer(other, subject="foreign")
    client.force_login(auditor)

    issue_url = reverse("console:consumer_token_issue", args=[consumer.public_id])
    assert client.get(issue_url).status_code == 405
    assert client.post(issue_url, {"name": "denied"}).status_code == 403
    assert (
        client.post(
            reverse("console:consumer_token_issue", args=[foreign.public_id]), {"name": "hidden"}
        ).status_code
        == 404
    )
    assert not ConsumerToken.objects.exists()

    organization.status = OrganizationStatus.DISABLED
    organization.save(update_fields=["status", "updated_at"])
    assert client.post(issue_url, {"name": "disabled"}).status_code == 403
    assert (
        AuditEvent.objects.filter(
            action="consumer_token.issue", outcome="deny", organization_id=organization.pk
        ).count()
        == 2
    )


@pytest.mark.django_db
def test_disabled_consumer_cannot_issue_or_rotate_but_can_revoke(client: Client) -> None:
    organization = Organization.objects.create(slug="org", name="Org")
    admin, _membership = _member("admin", organization)
    consumer = _consumer(organization)
    token, raw = create_token(consumer, "existing")
    consumer.status = ConsumerStatus.DISABLED
    consumer.save(update_fields=["status", "updated_at"])
    client.force_login(admin)

    assert (
        client.post(
            reverse("console:consumer_token_issue", args=[consumer.public_id]),
            {"name": "blocked"},
        ).status_code
        == 302
    )
    assert (
        client.post(
            reverse("console:consumer_token_rotate", args=[consumer.public_id, token.pk])
        ).status_code
        == 302
    )
    assert ConsumerToken.objects.count() == 1
    token.refresh_from_db()
    assert token.status == TokenStatus.ACTIVE

    assert (
        client.post(
            reverse("console:consumer_token_revoke", args=[consumer.public_id, token.pk])
        ).status_code
        == 302
    )
    token.refresh_from_db()
    assert token.status == TokenStatus.REVOKED
    assert resolve_consumer(raw) is None


@pytest.mark.django_db
def test_token_actions_reject_foreign_token_even_for_authorized_admin(client: Client) -> None:
    organization = Organization.objects.create(slug="org", name="Org")
    admin, _membership = _member("admin", organization)
    first = _consumer(organization, subject="first")
    second = _consumer(organization, subject="second")
    foreign_token, _raw = create_token(second, "other")
    client.force_login(admin)

    assert (
        client.post(
            reverse("console:consumer_token_rotate", args=[first.public_id, foreign_token.pk])
        ).status_code
        == 404
    )
    assert (
        client.post(
            reverse("console:consumer_token_revoke", args=[first.public_id, foreign_token.pk])
        ).status_code
        == 404
    )
    foreign_token.refresh_from_db()
    assert foreign_token.status == TokenStatus.ACTIVE


@pytest.mark.django_db
def test_issue_requires_csrf() -> None:
    organization = Organization.objects.create(slug="org", name="Org")
    admin, _membership = _member("admin", organization)
    consumer = _consumer(organization)
    client = Client(enforce_csrf_checks=True)
    client.force_login(admin)

    response = client.post(
        reverse("console:consumer_token_issue", args=[consumer.public_id]),
        {"name": "blocked"},
    )

    assert response.status_code == 403
    assert not ConsumerToken.objects.exists()
