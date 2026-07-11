"""Resolve an operator's organization roles for tool-approval decisions."""

from __future__ import annotations

from django.contrib.auth import get_user_model

from apps.tenancy.models import OrganizationMembership


def resolve_actor_roles(*, username: str, organization_id: int) -> list[str] | None:
    """Return the acting user's roles in the organization, or None if unknown.

    A platform admin (Django superuser) carries the ``platform_admin`` role
    everywhere; other operators carry only their explicit organization memberships.
    """
    user = get_user_model().objects.filter(username=username).first()
    if user is None:
        return None
    if user.is_superuser:
        return ["platform_admin"]
    return list(
        OrganizationMembership.objects.filter(
            user=user, organization_id=organization_id
        ).values_list("role", flat=True)
    )
