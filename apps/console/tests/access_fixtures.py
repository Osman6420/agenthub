"""Explicit initial access for authoring tests that retain narrow specialist actors."""

from django.contrib.auth import get_user_model

from apps.tenancy.models import Organization, OrganizationMembership


def private_access_member(organization: Organization) -> int:
    # The acting author is deliberately not this manager: negative editor/release
    # tests must continue to exercise their exact, narrow responsibilities.
    user, _ = get_user_model().objects.get_or_create(
        username=f"initial-access-manager-{organization.pk}"
    )
    membership, _ = OrganizationMembership.objects.get_or_create(
        organization=organization, user=user
    )
    return membership.pk
