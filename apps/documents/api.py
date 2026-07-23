"""Operator JSON API for the document content plane (session/LDAP authenticated).

An *operator* surface mounted under ``/console/api/documents/``. It reuses the console's
Django authentication (LDAP in production per ADR-0001, or the model backend when LDAP is
disabled) and the Sprint 1 tenant/role authorization helpers. It is **not** the public
consumer gateway — there is no bearer-token path, no CORS, and CSRF applies to every mutating
method. The frontend is non-authoritative; every authorization/lifecycle decision is re-made
here on the server.

Authorization:
- read (list/retrieve) is membership-scoped (:func:`allowed_organization_ids`);
- create/upload/soft-delete require ``can_author_scenarios`` in the target organization;
- physical purge requires the elevated ``can_admin_org`` (organization admin / platform admin).

Responses never expose object-store keys, physical store names, secret refs, or egress
endpoints — only tenant-scoped metadata (ids, counts, checksums, stable states).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import wraps
from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods

from apps.documents import services
from apps.documents.models import (
    Document,
    DocumentSet,
    DocumentSetVersion,
    DocumentVersion,
)
from apps.documents.storage import StorageError
from apps.tenancy.models import Organization
from apps.tenancy.services import (
    allowed_organization_ids,
    can_admin_org,
    can_manage_documents,
)


def operator_api(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Require an authenticated operator and translate errors to JSON envelopes."""

    @wraps(view)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not request.user.is_authenticated:
            return JsonResponse({"error": {"code": "authentication_required"}}, status=401)
        try:
            return view(request, *args, **kwargs)
        except services.DocumentError as exc:
            return JsonResponse({"error": {"code": exc.code, "message": str(exc)}}, status=400)
        except ValidationError as exc:
            return JsonResponse(
                {"error": {"code": "invalid", "message": "; ".join(exc.messages)}}, status=400
            )
        except StorageError:
            # Content-free: a storage backend failure must not leak store internals.
            return JsonResponse({"error": {"code": "storage_unavailable"}}, status=502)
        except PermissionDenied:
            return JsonResponse({"error": {"code": "forbidden"}}, status=403)
        except Http404:
            return JsonResponse({"error": {"code": "not_found"}}, status=404)

    return wrapper


def _request_id(request: HttpRequest) -> str:
    return getattr(request, "request_id", "")


def _actor(request: HttpRequest) -> str:
    return request.user.get_username()


