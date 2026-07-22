"""Console request context: the active-organization workspace selector.

The active organization is a **display filter only**. Every console queryset is still
derived server-side from :func:`apps.tenancy.services.allowed_organization_ids`; the
active organization merely narrows an already-tenant-scoped list to one organization for
readability. It never widens access, and it is re-validated against current membership on
**every** request — a stale, revoked, or forged id is cleared and treated as
"all organizations".
"""

from __future__ import annotations

from django.http import HttpRequest

from apps.console import scoping
from apps.tenancy.models import Organization
from apps.tenancy.services import is_platform_admin

# Session key holding the operator's chosen active organization (an integer pk) or absent
# for "all organizations".
SESSION_KEY = "active_organization_id"

# Upper bound on how many organizations the selector renders; a platform admin could be a
# member of many. Beyond this the selector is capped and flagged; operators can still
# reach authorized objects by deep link without changing the explicit workspace selection.
_MAX_SELECTOR_ORGS = 200


def resolve_active_organization(request: HttpRequest) -> Organization | None:
    """Return the validated active organization, or ``None`` for "all organizations".

    The session id is confirmed against current membership every request; an invalid or
    no-longer-permitted id is cleared from the session and treated as "all organizations".
    Never trusts the session value for authorization — it can only *narrow* what the user
    is already allowed to see.
    """
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    raw = request.session.get(SESSION_KEY)
    if raw is None:
        # A non-platform user with exactly one visible organization has no meaningful
        # "all organizations" choice. Persist the deterministic default so subsequent
        # requests observe the same explicit workspace. Platform admins always default
        # to the cross-organization view, even in a one-organization installation.
        if not is_platform_admin(user):
            visible = list(scoping.scoped_organizations(user).order_by("pk")[:2])
            if len(visible) == 1:
                request.session[SESSION_KEY] = visible[0].pk
                return visible[0]
        return None
    try:
        org_id = int(raw)
    except (TypeError, ValueError):
        request.session.pop(SESSION_KEY, None)
        return resolve_active_organization(request)
    organization = scoping.scoped_organizations(user).filter(pk=org_id).first()
    if organization is None:
        # Membership lost or forged id: clear and apply the normal deterministic default.
        request.session.pop(SESSION_KEY, None)
        return resolve_active_organization(request)
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
        # Offer the "all organizations" option (and a real dropdown) only when the user can
        # actually see more than one organization; single-org users get a static label.
        "workspace_multi_org": len(available) > 1 or is_platform_admin(user),
    }
