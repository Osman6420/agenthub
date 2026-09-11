"""Canonical OpenAI-compatible gateway backed exclusively by unified Runs."""

from __future__ import annotations

import time
import uuid
from datetime import timedelta
from typing import Any

import jsonschema
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.artifacts.validation import compute_checksum
from apps.audit.services import record_event
from apps.gateway.errors import ApiError, ErrorCode
from apps.gateway.execution_context import issue_execution_context
from apps.gateway.models import IdempotencyRecord
from apps.gateway.openai_compat import (
    chat_response,
    compatible_error,
    parse_chat_request,
    parse_responses_request,
    prepare_runtime_input,
    responses_response,
)
from apps.identity.capabilities import Capability
from apps.identity.models import ConsumerProtocol
from apps.identity.services import resolve_active_binding
from apps.observability.models import UsageEvent
from apps.releases.routing import select_release
from apps.releases.services import get_artifact_body_for_role
from apps.tenancy.context import set_tenant_context
from apps.workflows.compiler import WorkflowCompileError
from apps.workflows.models import Run, RunStatus
from apps.workflows.services import (
    WorkflowRequestError,
    request_unified_run,
    resolve_release_workflow,
)
from apps.workflows.tasks import dispatch_unified_background_run
from apps.workflows.transitions import renew_sync_lease, request_run_cancellation
from apps.workflows.unified_executor import execute_sync_run


def _require_mapping(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "Request body must be a JSON object.",
            http_status_code=400,
        )
    return data


def _validate_input(release: Any, input_payload: dict[str, Any]) -> None:
    schema = get_artifact_body_for_role(release, "input_contract")
    if schema is None:
        return
    try:
        jsonschema.validate(instance=input_payload, schema=schema)
    except jsonschema.ValidationError as exc:
        raise ApiError(
            ErrorCode.INPUT_CONTRACT_VIOLATION,
            "Input does not satisfy the scenario input contract.",
            http_status_code=400,
            details=[{"path": [str(part) for part in exc.absolute_path]}],
        ) from None


#: Safe client message and HTTP status per ``WorkflowRequestError`` code. Messages name the
#: caller-visible condition only — no internal state, identifiers or dependency details.
_REQUEST_ERROR_RESPONSES: dict[str, tuple[str, int]] = {
    "IDEMPOTENCY_KEY_REQUIRED": ("A bounded Idempotency-Key header is required.", 400),
    "EXECUTION_CONTEXT_INVALID": ("The execution context is not valid for this request.", 400),
    "WORKFLOW_STATE_TOO_LARGE": ("The request input exceeds the allowed size.", 413),
    "RUN_RUNTIME_SUSPENDED": ("The runtime is suspended and is not accepting new runs.", 503),
}


