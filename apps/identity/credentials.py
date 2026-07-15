"""Server-generated consumer identities and audited bearer credential lifecycle."""

from __future__ import annotations

import base64
import secrets

from django.db import IntegrityError, transaction
from django.views.decorators.debug import sensitive_variables

from apps.audit.services import record_event
from apps.identity.models import Consumer, ConsumerStatus, ConsumerToken, TokenStatus
from apps.identity.tokens import create_token
from apps.tenancy.identifiers import MAX_ALLOCATION_ATTEMPTS
from apps.tenancy.models import Organization, OrganizationStatus

_SUBJECT_BYTES = 15
_SUBJECT_PREFIX = "consumer-"


class ConsumerSubjectAllocationError(RuntimeError):
    code = "CONSUMER_SUBJECT_ALLOCATION_FAILED"


class CredentialLifecycleError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _opaque_subject() -> str:
    suffix = (
        base64.b32encode(secrets.token_bytes(_SUBJECT_BYTES)).decode("ascii").rstrip("=").lower()
    )
    return f"{_SUBJECT_PREFIX}{suffix}"


def create_console_consumer(
    *, organization: Organization, name: str, protocol: str, status: str
) -> Consumer:
    """Create a bearer consumer without trusting a client-supplied authentication subject."""
    with transaction.atomic():
        locked_organization = (
            Organization.objects.select_for_update().filter(pk=organization.pk).first()
        )
        if locked_organization is None or locked_organization.status != OrganizationStatus.ACTIVE:
            raise ConsumerSubjectAllocationError
        for _attempt in range(MAX_ALLOCATION_ATTEMPTS):
            subject = _opaque_subject()
            try:
                with transaction.atomic():
                    return Consumer.objects.create(
                        organization=locked_organization,
                        subject=subject,
                        name=name,
                        protocol=protocol,
                        status=status,
                    )
            except IntegrityError:
                if Consumer.objects.filter(
                    organization=locked_organization, subject=subject
                ).exists():
                    continue
                raise
    raise ConsumerSubjectAllocationError


def _locked_consumer(consumer: Consumer) -> Consumer:
    locked = (
        Consumer.objects.select_for_update()
        .select_related("organization")
        .filter(pk=consumer.pk, organization_id=consumer.organization_id)
        .first()
    )
    if locked is None:
        raise CredentialLifecycleError("CONSUMER_NOT_FOUND")
    return locked


@sensitive_variables("raw")
def issue_consumer_token(
    *,
    consumer: Consumer,
    name: str,
    actor_id: str,
    request_id: str = "",
    trace_id: str = "",
) -> tuple[ConsumerToken, str]:
    with transaction.atomic():
        locked_consumer = _locked_consumer(consumer)
        if (
            locked_consumer.status != ConsumerStatus.ACTIVE
            or locked_consumer.organization.status != OrganizationStatus.ACTIVE
        ):
            raise CredentialLifecycleError("CONSUMER_NOT_ACTIVE")
        token, raw = create_token(locked_consumer, name)
        try:
            record_event(
                actor_type="user",
                actor_id=actor_id,
                action="consumer_token.issue",
                outcome="success",
                organization_id=locked_consumer.organization_id,
                resource_type="consumer_token",
                resource_id=str(token.pk),
                reason="TOKEN_ISSUED",
                request_id=request_id,
                trace_id=trace_id,
                after={
                    "consumer_id": locked_consumer.pk,
                    "prefix": token.prefix,
                    "status": token.status,
                },
            )
        except BaseException:
            raw = ""
            raise
        return token, raw


@sensitive_variables("raw")
def rotate_consumer_token(
    *,
    consumer: Consumer,
    token_id: int,
    actor_id: str,
    request_id: str = "",
    trace_id: str = "",
) -> tuple[ConsumerToken, str]:
    with transaction.atomic():
        locked_consumer = _locked_consumer(consumer)
        if (
            locked_consumer.status != ConsumerStatus.ACTIVE
            or locked_consumer.organization.status != OrganizationStatus.ACTIVE
        ):
            raise CredentialLifecycleError("CONSUMER_NOT_ACTIVE")
        old_token = (
            ConsumerToken.objects.select_for_update()
            .filter(
                pk=token_id,
                consumer=locked_consumer,
                organization_id=locked_consumer.organization_id,
            )
            .first()
        )
        if old_token is None:
            raise CredentialLifecycleError("TOKEN_NOT_FOUND")
        if old_token.status != TokenStatus.ACTIVE:
            raise CredentialLifecycleError("TOKEN_NOT_ACTIVE")
        old_token.status = TokenStatus.REVOKED
        old_token.save(update_fields=["status", "updated_at"])
        new_token, raw = create_token(locked_consumer, old_token.name)
        try:
            record_event(
                actor_type="user",
                actor_id=actor_id,
                action="consumer_token.rotate",
                outcome="success",
                organization_id=locked_consumer.organization_id,
                resource_type="consumer_token",
                resource_id=str(old_token.pk),
                reason="TOKEN_ROTATED",
                request_id=request_id,
                trace_id=trace_id,
                before={"status": TokenStatus.ACTIVE, "prefix": old_token.prefix},
                after={
                    "status": TokenStatus.REVOKED,
                    "replacement_id": new_token.pk,
                    "replacement_prefix": new_token.prefix,
                },
            )
        except BaseException:
            raw = ""
            raise
        return new_token, raw


def revoke_consumer_token(
    *,
    consumer: Consumer,
    token_id: int,
    actor_id: str,
    request_id: str = "",
    trace_id: str = "",
) -> bool:
    with transaction.atomic():
        locked_consumer = _locked_consumer(consumer)
        token = (
            ConsumerToken.objects.select_for_update()
            .filter(
                pk=token_id,
                consumer=locked_consumer,
                organization_id=locked_consumer.organization_id,
            )
            .first()
        )
        if token is None:
            raise CredentialLifecycleError("TOKEN_NOT_FOUND")
        changed = token.status != TokenStatus.REVOKED
        if changed:
            token.status = TokenStatus.REVOKED
            token.save(update_fields=["status", "updated_at"])
        record_event(
            actor_type="user",
            actor_id=actor_id,
            action="consumer_token.revoke",
            outcome="success",
            organization_id=locked_consumer.organization_id,
            resource_type="consumer_token",
            resource_id=str(token.pk),
            reason="TOKEN_REVOKED" if changed else "TOKEN_ALREADY_REVOKED",
            request_id=request_id,
            trace_id=trace_id,
            before={"status": TokenStatus.ACTIVE if changed else TokenStatus.REVOKED},
            after={"status": TokenStatus.REVOKED},
        )
        return changed
