"""Public gateway endpoints (v3 plan §11).

Flow for invoke/query: authenticate consumer -> authorize scenario alias +
capability -> resolve the active release -> validate input against the release input
contract -> honor idempotency -> issue a signed ExecutionContext -> dispatch to the
runtime facade -> audit + usage. Everything is fail-closed and returns the standard
error envelope.
"""

from __future__ import annotations

import time
from typing import Any

import jsonschema
from django.db import IntegrityError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.artifacts.validation import compute_checksum
from apps.audit.services import record_event
from apps.gateway.errors import ApiError, ErrorCode
from apps.gateway.execution_context import issue_execution_context
from apps.gateway.models import IdempotencyRecord
from apps.gateway.runtime import dispatch
from apps.identity.capabilities import Capability
from apps.identity.services import resolve_active_binding
from apps.observability.models import UsageEvent
from apps.releases.services import get_active_release, get_artifact_body_for_role

_QUERY_CAPABILITY = Capability.QUERY


def _require_mapping(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "Request body must be a JSON object.",
            http_status_code=400,
        )
    return data


def _require_alias(data: dict[str, Any]) -> str:
    alias = data.get("scenario_alias")
    # Only a bound alias routes; raw project_id/release_id in the body are ignored.
    if not isinstance(alias, str) or not alias:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "scenario_alias is required.",
            http_status_code=400,
        )
    return alias


def _validate_input(release: Any, input_payload: dict[str, Any]) -> None:
    schema = get_artifact_body_for_role(release, "input_contract")
    if schema is None:
        return
    try:
        jsonschema.validate(instance=input_payload, schema=schema)
    except jsonschema.ValidationError as exc:
        # Do not echo the offending value; report only the location.
        raise ApiError(
            ErrorCode.INPUT_CONTRACT_VIOLATION,
            "Input does not satisfy the scenario input contract.",
            http_status_code=400,
            details=[{"path": [str(p) for p in exc.absolute_path]}],
        ) from None