class _OpenAICompatibilityView(APIView):
    """Authorize and admit one canonical unified workflow request."""

    operation = "openai"
    required_protocol = ConsumerProtocol.REST
    _requested_alias = ""
    _requested_background = False

    def _extract(self, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        raise NotImplementedError

    def _adapt_success(self, body: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def _adapt_failure(self, body: dict[str, Any]) -> Response:
        """Default: the adapter's own body shape already carries the real status honestly
        (BUG-001) -- OpenAI's Responses contract keeps this a 200 with ``status != "completed"``
        and an ``error`` object. Override where the target contract has no such shape (see
        ``ChatCompletionsView``, which has no non-terminal-success completion shape at all)."""
        return Response(self._adapt_success(body), status=200)

    @transaction.atomic
    def _admit(self, request: Request) -> Response:
        started = time.monotonic()
        consumer = request.auth
        set_tenant_context(consumer.organization_id)
        if consumer.protocol != self.required_protocol:
            self._denial_reason = "PROTOCOL_DENIED"
            raise ApiError(
                ErrorCode.CAPABILITY_DENIED,
                "The credential is not enabled for this protocol.",
                http_status_code=403,
            )
        try:
            content_length = int(request.META.get("CONTENT_LENGTH") or 0)
        except (TypeError, ValueError):
            content_length = settings.GATEWAY_MAX_REQUEST_BYTES + 1
        if content_length > settings.GATEWAY_MAX_REQUEST_BYTES:
            raise ApiError(
                ErrorCode.VALIDATION_ERROR,
                "The request body is too large.",
                http_status_code=413,
            )

        alias, raw_input = self._extract(_require_mapping(request.data))
        resolved = resolve_active_binding(
            organization_id=consumer.organization_id,
            subject=consumer.subject,
            alias=alias,
        )
        if resolved is None:
            raise ApiError(
                ErrorCode.SCENARIO_NOT_ALLOWED,
                "The scenario alias is not available to this consumer.",
                http_status_code=403,
            )
        if Capability.WORKFLOW_RUN not in resolved.capabilities:
            raise ApiError(
                ErrorCode.CAPABILITY_DENIED,
                "The workflow_run capability is required.",
                http_status_code=403,
            )

        scenario = resolved.binding.scenario
        release, _is_canary = select_release(scenario=scenario, consumer=consumer)
        if release is None:
            raise ApiError(
                ErrorCode.RELEASE_NOT_AVAILABLE,
                "No active release for this scenario.",
                http_status_code=503,
                retryable=True,
            )
        input_payload = prepare_runtime_input(release, raw_input)
        _validate_input(release, input_payload)
        try:
            workflow_version = resolve_release_workflow(release)
        except WorkflowCompileError as exc:
            raise ApiError(
                ErrorCode.RUNTIME_NOT_AVAILABLE,
                "The workflow runtime is not available for this release.",
                http_status_code=503,
            ) from exc

        execution_mode = "background" if self._requested_background else "sync"
        context = issue_execution_context(
            organization_id=consumer.organization_id,
            project_id=scenario.project_id,
            scenario_id=scenario.id,
            scenario_alias=alias,
            consumer_id=consumer.id,
            capabilities=list(resolved.capabilities),
            release_id=release.id,
            request_id=getattr(request, "request_id", ""),
        )
        idempotency_key = str(
            getattr(self, "_idempotency_key", request.headers.get("Idempotency-Key", ""))
        )
        request_hash = compute_checksum(
            {"alias": alias, "input": input_payload, "operation": self.operation}
        )
        replay = self._check_idempotency(consumer, idempotency_key, request_hash)
        if replay is not None:
            return replay
        try:
            run, created = request_unified_run(
                release=release,
                consumer=consumer,
                workflow_version=workflow_version,
                execution_context=context,
                input_payload=input_payload,
                idempotency_key=idempotency_key,
                execution_mode=execution_mode,
            )
        except WorkflowRequestError as exc:
            if exc.code == "IDEMPOTENCY_CONFLICT":
                raise ApiError(
                    ErrorCode.IDEMPOTENCY_CONFLICT,
                    "Idempotency-Key was reused with a different request.",
                    http_status_code=409,
                ) from exc
            if exc.code == "UNSUPPORTED_EXECUTION_MODE":
                analysis = workflow_version.compiled_graph.get("execution_mode_analysis", {})
                reasons = analysis.get("reasons", {}).get(execution_mode, [])
                raise ApiError(
                    ErrorCode.VALIDATION_ERROR,
                    "The requested execution mode is not supported.",
                    http_status_code=400,
                    details=[
                        {
                            "path": ["background"],
                            "reason_codes": [
                                str(item.get("code"))
                                for item in reasons
                                if isinstance(item, dict) and item.get("code")
                            ],
                        }
                    ],
                ) from exc
            # Every remaining code used to answer "A bounded Idempotency-Key is required.",
            # so a suspended runtime or an invalid execution context sent the caller looking
            # at their header. Each code now says what actually happened; anything unmapped
            # stays a generic, content-free rejection rather than a wrong specific one.
            message, status = _REQUEST_ERROR_RESPONSES.get(
                exc.code, ("The request could not be accepted.", 400)
            )
            raise ApiError(ErrorCode.VALIDATION_ERROR, message, http_status_code=status) from exc

        if created and self._requested_background:
            dispatch_unified_background_run(
                run_id=run.id,
                organization_id=run.organization_id,
            )
        elif created:
            renew_sync_lease(
                organization_id=run.organization_id,
                run_id=run.id,
                lease_token=uuid.uuid4(),
                expires_at=min(run.deadline_at, timezone.now() + timedelta(seconds=30)),
            )
            run.refresh_from_db()

        body = {
            "request_id": getattr(request, "request_id", ""),
            "response_id": run.response_id,
            "scenario_alias": alias,
            "release_id": release.id,
            "run_id": str(run.id),
            "status": str(run.status),
        }
        self._store_idempotency(consumer, idempotency_key, request_hash, 202, body)
        record_event(
            actor_type="consumer",
            actor_id=consumer.subject,
            action="gateway.unified_run",
            outcome="success",
            organization_id=consumer.organization_id,
            resource_type="run",
            resource_id=str(run.id),
            reason="RUN_ADMITTED" if created else "RUN_ADMISSION_REPLAYED",
            request_id=getattr(request, "request_id", ""),
        )
        UsageEvent.objects.create(
            request_id=getattr(request, "request_id", ""),
            organization_id=consumer.organization_id,
            scenario_id=scenario.id,
            release_id=release.id,
            consumer_id=consumer.id,
            operation=self.operation,
            status="queued",
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        return Response(body, status=202)

    def post(self, request: Request) -> Response:
        if not settings.OPENAI_COMPAT_ENABLED:
            raise ApiError(
                ErrorCode.RUNTIME_NOT_AVAILABLE,
                "The compatibility endpoint is not enabled.",
                http_status_code=404,
            )
        admitted = self._admit(request)
        if self._requested_background:
            body = dict(admitted.data)
            body["_http_status"] = admitted.status_code
            response = Response(self._adapt_success(body), status=admitted.status_code)
            response["X-AgentHub-Run-Id"] = str(body["run_id"])
            return response
        return self._complete_sync_run(request, admitted)

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, ApiError):
            request = self.request
            consumer = getattr(request, "auth", None)
            if consumer is not None:
                with transaction.atomic():
                    set_tenant_context(consumer.organization_id)
                    record_event(
                        actor_type="consumer",
                        actor_id=consumer.subject,
                        action=f"gateway.{self.operation}",
                        outcome="deny",
                        organization_id=consumer.organization_id,
                        resource_type="scenario_alias",
                        resource_id=self._requested_alias,
                        reason=str(getattr(self, "_denial_reason", exc.code)),
                        request_id=getattr(request, "request_id", ""),
                    )
                    UsageEvent.objects.create(
                        request_id=getattr(request, "request_id", ""),
                        organization_id=consumer.organization_id,
                        consumer_id=consumer.id,
                        operation=self.operation,
                        status="error",
                        error_code=exc.code,
                    )
        response = super().handle_exception(exc)
        response.data = compatible_error(response.data)
        return response

    def _complete_sync_run(self, request: Request, admitted: Response) -> Response:
        run_id = uuid.UUID(str(admitted.data["run_id"]))
        with transaction.atomic():
            set_tenant_context(request.auth.organization_id)
            run = Run.objects.get(
                pk=run_id,
                consumer=request.auth,
                organization_id=request.auth.organization_id,
            )
            lease_token = run.sync_lease_token
        terminal = run.status in {
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.TIMED_OUT,
            RunStatus.CANCELLED,
        }
        if not terminal:
            if lease_token is None:
                raise ApiError(
                    ErrorCode.RUNTIME_NOT_AVAILABLE,
                    "The synchronous runtime did not acquire a lease.",
                    http_status_code=500,
                )
            execute_sync_run(
                organization_id=run.organization_id,
                run_id=run.id,
                lease_token=lease_token,
            )
        with transaction.atomic():
            set_tenant_context(request.auth.organization_id)
            run.refresh_from_db()
            record_event(
                actor_type="consumer",
                actor_id=request.auth.subject,
                action="gateway.unified_run_completed",
                outcome="success" if run.status == RunStatus.COMPLETED else "failure",
                organization_id=run.organization_id,
                resource_type="run",
                resource_id=str(run.id),
                reason=str(run.status),
                request_id=getattr(request, "request_id", ""),
            )
            UsageEvent.objects.create(
                request_id=getattr(request, "request_id", ""),
                organization_id=run.organization_id,
                scenario_id=run.scenario_id,
                release_id=run.release_id,
                consumer_id=run.consumer_id,
                operation=self.operation,
                status=str(run.status),
                input_tokens=run.input_token_count,
                output_tokens=run.output_token_count,
            )
        body = {
            "request_id": getattr(request, "request_id", ""),
            "response_id": run.response_id,
            "run_id": str(run.id),
            "status": str(run.status),
            "error_code": run.error_code,
            "output": run.redacted_state.get("output", {}),
            "usage": {
                "input_tokens": run.input_token_count,
                "output_tokens": run.output_token_count,
            },
            "_http_status": 200,
        }
        # BUG-001: a run that finished FAILED/TIMED_OUT/CANCELLED must not be reported as a
        # successful completion -- route through the adapter's honest-failure shape instead of
        # unconditionally calling `_adapt_success`.
        if run.status == RunStatus.COMPLETED:
            response = Response(self._adapt_success(body), status=200)
        else:
            response = self._adapt_failure(body)
        response["X-AgentHub-Run-Id"] = str(run.id)
        return response

    @staticmethod
    def _check_idempotency(consumer: Any, key: str, request_hash: str) -> Response | None:
        if not key:
            return None
        existing = IdempotencyRecord.objects.filter(consumer=consumer, key=key).first()
        if existing is None:
            return None
        if existing.request_hash != request_hash:
            raise ApiError(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "Idempotency-Key was reused with a different request.",
                http_status_code=409,
            )
        return Response(existing.response_body, status=existing.response_status)

    @staticmethod
    def _store_idempotency(
        consumer: Any,
        key: str,
        request_hash: str,
        status_code: int,
        body: dict[str, Any],
    ) -> None:
        if not key:
            return
        try:
            IdempotencyRecord.objects.create(
                consumer=consumer,
                key=key,
                request_hash=request_hash,
                response_status=status_code,
                response_body=body,
            )
        except IntegrityError:
            pass


class ChatCompletionsView(_OpenAICompatibilityView):
    operation = "openai.chat_completions"

    def _extract(self, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        alias, payload = parse_chat_request(data)
        self._requested_alias = alias
        self._requested_background = False
        return alias, payload

    def _adapt_success(self, body: dict[str, Any]) -> dict[str, Any]:
        return chat_response(body, self._requested_alias)

    def _adapt_failure(self, body: dict[str, Any]) -> Response:
        # BUG-001: OpenAI's chat.completion contract has no non-terminal-success shape -- a
        # failed generation is reported as an HTTP error, never as a completion object with a
        # fabricated `finish_reason: "stop"` and empty content.
        payload = compatible_error(
            {
                "error": {
                    "code": str(body.get("error_code") or "WORKFLOW_RUN_FAILED"),
                    "message": "The run did not complete successfully.",
                }
            }
        )
        return Response(payload, status=502)


class ResponsesView(_OpenAICompatibilityView):
    operation = "openai.responses"

    def _extract(self, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        alias, payload = parse_responses_request(data)
        self._requested_alias = alias
        self._requested_background = payload.get("__openai_background", False) is True
        return alias, payload

    def _adapt_success(self, body: dict[str, Any]) -> dict[str, Any]:
        return responses_response(body, self._requested_alias)


class RunStatusView(APIView):
    """Consumer and tenant scoped unified Run status."""

    @transaction.atomic
    def get(self, request: Request, run_id: uuid.UUID) -> Response:
        set_tenant_context(request.auth.organization_id)
        run = self._resolve(request, run_id)
        body: dict[str, Any] = {
            "run_id": str(run.id),
            "response_id": run.response_id,
            "status": str(run.status),
            "execution_mode": str(run.execution_mode),
            "release_id": run.release_id,
            "cancellation_state": str(run.cancellation_state),
            "error_code": run.error_code,
            "reason_code": run.reason_code,
        }
        output = run.redacted_state.get("output")
        if run.status == RunStatus.COMPLETED and isinstance(output, dict):
            body["output"] = output
        response = Response(body)
        response["X-AgentHub-Run-Id"] = str(run.id)
        return response

    @staticmethod
    def _resolve(request: Request, run_id: uuid.UUID) -> Run:
        run = Run.objects.filter(
            pk=run_id,
            consumer=request.auth,
            organization_id=request.auth.organization_id,
        ).first()
        if run is None:
            raise ApiError(ErrorCode.RUN_NOT_FOUND, "Run not found.", http_status_code=404)
        return run


class RunCancelView(APIView):
    """Idempotent consumer-scoped cooperative cancellation."""

    @transaction.atomic
    def post(self, request: Request, run_id: uuid.UUID) -> Response:
        set_tenant_context(request.auth.organization_id)
        run = RunStatusView._resolve(request, run_id)
        result = request_run_cancellation(
            organization_id=run.organization_id,
            run_id=run.id,
            reason_code="CLIENT_REQUESTED",
        )
        run.refresh_from_db()
        record_event(
            actor_type="consumer",
            actor_id=request.auth.subject,
            action="gateway.run_cancel",
            outcome="success",
            organization_id=run.organization_id,
            resource_type="run",
            resource_id=str(run.id),
            reason=f"RUN_CANCELLATION_{result.outcome.upper()}",
            request_id=getattr(request, "request_id", ""),
        )
        response = Response(
            {
                "run_id": str(run.id),
                "status": str(run.status),
                "cancellation_state": str(run.cancellation_state),
            }
        )
        response["X-AgentHub-Run-Id"] = str(run.id)
        return response
