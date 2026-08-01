"""Console request context: the active-organization workspace selector.

The active organization is a **display filter only**. Every console queryset is still
derived server-side from :func:`apps.tenancy.services.allowed_organization_ids`; the
active organization merely narrows an already-tenant-scoped list to one organization for
readability. It never widens access, and it is re-validated against current membership on
**every** request — a stale, revoked, or forged id is cleared and treated as
the deterministic first authorized organization.
"""

from __future__ import annotations

from django.http import HttpRequest

from apps.console import scoping
from apps.tenancy.models import Organization
from apps.tenancy.services import can_admin_org, is_platform_admin

# Session key holding the operator's chosen active organization (an integer pk).
SESSION_KEY = "active_organization_id"

# Upper bound on how many organizations the selector renders; a platform admin could be a
# member of many. Beyond this the selector is capped and flagged; operators can still
# reach authorized objects by deep link without changing the explicit workspace selection.
_MAX_SELECTOR_ORGS = 200


def resolve_active_organization(request: HttpRequest) -> Organization | None:
    """Return the validated active organization, or ``None`` when none is accessible.

    The session id is confirmed against current membership every request; an invalid or
    no-longer-permitted id is replaced with the first authorized organization.
    Never trusts the session value for authorization — it can only *narrow* what the user
    is already allowed to see.
    """
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    raw = request.session.get(SESSION_KEY)
    fallback = scoping.scoped_organizations(user).order_by("name", "slug", "pk").first()
    if raw is None:
        if fallback is not None:
            request.session[SESSION_KEY] = fallback.pk
        return fallback
    try:
        org_id = int(raw)
    except (TypeError, ValueError):
        if fallback is None:
            request.session.pop(SESSION_KEY, None)
            return None
        request.session[SESSION_KEY] = fallback.pk
        return fallback
    organization = scoping.scoped_organizations(user).filter(pk=org_id).first()
    if organization is None:
        if fallback is None:
            request.session.pop(SESSION_KEY, None)
            return None
        request.session[SESSION_KEY] = fallback.pk
        return fallback
    return organization


def active_workspace(request: HttpRequest) -> dict[str, object]:
    """Context processor: active organization + the selectable organization list.

    Registered in ``TEMPLATES`` so the sidebar selector renders consistently on every
    screen without each view recomputing it. Returns an empty mapping for anonymous
    requests (the login page has no chrome).
    """
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return {}
    available = list(
        scoping.scoped_organizations(user).order_by("name", "slug")[: _MAX_SELECTOR_ORGS + 1]
    )
    available_limited = len(available) > _MAX_SELECTOR_ORGS
    available = available[:_MAX_SELECTOR_ORGS]
    active = resolve_active_organization(request)
    return {
        "active_organization": active,
        "available_organizations": available,
        "available_organizations_limited": available_limited,
        # Multiple organizations use a dropdown; single-org users get a static label.
        "workspace_multi_org": len(available) > 1,
        "can_manage_organization_members": (active is not None and can_admin_org(user, active.pk)),
        "is_platform_admin": is_platform_admin(user),
    }