def _json_body(request: HttpRequest) -> dict[str, Any]:
    if not request.body:
        return {}
    try:
        parsed = json.loads(request.body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise services.DocumentError("invalid_json", "request body is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise services.DocumentError("invalid_json", "request body must be a JSON object")
    return parsed


def _resolve_org_in_scope(request: HttpRequest, ref: Any) -> Organization:
    allowed = allowed_organization_ids(request.user)
    qs = Organization.objects.all()
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        org = qs.filter(pk=int(ref)).first()
    elif isinstance(ref, str) and ref:
        org = qs.filter(slug=ref).first()
    else:
        raise services.DocumentError("organization_required", "organization is required")
    if org is None or (allowed is not None and org.id not in allowed):
        raise Http404
    return org


def _require_author(request: HttpRequest, organization_id: int) -> None:
    if not can_manage_documents(request.user, organization_id):
        raise PermissionDenied


def _require_admin(request: HttpRequest, organization_id: int) -> None:
    if not can_admin_org(request.user, organization_id):
        raise PermissionDenied


def _scoped(request: HttpRequest, qs: Any) -> Any:
    allowed = allowed_organization_ids(request.user)
    return qs if allowed is None else qs.filter(organization_id__in=allowed)


def _scoped_document(request: HttpRequest, pk: int) -> Document:
    document = (
        _scoped(request, Document.objects.select_related("organization")).filter(pk=pk).first()
    )
    if document is None:
        raise Http404
    return document


def _scoped_set(request: HttpRequest, pk: int) -> DocumentSet:
    document_set = (
        _scoped(request, DocumentSet.objects.select_related("organization")).filter(pk=pk).first()
    )
    if document_set is None:
        raise Http404
    return document_set


def _scoped_set_version(request: HttpRequest, pk: int) -> DocumentSetVersion:
    version = (
        _scoped(request, DocumentSetVersion.objects.select_related("organization", "document_set"))
        .filter(pk=pk)
        .first()
    )
    if version is None:
        raise Http404
    return version


def _serialize_document(document: Document, *, request: HttpRequest, detail: bool = False) -> dict:
    data: dict[str, Any] = {
        "id": document.pk,
        "organization": document.organization.slug,
        "organization_id": document.organization_id,
        "logical_id": document.logical_id,
        "title": document.title,
        "current_version": document.current_version,
        "lifecycle_state": document.lifecycle_state,
        "deleted_at": document.deleted_at.isoformat() if document.deleted_at else None,
        "updated_at": document.updated_at.isoformat(),
        "can_write": can_manage_documents(request.user, document.organization_id),
        "can_purge": can_admin_org(request.user, document.organization_id),
    }
    if detail:
        data["versions"] = [
            {
                "id": v.pk,
                "version": v.version,
                "checksum": v.checksum,
                "mime_type": v.mime_type,
                "byte_size": v.byte_size,
                "parse_status": v.parse_status,
                "created_at": v.created_at.isoformat(),
            }
            for v in document.versions.all().order_by("version")
        ]
    return data


def _serialize_set(document_set: DocumentSet, *, request: HttpRequest) -> dict:
    return {
        "id": document_set.pk,
        "organization": document_set.organization.slug,
        "organization_id": document_set.organization_id,
        "logical_id": document_set.logical_id,
        "name": document_set.name,
        "status": document_set.status,
        "versions": [
            {"id": v.pk, "version": v.version, "status": v.status}
            for v in document_set.versions.all().order_by("version")
        ],
        "can_write": can_manage_documents(request.user, document_set.organization_id),
    }


@operator_api
@require_http_methods(["GET", "POST"])
def documents(request: HttpRequest) -> HttpResponse:
    if request.method == "GET":
        include_deleted = request.GET.get("include_deleted") == "true"
        qs = _scoped(request, Document.objects.select_related("organization"))
        if not include_deleted:
            qs = qs.filter(deleted_at__isnull=True)
        items = [_serialize_document(d, request=request) for d in qs]
        return JsonResponse({"documents": items})

    org = _resolve_org_in_scope(request, request.POST.get("organization"))
    _require_author(request, org.id)
    upload = request.FILES.get("file")
    if upload is None:
        raise services.DocumentError("file_required", "a multipart 'file' field is required")
    version = services.upload_document(
        organization=org,
        logical_id=request.POST.get("logical_id", ""),
        title=request.POST.get("title", ""),
        mime_type=upload.content_type or "application/octet-stream",
        data=upload.read(),
        actor=_actor(request),
        request_id=_request_id(request),
    )
    return JsonResponse(
        {
            "document_id": version.document_id,
            "logical_id": version.document.logical_id,
            "version": version.version,
            "checksum": version.checksum,
            "byte_size": version.byte_size,
        },
        status=201,
    )


@operator_api
@require_http_methods(["GET", "DELETE"])
def document_detail(request: HttpRequest, pk: int) -> HttpResponse:
    document = _scoped_document(request, pk)
    if request.method == "GET":
        return JsonResponse(_serialize_document(document, request=request, detail=True))
    _require_author(request, document.organization_id)
    services.soft_delete_document(document, actor=_actor(request), request_id=_request_id(request))
    return JsonResponse({"soft_deleted": True})


@operator_api
@require_http_methods(["POST"])
def document_purge(request: HttpRequest, pk: int) -> HttpResponse:
    document = _scoped_document(request, pk)
    _require_admin(request, document.organization_id)
    removed = services.purge_document(
        document, actor=_actor(request), request_id=_request_id(request)
    )
    return JsonResponse({"purged": True, "versions_removed": removed})


@operator_api
@require_http_methods(["GET", "POST"])
def document_sets(request: HttpRequest) -> HttpResponse:
    if request.method == "GET":
        qs = _scoped(request, DocumentSet.objects.select_related("organization")).prefetch_related(
            "versions"
        )
        return JsonResponse({"document_sets": [_serialize_set(s, request=request) for s in qs]})

    payload = _json_body(request)
    org = _resolve_org_in_scope(request, payload.get("organization"))
    _require_author(request, org.id)
    document_set = services.create_document_set(
        organization=org,
        logical_id=payload.get("logical_id", ""),
        name=payload.get("name", ""),
        actor=_actor(request),
        request_id=_request_id(request),
    )
    return JsonResponse(_serialize_set(document_set, request=request), status=201)


@operator_api
@require_http_methods(["POST"])
def document_set_versions(request: HttpRequest, pk: int) -> HttpResponse:
    document_set = _scoped_set(request, pk)
    _require_author(request, document_set.organization_id)
    version = services.create_document_set_version(
        document_set=document_set, actor=_actor(request), request_id=_request_id(request)
    )
    return JsonResponse(
        {"id": version.pk, "version": version.version, "status": version.status}, status=201
    )


@operator_api
@require_http_methods(["POST"])
def set_version_members(request: HttpRequest, pk: int) -> HttpResponse:
    set_version = _scoped_set_version(request, pk)
    _require_author(request, set_version.organization_id)
    payload = _json_body(request)
    document_version = (
        _scoped(request, DocumentVersion.objects.all())
        .filter(pk=payload.get("document_version_id"))
        .first()
    )
    if document_version is None:
        raise Http404
    membership = services.add_document_to_set_version(
        set_version=set_version,
        document_version=document_version,
        ordinal=int(payload.get("ordinal", 0) or 0),
        actor=_actor(request),
        request_id=_request_id(request),
    )
    return JsonResponse({"membership_id": membership.pk}, status=201)


@operator_api
@require_http_methods(["POST"])
def set_version_publish(request: HttpRequest, pk: int) -> HttpResponse:
    set_version = _scoped_set_version(request, pk)
    _require_author(request, set_version.organization_id)
    published = services.publish_document_set_version(
        set_version=set_version, actor=_actor(request), request_id=_request_id(request)
    )
    return JsonResponse({"id": published.pk, "status": published.status})