class _GatewayView(APIView):
    """Shared authorization + dispatch pipeline for invoke/query."""

    operation = "invoke"

    def _extract(self, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Return (scenario_alias, input_payload). Overridden by the query facade."""
        alias = _require_alias(data)
        payload = data.get("input")
        if not isinstance(payload, dict):
            raise ApiError(
                ErrorCode.VALIDATION_ERROR, "input must be an object.", http_status_code=400
            )
        return alias, payload

    def post(self, request: Request) -> Response:
        started = time.monotonic()
        consumer = request.auth  # set by ConsumerTokenAuthentication
        request_id = getattr(request, "request_id", "")
        data = _require_mapping(request.data)
        alias, input_payload = self._extract(data)

        try:
            response = self._process(request, consumer, request_id, alias, input_payload)
        except ApiError as exc:
            self._record_usage(consumer, request_id, alias, exc.code, started)
            record_event(
                actor_type="consumer",
                actor_id=consumer.subject,
                action=f"gateway.{self.operation}",
                outcome="deny",
                organization_id=consumer.organization_id,
                resource_type="scenario_alias",
                resource_id=alias,
                reason=exc.code,
                request_id=request_id,
            )
            raise
        return response

    def _process(
        self,
        request: Request,
        consumer: Any,
        request_id: str,
        alias: str,
        input_payload: dict[str, Any],
    ) -> Response:
        # Authorize alias + capability against the consumer's bindings.
        resolved = resolve_active_binding(
            organization_id=consumer.organization_id, subject=consumer.subject, alias=alias
        )
        if resolved is None:
            raise ApiError(
                ErrorCode.SCENARIO_NOT_ALLOWED,
                "The scenario alias is not available to this consumer.",
                http_status_code=403,
            )
        if _QUERY_CAPABILITY not in resolved.capabilities:
            raise ApiError(
                ErrorCode.CAPABILITY_DENIED,
                "The required capability is not granted.",
                http_status_code=403,
            )

        scenario = resolved.binding.scenario
        release = get_active_release(scenario)
        if release is None:
            raise ApiError(
                ErrorCode.RELEASE_NOT_AVAILABLE,
                "No active release for this scenario.",
                http_status_code=503,
                retryable=True,
            )

        _validate_input(release, input_payload)

        # Idempotency: replay identical, conflict on differing body.
        idem_key = request.headers.get("Idempotency-Key")
        request_hash = compute_checksum(
            {"alias": alias, "input": input_payload, "op": self.operation}
        )
        if idem_key:
            replay = self._check_idempotency(consumer, idem_key, request_hash)
            if replay is not None:
                return replay

        context = issue_execution_context(
            organization_id=consumer.organization_id,
            project_id=scenario.project_id,
            scenario_id=scenario.id,
            scenario_alias=alias,
            consumer_id=consumer.id,
            capabilities=list(resolved.capabilities),
            release_id=release.id,
            request_id=request_id,
        )
        result = dispatch(
            execution_context=context, validated_input=input_payload, operation=self.operation
        )

        body = {
            "request_id": request_id,
            "scenario_alias": alias,
            "release_id": release.id,
            "status": result["status"],
            "output": result["output"],
            "detail": result["detail"],
        }
        if idem_key:
            self._store_idempotency(consumer, idem_key, request_hash, 200, body)

        record_event(
            actor_type="consumer",
            actor_id=consumer.subject,
            action=f"gateway.{self.operation}",
            outcome="success",
            organization_id=consumer.organization_id,
            resource_type="scenario",
            resource_id=str(scenario.id),
            request_id=request_id,
        )
        self._record_usage_success(consumer, request_id, scenario, release, result["status"])
        return Response(body, status=200)

    def _check_idempotency(self, consumer: Any, key: str, request_hash: str) -> Response | None:
        existing = IdempotencyRecord.objects.filter(consumer=consumer, key=key).first()
        if existing is None:
            return None
        if existing.request_hash != request_hash:
            raise ApiError(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "Idempotency-Key was reused with a different request body.",
                http_status_code=409,
            )
        return Response(existing.response_body, status=existing.response_status)

    def _store_idempotency(
        self, consumer: Any, key: str, request_hash: str, status_code: int, body: dict
    ) -> None:
        try:
            IdempotencyRecord.objects.create(
                consumer=consumer,
                key=key,
                request_hash=request_hash,
                response_status=status_code,
                response_body=body,
            )
        except IntegrityError:
            # Concurrent create with the same key; the stored one wins.
            pass

    def _record_usage_success(
        self, consumer: Any, request_id: str, scenario: Any, release: Any, status: str
    ) -> None:
        UsageEvent.objects.create(
            request_id=request_id,
            organization_id=consumer.organization_id,
            scenario_id=scenario.id,
            release_id=release.id,
            consumer_id=consumer.id,
            operation=self.operation,
            status=status,
        )

    def _record_usage(
        self, consumer: Any, request_id: str, alias: str, error_code: str, started: float
    ) -> None:
        UsageEvent.objects.create(
            request_id=request_id,
            organization_id=consumer.organization_id,
            consumer_id=consumer.id,
            operation=self.operation,
            status="error",
            error_code=error_code,
            latency_ms=int((time.monotonic() - started) * 1000),
        )


class InvokeView(_GatewayView):
    operation = "invoke"


class QueryView(_GatewayView):
    """RAG facade: top-level ``query`` is reshaped into the invoke input."""

    operation = "query"

    def _extract(self, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        alias = _require_alias(data)
        query = data.get("query")
        if not isinstance(query, str) or not query:
            raise ApiError(ErrorCode.VALIDATION_ERROR, "query is required.", http_status_code=400)
        payload: dict[str, Any] = {"query": query}
        if isinstance(data.get("conversation_id"), str):
            payload["conversation_id"] = data["conversation_id"]
        return alias, payload


class RunStatusView(APIView):
    def get(self, request: Request, run_id: str) -> Response:
        # No durable runs exist yet (async workflow/agent runs arrive later).
        raise ApiError(ErrorCode.RUN_NOT_FOUND, "Run not found.", http_status_code=404)
