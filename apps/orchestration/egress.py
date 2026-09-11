from __future__ import annotations

import json
from typing import Any

from apps.orchestration.models import ModelProfile, ModelProfileStatus
from apps.orchestration.secrets_resolver import ModelEnvSecretResolver
from apps.tools.adapters import ToolAdapterError, ToolAdapterRequest, ToolAdapterUncertain
from apps.tools.egress import DnsResolver, EgressDenied, validate_destination
from apps.tools.http_adapter import (
    ConnectionFactory,
    _default_connection_factory,
    perform_https_post,
)
from apps.tools.secrets_resolver import SecretResolutionError, SecretResolver


class ModelEgressError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ModelEgressOutcomeUnknown(ModelEgressError):
    pass


class JsonModelEgressClient:
    """Profile-ID-only JSON egress; callers can never supply a destination."""

    def __init__(
        self,
        *,
        resolver: DnsResolver | None = None,
        connection_factory: ConnectionFactory | None = None,
        secret_resolver: SecretResolver | None = None,
    ) -> None:
        self._resolver = resolver
        self._connection_factory = connection_factory or _default_connection_factory
        self._secret_resolver = secret_resolver or ModelEnvSecretResolver()

    def call_json(
        self, *, profile_id: str, operation: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if operation != "chat":
            raise ModelEgressError("OPERATION_NOT_ALLOWED")
        try:
            profile = ModelProfile.objects.get(
                public_id=profile_id, status=ModelProfileStatus.ACTIVE
            )
        except (ModelProfile.DoesNotExist, ValueError, TypeError) as exc:
            raise ModelEgressError("MODEL_PROFILE_UNAVAILABLE") from exc
        try:
            destination = validate_destination(
                {
                    "scheme": profile.scheme,
                    "host": profile.host,
                    "port": profile.port,
                    "path_prefix": profile.path,
                },
                resolver=self._resolver,
            )
            credential = self._secret_resolver.resolve(profile.secret_ref)
        except EgressDenied as exc:
            raise ModelEgressError(exc.code) from exc
        except SecretResolutionError as exc:
            raise ModelEgressError(exc.code) from exc

        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        request = ToolAdapterRequest(
            protocol="http",
            method="POST",
            destination=destination,
            payload={},
            credential=credential,
            timeout_seconds=profile.timeout_seconds,
            max_response_bytes=profile.max_response_bytes,
        )
        headers = {
            "Host": destination.host,
            "Authorization": f"Bearer {credential}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            raw = perform_https_post(
                self._connection_factory,
                request,
                path=destination.path_prefix,
                headers=headers,
                body=body,
            )
        except ToolAdapterUncertain as exc:
            raise ModelEgressOutcomeUnknown(exc.code) from exc
        except ToolAdapterError as exc:
            raise ModelEgressError(exc.code) from exc
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ModelEgressError("RESPONSE_NOT_JSON") from exc
        if not isinstance(parsed, dict):
            raise ModelEgressError("RESPONSE_NOT_OBJECT")
        return parsed
