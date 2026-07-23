import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.identity.authorization import AuthoritySource, Capability, authorize
from apps.identity.models import GlobalAdministrator
from apps.identity.roles import Role
from apps.tenancy.models import Organization, OrganizationMembership, OrganizationStatus

pytestmark = pytest.mark.django_db


def _user(username: str, *, superuser: bool = False, active: bool = True):
    return get_user_model().objects.create_user(
        username=username,
        password=None,
        is_superuser=superuser,
        is_staff=superuser,
        is_active=active,
    )


def test_global_administrator_is_single_non_superuser_identity() -> None:
    daily = _user("daily-admin")
    recovery = _user("recovery-admin", superuser=True)
    inactive = _user("inactive-admin", active=False)
    GlobalAdministrator(user=daily).full_clean()

    with pytest.raises(ValidationError):
        GlobalAdministrator(user=recovery).full_clean()
    with pytest.raises(ValidationError):
        GlobalAdministrator(user=inactive).full_clean()
    with pytest.raises(ValidationError):
        GlobalAdministrator(user=daily, scope="not-global").full_clean()


def test_global_administrator_singleton_is_database_enforced() -> None:
    GlobalAdministrator.objects.create(user=_user("first-global-admin"))

    with pytest.raises(IntegrityError), transaction.atomic():
        GlobalAdministrator.objects.create(user=_user("second-global-admin"))


def test_global_administrator_has_admin_but_not_document_content_authority() -> None:
    user = _user("global-admin")
    GlobalAdministrator.objects.create(user=user)

    allowed = authorize(user=user, capability=Capability.SCENARIO_RELEASE)
    excluded = authorize(user=user, capability=Capability.DOCUMENT_SET_CONTENT_READ)
    grant_excluded = authorize(user=user, capability=Capability.DOCUMENT_SET_RETRIEVE_GRANT)

    assert allowed.allowed is True
    assert allowed.source == AuthoritySource.GLOBAL_ADMINISTRATOR
    assert excluded.allowed is False
    assert excluded.reason == "GLOBAL_ADMINISTRATOR_CAPABILITY_EXCLUDED"
    assert grant_excluded.allowed is False


def test_organization_administrator_is_tenant_bound_and_content_excluded() -> None:
    user = _user("org-admin")
    own = Organization.objects.create(slug="own", name="Own")
    foreign = Organization.objects.create(slug="foreign", name="Foreign")
    OrganizationMembership.objects.create(
        organization=own, user=user, role=Role.ORGANIZATION_ADMIN
    )

    assert authorize(
        user=user, capability=Capability.SCENARIO_RELEASE, organization=own
    ).allowed
    assert not authorize(
        user=user, capability=Capability.SCENARIO_RELEASE, organization=foreign
    ).allowed
    assert not authorize(
        user=user, capability=Capability.DOCUMENT_SET_CONTENT_READ, organization=own
    ).allowed


def test_disabled_organization_denies_normal_administrator_mutation() -> None:
    user = _user("disabled-org-admin")
    organization = Organization.objects.create(
        slug="disabled", name="Disabled", status=OrganizationStatus.DISABLED
    )
    OrganizationMembership.objects.create(
        organization=organization, user=user, role=Role.ORGANIZATION_ADMIN
    )

    decision = authorize(
        user=user, capability=Capability.ORGANIZATION_MANAGE, organization=organization
    )

    assert not decision.allowed
    assert decision.reason == "ORGANIZATION_INACTIVE"

    global_user = _user("global-disabled-admin")
    GlobalAdministrator.objects.create(user=global_user)
    global_decision = authorize(
        user=global_user,
        capability=Capability.SCENARIO_RELEASE,
        organization=organization,
    )
    assert not global_decision.allowed
    assert global_decision.reason == "ORGANIZATION_INACTIVE"


def test_superadmin_is_explicit_recovery_source_and_anonymous_is_denied() -> None:
    recovery = _user("recovery", superuser=True)
    decision = authorize(user=recovery, capability=Capability.DOCUMENT_SET_CONTENT_READ)

    assert decision.allowed
    assert decision.source == AuthoritySource.SUPERADMIN_RECOVERY

    anonymous = type("Anonymous", (), {"is_authenticated": False, "is_active": False})()
    assert not authorize(user=anonymous, capability=Capability.PLATFORM_MANAGE).allowed
